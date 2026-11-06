"""单张图片处理任务：读取、转换、压缩、原子写入。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .compressor import compress_frames
from .config import CompressConfig
from .converter import normalize_for_processing, prepare_frames
from .metadata import collect_metadata, normalize_orientation
from .optimizer import external_optimize
from .resizer import resize_image
from .scanner import ImageSource
from .utils import (
    FORMAT_EXTENSIONS,
    ImageCompressorError,
    atomic_write,
    check_free_space,
    ensure_heif_support,
    format_from_path,
    friendly_error,
    is_compressed_name,
)

logger = logging.getLogger("image_compressor")

Image.MAX_IMAGE_PIXELS = 500_000_000


class TaskStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TaskResult:
    source: str
    output: str | None
    status: str
    original_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    format: str | None = None
    quality: int | None = None
    scale: float = 1.0
    note: str = ""
    error: str | None = None

    @property
    def saved_size(self) -> int:
        return max(0, self.original_size - self.output_size)

    @property
    def ratio(self) -> float:
        if self.original_size <= 0:
            return 0.0
        return self.saved_size / self.original_size * 100


def build_output_path(source: ImageSource, config: CompressConfig) -> Path:
    source_format = format_from_path(source.path)
    target_format = config.output_format or source_format
    if target_format is None:
        raise ImageCompressorError(f"无法确定输出格式：{source.path}")
    # 未转换格式时保留原始扩展名（.jpeg/.tif/.heif 等不被改写）
    if target_format == source_format and source.path.suffix:
        extension = source.path.suffix
    else:
        extension = FORMAT_EXTENSIONS[target_format]

    if config.keep_structure and source.from_directory:
        relative = source.path.relative_to(source.root)
        parent = relative.parent
        stem = relative.stem
    else:
        parent = Path()
        stem = source.path.stem

    if config.suffix and not stem.endswith(config.suffix):
        stem = f"{stem}{config.suffix}"
    return config.output_dir / parent / f"{stem}{extension}"


_reserved_output_paths: set[Path] = set()
_reserved_lock = threading.Lock()


def _unique_reserved_path(path: Path) -> Path:
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists() and candidate.resolve() not in _reserved_output_paths:
            return candidate
        index += 1


def _claim_output_path(
    path: Path, config: CompressConfig, same_as_input: bool
) -> tuple[Path | None, str | None]:
    """在多线程间原子地占用输出路径，避免同名任务互相覆盖。"""
    if same_as_input and not config.overwrite:
        return None, "输出路径与原始文件相同，已跳过（如需覆盖请加 --overwrite）"

    key = path.resolve()
    with _reserved_lock:
        if key in _reserved_output_paths and not config.overwrite:
            if config.rename_conflicts:
                path = _unique_reserved_path(path)
                key = path.resolve()
            else:
                return None, "输出文件已存在或与其他任务冲突，已跳过（使用 --overwrite 覆盖）"
        if path.exists() and not config.overwrite:
            if config.rename_conflicts:
                path = _unique_reserved_path(path)
                key = path.resolve()
            else:
                return None, "输出文件已存在，已跳过（使用 --overwrite 覆盖）"
        _reserved_output_paths.add(key)
    return path, None


def _release_output_path(path: Path) -> None:
    with _reserved_lock:
        _reserved_output_paths.discard(path.resolve())


def _validate_image(path: Path) -> None:
    """目标体积已满足时也要确认文件可解码，避免把损坏文件当成功复制。"""
    try:
        with Image.open(path) as probe:
            probe.verify()
    except Exception:  # noqa: BLE001 - 部分格式不支持 verify，退回完整解码
        with Image.open(path) as probe:
            probe.load()


def _skip(source: Path, size: int, note: str, duration: float = 0.0) -> TaskResult:
    return TaskResult(
        source=str(source),
        output=None,
        status=TaskStatus.SKIPPED.value,
        original_size=size,
        duration=duration,
        note=note,
    )


def _load_frames(
    path: Path, target_format: str, all_frames: bool
) -> tuple[list[Image.Image], list[int], int, int, bool]:
    """只打开一次文件，按目标格式决定是否保留全部帧。"""
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(path) as opened:
        opened.load()
        total = getattr(opened, "n_frames", 1)
        keep_all = (target_format == "TIFF" and total > 1) or (
            all_frames and target_format in ("GIF", "WEBP") and total > 1
        )
        count = total if keep_all else 1
        loop = int(opened.info.get("loop", 0) or 0)
        for index in range(count):
            if index:
                opened.seek(index)
            frame = opened.copy()
            frame.load()
            frames.append(frame)
            duration = frame.info.get("duration", opened.info.get("duration", 100))
            durations.append(int(duration or 100))
    return frames, durations, loop, total, keep_all


def process_image(source: ImageSource, config: CompressConfig) -> TaskResult:
    """处理单张图片，所有异常都转换为失败结果，不影响其他任务。"""
    started = time.perf_counter()
    path = source.path
    original_size = 0
    reserved_output: Path | None = None

    try:
        if not path.exists():
            return TaskResult(
                source=str(path),
                output=None,
                status=TaskStatus.FAILED.value,
                duration=time.perf_counter() - started,
                error=f"文件不存在：{path}",
            )
        original_size = path.stat().st_size
        if original_size <= 0:
            return TaskResult(
                source=str(path),
                output=None,
                status=TaskStatus.FAILED.value,
                duration=time.perf_counter() - started,
                error="文件为空",
            )

        if config.min_size and original_size < config.min_size:
            return _skip(
                path,
                original_size,
                f"小于跳过阈值 {config.min_size} 字节",
                time.perf_counter() - started,
            )
        marker = config.suffix or "_compressed"
        if config.skip_compressed and is_compressed_name(path, marker):
            return _skip(
                path,
                original_size,
                "文件名包含压缩后缀，已跳过",
                time.perf_counter() - started,
            )

        source_format = format_from_path(path)
        if source_format is None:
            return TaskResult(
                source=str(path),
                output=None,
                status=TaskStatus.FAILED.value,
                original_size=original_size,
                duration=time.perf_counter() - started,
                error="不支持的图片格式",
            )
        if source_format == "HEIF" and not ensure_heif_support():
            return TaskResult(
                source=str(path),
                output=None,
                status=TaskStatus.FAILED.value,
                original_size=original_size,
                duration=time.perf_counter() - started,
                error="未安装 pillow-heif，无法处理 HEIC/HEIF",
            )

        target_format = config.output_format or source_format
        same_format = target_format == source_format
        target_bytes: int | None = None
        if config.target_size is not None:
            target_bytes = config.target_size
        elif config.ratio is not None:
            target_bytes = max(1, int(original_size * config.ratio))

        output_path = build_output_path(source, config)
        same_as_input = output_path.resolve() == path.resolve()
        output_path, skip_note = _claim_output_path(output_path, config, same_as_input)
        if skip_note or output_path is None:
            return _skip(
                path,
                original_size,
                skip_note or "输出路径冲突，已跳过",
                time.perf_counter() - started,
            )
        reserved_output = output_path

        # 原图已经满足目标体积且无需转换/缩放/清理元数据时，直接保留原数据
        if (
            target_bytes is not None
            and original_size <= target_bytes
            and same_format
            and not config.resize.enabled
            and config.metadata.keep
            and not config.metadata.strip_gps
        ):
            _validate_image(path)
            note = "原图已小于目标大小，保留原始文件数据"
            if same_as_input:
                return TaskResult(
                    source=str(path),
                    output=str(path),
                    status=TaskStatus.SUCCESS.value,
                    original_size=original_size,
                    output_size=original_size,
                    duration=time.perf_counter() - started,
                    format=target_format,
                    quality=None,
                    scale=1.0,
                    note=note,
                )
            data = path.read_bytes()
            check_free_space(output_path.parent, len(data) + 1024 * 1024)
            atomic_write(output_path, data)
            return TaskResult(
                source=str(path),
                output=str(output_path),
                status=TaskStatus.SUCCESS.value,
                original_size=original_size,
                output_size=output_path.stat().st_size,
                duration=time.perf_counter() - started,
                format=target_format,
                quality=None,
                scale=1.0,
                note=note,
            )

        frames, durations, loop, total_frames, keep_all = _load_frames(
            path, target_format, config.all_frames
        )
        if not frames:
            raise ImageCompressorError("图片没有可用帧")

        frames[0] = normalize_orientation(frames[0])
        metadata = collect_metadata(frames[0], config.metadata, target_format)

        note_parts: list[str] = []
        if total_frames > 1 and not keep_all:
            if source_format == "TIFF":
                note_parts.append("多页 TIFF 仅处理第一页")
            elif target_format not in ("TIFF", "GIF", "WEBP"):
                note_parts.append("动图仅处理第一帧")
            elif target_format in ("GIF", "WEBP"):
                note_parts.append("默认仅处理第一帧（使用 --all-frames 保留动画）")

        processed: list[Image.Image] = []
        for frame in frames:
            normalized = normalize_for_processing(frame)
            if config.resize.enabled:
                normalized = resize_image(normalized, config.resize)
            processed.append(normalized)
        prepared = prepare_frames(processed, target_format, config.background)

        outcome = compress_frames(
            prepared,
            target_format,
            config,
            target_bytes=target_bytes,
            durations=durations if len(prepared) > 1 else None,
            loop=loop if len(prepared) > 1 else None,
            metadata=metadata,
        )
        data = outcome.data
        quality = outcome.quality
        scale = outcome.scale
        if outcome.note:
            note_parts.append(outcome.note)

        preserved_original = False
        if (
            same_format
            and not config.resize.enabled
            and len(data) >= original_size
            and config.metadata.keep
            and not config.metadata.strip_gps
        ):
            data = path.read_bytes()
            preserved_original = True
            quality = None
            note_parts.append("压缩后体积未减小，已保留原始文件数据")

        if preserved_original and same_as_input:
            return TaskResult(
                source=str(path),
                output=str(path),
                status=TaskStatus.SUCCESS.value,
                original_size=original_size,
                output_size=original_size,
                duration=time.perf_counter() - started,
                format=target_format,
                quality=quality,
                scale=scale,
                note="；".join(note_parts),
            )

        check_free_space(output_path.parent, len(data) + 1024 * 1024)
        atomic_write(output_path, data)
        output_size = output_path.stat().st_size

        if config.external_optimize and not preserved_original:
            changed, optimize_note = external_optimize(output_path, target_format)
            if changed:
                output_size = output_path.stat().st_size
                note_parts.append(optimize_note)

        return TaskResult(
            source=str(path),
            output=str(output_path),
            status=TaskStatus.SUCCESS.value,
            original_size=original_size,
            output_size=output_size,
            duration=time.perf_counter() - started,
            format=target_format,
            quality=quality,
            scale=scale,
            note="；".join(note_parts),
        )

    except UnidentifiedImageError:
        logger.error("无法识别图片：%s", path)
        return TaskResult(
            source=str(path),
            output=None,
            status=TaskStatus.FAILED.value,
            original_size=original_size,
            duration=time.perf_counter() - started,
            error="无法识别的图片格式或文件已损坏",
        )
    except Image.DecompressionBombError:
        logger.error("图片像素数量过大：%s", path)
        return TaskResult(
            source=str(path),
            output=None,
            status=TaskStatus.FAILED.value,
            original_size=original_size,
            duration=time.perf_counter() - started,
            error="图片像素数量过大，已拒绝处理",
        )
    except MemoryError:
        logger.error("内存不足：%s", path)
        return TaskResult(
            source=str(path),
            output=None,
            status=TaskStatus.FAILED.value,
            original_size=original_size,
            duration=time.perf_counter() - started,
            error="内存不足，请降低并发数后重试",
        )
    except Exception as exc:
        logger.exception("处理图片失败：%s", path)
        return TaskResult(
            source=str(path),
            output=None,
            status=TaskStatus.FAILED.value,
            original_size=original_size,
            duration=time.perf_counter() - started,
            error=friendly_error(exc),
        )
    finally:
        if reserved_output is not None:
            _release_output_path(reserved_output)
