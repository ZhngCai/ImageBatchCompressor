"""通用工具：格式映射、参数解析、日志、原子写入等。"""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageColor

LOGGER_NAME = "image_compressor"
logger = logging.getLogger(LOGGER_NAME)

EXTENSION_FORMATS: dict[str, str] = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".gif": "GIF",
    ".heic": "HEIF",
    ".heif": "HEIF",
}

FORMAT_EXTENSIONS: dict[str, str] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tif",
    "GIF": ".gif",
    "HEIF": ".heic",
}

FORMAT_ALIASES: dict[str, str] = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tif": "TIFF",
    "tiff": "TIFF",
    "gif": "GIF",
    "heic": "HEIF",
    "heif": "HEIF",
}

SUPPORTED_EXTENSIONS = frozenset(EXTENSION_FORMATS)
LOSSY_FORMATS = frozenset({"JPEG", "WEBP", "HEIF"})
ANIMATED_FORMATS = frozenset({"GIF", "WEBP", "TIFF"})

_SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([kmgtp]?i?b)?$", re.IGNORECASE)
_SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "KIB": 1024,
    "MB": 1024**2,
    "MIB": 1024**2,
    "GB": 1024**3,
    "GIB": 1024**3,
    "TB": 1024**4,
    "TIB": 1024**4,
}

_heif_registered: bool | None = None


class ImageCompressorError(Exception):
    """项目内可预期的业务异常。"""


class UnsupportedFormatError(ImageCompressorError):
    """不支持的图片格式。"""


def format_from_path(path: Path | str) -> str | None:
    return EXTENSION_FORMATS.get(Path(path).suffix.lower())


def is_supported_image(path: Path | str) -> bool:
    return format_from_path(path) is not None


def normalize_format(value: str) -> str:
    fmt = FORMAT_ALIASES.get(value.strip().lower())
    if fmt is None:
        raise UnsupportedFormatError(f"不支持的输出格式：{value}")
    if fmt == "HEIF" and not ensure_heif_support():
        raise UnsupportedFormatError(
            "当前环境未安装 pillow-heif，无法处理 HEIC/HEIF。"
            "请执行 pip install pillow-heif 后重试。"
        )
    return fmt


def ensure_heif_support() -> bool:
    """按需注册 HEIF 插件，未安装时返回 False，不影响基础功能。"""
    global _heif_registered
    if _heif_registered is None:
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
            _heif_registered = True
            logger.debug("已启用 HEIC/HEIF 支持")
        except Exception:  # noqa: BLE001 - 依赖缺失时走此分支
            _heif_registered = False
    return _heif_registered


def parse_size(value: str | float) -> int:
    """解析 500KB、10MB、1.5GB 等大小写法，统一按 1024 进制。"""
    if isinstance(value, (int, float)):
        size = int(value)
        if size <= 0:
            raise ValueError("大小必须大于 0")
        return size

    text = str(value).strip().replace("_", "").replace(" ", "")
    match = _SIZE_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(f"无法识别的大小：{value}，示例：500KB、10MB")
    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    size = int(number * _SIZE_UNITS[unit])
    if size <= 0:
        raise ValueError("大小必须大于 0")
    return size


def parse_ratio(value: str | float) -> float:
    """解析压缩比例：80、80%、0.8 均表示保留原体积的 80%。"""
    if isinstance(value, (int, float)):
        ratio = float(value)
        if ratio > 1:
            ratio /= 100
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("压缩比例不能为空")
        is_percent = text.endswith("%")
        number = text.rstrip("%").strip()
        try:
            ratio = float(number)
        except ValueError as exc:
            raise ValueError(f"无法识别的压缩比例：{value}") from exc
        if is_percent or ratio > 1:
            ratio /= 100
    if not 0 < ratio <= 1:
        raise ValueError("压缩比例必须位于 (0, 1] 区间，例如 80% 或 0.8")
    return ratio


def parse_color(value: str) -> tuple[int, int, int]:
    """解析 #fff、white、255,255,255 等颜色写法。"""
    text = value.strip()
    if "," in text:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) != 3:
            raise ValueError(f"无法识别的颜色：{value}")
        try:
            rgb = tuple(int(part) for part in parts)
        except ValueError as exc:
            raise ValueError(f"无法识别的颜色：{value}") from exc
        if any(channel < 0 or channel > 255 for channel in rgb):
            raise ValueError("颜色通道必须位于 0-255")
        return rgb  # type: ignore[return-value]
    try:
        rgb = ImageColor.getrgb(text)
    except ValueError as exc:
        raise ValueError(f"无法识别的颜色：{value}") from exc
    return rgb[:3]


