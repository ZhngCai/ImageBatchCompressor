"""压缩算法：质量压缩、目标体积搜索、压缩比例。"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .config import CompressConfig
from .converter import encode_image, prepare_frames, scale_frames
from .utils import LOSSY_FORMATS, human_size


@dataclass(frozen=True)
class CompressionOutcome:
    data: bytes
    quality: int | None
    scale: float = 1.0
    note: str = ""


def _clamp_quality(value: int, minimum: int = 1) -> int:
    return max(minimum, min(100, int(value)))


def _search_quality(
    frames: list[Image.Image],
    target_format: str,
    config: CompressConfig,
    target_bytes: int,
    metadata: dict[str, bytes],
    durations: list[int] | None,
    loop: int | None,
) -> CompressionOutcome:
    """二分搜索满足目标体积的最高质量；先试较高质量再向下调整。"""
    minimum = _clamp_quality(config.min_quality)
    maximum = _clamp_quality(max(95, config.quality))
    minimum = min(minimum, maximum)

    cache: dict[int, tuple[int, bytes]] = {}

    def attempt(quality: int) -> tuple[int, bytes]:
        quality = _clamp_quality(quality, minimum)
        if quality not in cache:
            data = encode_image(
                frames,
                target_format,
                quality,
                metadata,
                durations=durations,
                loop=loop,
            )
            cache[quality] = (len(data), data)
        return cache[quality]

    start = _clamp_quality(config.quality, minimum)
    start = min(start, maximum)
    start_size, start_data = attempt(start)

    best_quality: int | None = None
    best_data: bytes | None = None

    if start_size <= target_bytes:
        best_quality, best_data = start, start_data
        low, high = start + 1, maximum
    else:
        low, high = minimum, start - 1

    while low <= high:
        middle = (low + high) // 2
        size, data = attempt(middle)
        if size <= target_bytes:
            best_quality, best_data = middle, data
            low = middle + 1
        else:
            high = middle - 1

    if best_quality is None:
        size, data = attempt(minimum)
        return CompressionOutcome(
            data=data,
            quality=minimum,
            scale=1.0,
            note=(
                f"无法达到目标大小：最低质量 {minimum} 时仍有 {human_size(size)}，"
                f"目标为 {human_size(target_bytes)}"
            ),
        )

    return CompressionOutcome(
        data=best_data or b"", quality=best_quality, scale=1.0
    )


def _search_scale(
    frames: list[Image.Image],
    target_format: str,
    config: CompressConfig,
    target_bytes: int,
    metadata: dict[str, bytes],
    durations: list[int] | None,
    loop: int | None,
) -> CompressionOutcome:
    """无损格式无法靠质量调体积，用二分搜索找到满足目标的最大尺寸。"""
    base_data = encode_image(
        frames,
        target_format,
        config.quality,
        metadata,
        durations=durations,
        loop=loop,
    )
    if len(base_data) <= target_bytes:
        return CompressionOutcome(data=base_data, quality=None, scale=1.0)

    cache: dict[float, bytes] = {1.0: base_data}

    def attempt(scale: float) -> bytes:
        key = round(scale, 4)
        if key not in cache:
            scaled = prepare_frames(
                scale_frames(frames, key), target_format, config.background
            )
            cache[key] = encode_image(
                scaled,
                target_format,
                config.quality,
                metadata,
                durations=durations,
                loop=loop,
            )
        return cache[key]

    smallest_data = base_data
    smallest_scale = 1.0
    best_data: bytes | None = None
    best_scale = 1.0
    low, high = 0.1, 0.99

    for _ in range(7):
        middle = round((low + high) / 2, 4)
        data = attempt(middle)
        if len(data) < len(smallest_data):
            smallest_data, smallest_scale = data, middle
        if len(data) <= target_bytes:
            best_data, best_scale = data, middle
            low = middle
        else:
            high = middle

    if best_data is None:
        data = attempt(0.1)
        if len(data) < len(smallest_data):
            smallest_data, smallest_scale = data, 0.1
        if len(data) <= target_bytes:
            best_data, best_scale = data, 0.1

    if best_data is None:
        return CompressionOutcome(
            data=smallest_data,
            quality=None,
            scale=smallest_scale,
            note=(
                f"无法达到目标大小：已缩放至 {smallest_scale * 100:.0f}%，"
                f"体积为 {human_size(len(smallest_data))}，"
                f"目标为 {human_size(target_bytes)}"
            ),
        )

    return CompressionOutcome(
        data=best_data,
        quality=None,
        scale=best_scale,
        note=f"为达到目标大小，已缩放至原尺寸的 {best_scale * 100:.1f}%",
    )


def compress_frames(
    frames: list[Image.Image],
    target_format: str,
    config: CompressConfig,
    *,
    target_bytes: int | None = None,
    durations: list[int] | None = None,
    loop: int | None = None,
    metadata: dict[str, bytes] | None = None,
) -> CompressionOutcome:
    """按配置选择质量、目标体积或比例模式执行压缩。"""
    metadata = metadata or {}
    effective_target = target_bytes
    if effective_target is None and config.target_size is not None:
        effective_target = config.target_size

    if effective_target is None:
        data = encode_image(
            frames,
            target_format,
            config.quality,
            metadata,
            durations=durations,
            loop=loop,
        )
        quality = config.quality if target_format in LOSSY_FORMATS else None
        return CompressionOutcome(data=data, quality=quality)

    if target_format in LOSSY_FORMATS:
        return _search_quality(
            frames,
            target_format,
            config,
            effective_target,
            metadata,
            durations,
            loop,
        )
    return _search_scale(
        frames,
        target_format,
        config,
        effective_target,
        metadata,
        durations,
        loop,
    )
