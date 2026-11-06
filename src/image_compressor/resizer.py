"""尺寸计算与高质量缩放。"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .config import ResizeConfig


@dataclass(frozen=True)
class ResizeResult:
    width: int
    height: int
    scale: float

    @property
    def changed(self) -> bool:
        return self.scale < 1.0


def calculate_size(
    original: tuple[int, int], options: ResizeConfig
) -> ResizeResult:
    """按所有约束中最严格的一项缩放，始终保持比例且禁止放大。"""
    width, height = original
    if width <= 0 or height <= 0:
        raise ValueError(f"图片尺寸异常：{width}x{height}")

    scale = 1.0
    if options.percent is not None:
        scale = min(scale, options.percent / 100)
    if options.width is not None:
        scale = min(scale, options.width / width)
    if options.height is not None:
        scale = min(scale, options.height / height)
    if options.max_width is not None:
        scale = min(scale, options.max_width / width)
    if options.max_height is not None:
        scale = min(scale, options.max_height / height)

    scale = max(0.0, min(scale, 1.0))
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    if new_width == width and new_height == height:
        return ResizeResult(width, height, 1.0)
    return ResizeResult(new_width, new_height, scale)


def resize_image(image: Image.Image, options: ResizeConfig) -> Image.Image:
    """使用 LANCZOS 重采样，超大比例缩小时启用 reducing_gap 加速。"""
    if not options.enabled:
        return image
    result = calculate_size(image.size, options)
    if not result.changed:
        return image
    try:
        return image.resize(
            (result.width, result.height),
            resample=options.resample,
            reducing_gap=3.0,
        )
    except (ValueError, OSError):
        # 少数特殊模式（如 16 位灰度）不支持 LANCZOS，退回双三次插值
        return image.resize(
            (result.width, result.height), resample=Image.Resampling.BICUBIC
        )