def human_size(size: float) -> str:
    value = float(max(size, 0))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f}".rstrip("0").rstrip(".") + f" {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def default_workers() -> int:
    """默认并发数：不超过 8，避免同时解码过多大图导致内存峰值过高。"""
    return max(1, min(8, os.cpu_count() or 2))


def setup_logging(log_dir: Path, level: str = "INFO") -> Path:
    """初始化统一日志，同时输出到控制台和 logs 目录。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"image-compress_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console_handler)
    return log_path


def unique_path(path: Path) -> Path:
    """为同名文件生成 _1、_2 后缀，避免覆盖。"""
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def atomic_write(path: Path, data: bytes) -> None:
    """先写临时文件再原子替换，避免中断后留下半张图片。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temp_path.open("wb") as handle:
            handle.write(data)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def ensure_output_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise ImageCompressorError(f"输出目录无写入权限：{path}") from exc
    except OSError as exc:
        raise ImageCompressorError(f"无法创建输出目录：{path}（{exc}）") from exc
    if not path.is_dir():
        raise ImageCompressorError(f"输出路径不是目录：{path}")


def check_free_space(path: Path, required: int) -> None:
    """写入前检查磁盘剩余空间，避免写到一半才失败。"""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        stats = os.statvfs(probe)
        free = stats.f_bavail * stats.f_frsize
    except (AttributeError, OSError):  # pragma: no cover - Windows 无 statvfs
        import shutil

        try:
            free = shutil.disk_usage(probe).free
        except OSError:
            return
    if free < required:
        raise ImageCompressorError(
            f"磁盘空间不足：需要 {human_size(required)}，可用 {human_size(free)}"
        )


def validate_clean_output_dir(output_dir: Path, sources: list[Path]) -> None:
    """清理前做安全检查，避免误删项目、主目录或输入文件。"""
    resolved = output_dir.resolve()
    home = Path.home().resolve()
    cwd = Path.cwd().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    if resolved.parent == resolved:
        raise ImageCompressorError(f"拒绝清理文件系统根目录：{resolved}")
    if resolved == home:
        raise ImageCompressorError(f"拒绝清理用户主目录：{resolved}")
    if resolved == temp_root:
        raise ImageCompressorError(f"拒绝清理系统临时目录：{resolved}")
    if cwd == resolved or cwd.is_relative_to(resolved):
        raise ImageCompressorError(f"拒绝清理当前工作目录或其上级目录：{resolved}")
    if home.is_relative_to(resolved) or temp_root.is_relative_to(resolved):
        raise ImageCompressorError(f"拒绝清理包含用户目录或临时目录的上级目录：{resolved}")

    for source in sources:
        source_path = source.resolve()
        if source_path == resolved or source_path.is_relative_to(resolved):
            raise ImageCompressorError(f"输出目录包含输入文件，拒绝清理：{source_path}")


def clean_output_directory(
    output_dir: Path, preserve_paths: tuple[Path, ...] = ()
) -> tuple[int, int]:
    """清空输出目录内容，保留 .gitkeep 和指定文件/目录。"""
    preserve = {path.resolve() for path in preserve_paths}
    removed_files = 0
    removed_dirs = 0

    for entry in list(output_dir.iterdir()):
        if entry.name == ".gitkeep":
            continue
        entry_resolved = entry.resolve()
        if any(
            path == entry_resolved or path.is_relative_to(entry_resolved)
            for path in preserve
        ):
            continue
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
                removed_dirs += 1
            else:
                entry.unlink()
                removed_files += 1
        except OSError as exc:
            raise ImageCompressorError(
                f"清理输出目录失败：{entry}（{friendly_error(exc)}）"
            ) from exc
    return removed_files, removed_dirs


def friendly_error(exc: BaseException) -> str:
    """把常见系统异常转换成可读中文提示。"""
    if isinstance(exc, ImageCompressorError):
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return f"文件不存在：{exc.filename or exc}"
    if isinstance(exc, PermissionError):
        return f"权限不足：{exc.filename or exc}"
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return "磁盘空间不足"
        if exc.errno in (errno.EACCES, errno.EPERM):
            return f"权限不足：{exc.filename or exc}"
        if exc.errno == errno.EMFILE:
            return "打开的文件过多，请降低并发数"
        return f"系统错误：{exc}"
    return str(exc) or exc.__class__.__name__


def is_compressed_name(path: Path, suffix: str) -> bool:
    return bool(suffix) and path.stem.endswith(suffix)


def safe_load_image(path: Path) -> Image.Image:
    """打开并立即加载图片，确保文件句柄及时释放。"""
    with Image.open(path) as image:
        image.load()
        if getattr(image, "n_frames", 1) > 1:
            image.seek(0)
        return image.copy()
