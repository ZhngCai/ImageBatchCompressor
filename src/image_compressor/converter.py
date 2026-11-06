"""格式转换与图片编码。"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageCms

from .config import MetadataConfig
from .metadata import collect_metadata
from .utils import ImageCompressorError

logger = logging.getLogger("image_compressor")

METADATA_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "TIFF"})


def has_alpha(image: Image.Image) -> bool:
    return (
        image.mode in ("RGBA", "LA", "PA", "RGBa")
        or "A" in image.getbands()
        or (image.mode == "P" and "transparency" in image.info)
    )


def normalize_for_processing(image: Image.Image) -> Image.Image:
    """统一特殊模式，避免缩放和保存时出现颜色或透明异常。"""
    if image.mode == "P":
        return image.convert("RGBA" if "transparency" in image.info else "RGB")
    if image.mode == "1":
        return image.convert("L")
    if image.mode == "PA":
        return image.convert("RGBA")
    return image


def _cmyk_to_rgb(image: Image.Image) -> Image.Image:
    """优先使用嵌入 ICC 做色彩管理，缺失时退回 Pillow 转换。"""
    profile = image.info.get("icc_profile")
    if profile:
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            destination = ImageCms.createProfile("sRGB")
            return ImageCms.profileToProfile(
                image, source, destination, outputMode="RGB"
            )
        except Exception as exc:  # noqa: BLE001 - 异常 ICC 兜底
            logger.warning("CMYK ICC 转换失败，使用普通转换：%s", exc)
    return image.convert("RGB")


def _flatten_alpha(
    image: Image.Image, background: tuple[int, int, int]
) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*background, 255))
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")


def _to_gif_frame(image: Image.Image) -> Image.Image:
    """转换为 GIF 调色板；有透明像素时保留 1 位透明通道。"""
    if image.mode == "P":
        return image
    if has_alpha(image):
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        if alpha.getextrema()[0] >= 128:
            return rgba.convert("RGB").convert(
                "P", palette=Image.Palette.ADAPTIVE, colors=256
            )
        palette_image = rgba.convert("RGB").quantize(
            colors=255, method=Image.Quantize.MEDIANCUT
        )
        palette = palette_image.getpalette() or []
        palette.extend([0] * (768 - len(palette)))
        palette[255 * 3 : 255 * 3 + 3] = [0, 0, 0]
        palette_image.putpalette(palette)
        transparent_mask = alpha.point(lambda value: 255 if value < 128 else 0)
        palette_image.paste(255, mask=transparent_mask)
        palette_image.info["transparency"] = 255
        return palette_image
    return image.convert("RGB").convert(
        "P", palette=Image.Palette.ADAPTIVE, colors=256
    )


def prepare_frame(
    image: Image.Image, target_format: str, background: tuple[int, int, int]
) -> Image.Image:
    """把图片转换为目标格式可安全保存的模式。"""
    if target_format == "JPEG":
        if image.mode == "CMYK":
            return _cmyk_to_rgb(image)
        if has_alpha(image):
            return _flatten_alpha(image, background)
        if image.mode in ("RGB", "L"):
            return image
        if image.mode in ("I", "I;16", "I;16L", "I;16B", "F"):
            return image.convert("L")
        return image.convert("RGB")

    if target_format == "WEBP":
        if image.mode == "CMYK":
            return _cmyk_to_rgb(image)
        if has_alpha(image):
            return image.convert("RGBA")
        if image.mode == "RGB":
            return image
        if image.mode == "L":
            return image.convert("RGB")
        return image.convert("RGB")

    if target_format == "PNG":
        if image.mode == "CMYK":
            return _cmyk_to_rgb(image)
        if image.mode == "P":
            return image
        if image.mode in ("RGBA", "LA", "L", "RGB", "1", "I;16"):
            return image
        if image.mode in ("I;16L", "I;16B", "I"):
            return image.convert("I;16")
        if image.mode == "F":
            return image.convert("L")
        return image.convert("RGBA" if has_alpha(image) else "RGB")

    if target_format == "BMP":
        if image.mode == "CMYK":
            return _cmyk_to_rgb(image)
        if has_alpha(image):
            return _flatten_alpha(image, background)
        if image.mode in ("RGB", "L", "1"):
            return image
        if image.mode in ("I", "I;16", "I;16L", "I;16B", "F"):
            return image.convert("L")
        return image.convert("RGB")

    if target_format == "TIFF":
        if image.mode == "CMYK":
            return _cmyk_to_rgb(image)
        if image.mode == "PA":
            return image.convert("RGBA")
        if image.mode == "P" and "transparency" in image.info:
            return image.convert("RGBA")
        return image

    if target_format == "GIF":
        return _to_gif_frame(image)

    if target_format == "HEIF":
        if image.mode == "CMYK":
            return _cmyk_to_rgb(image)
        if has_alpha(image):
            return image.convert("RGBA")
        return image.convert("RGB")

    raise ImageCompressorError(f"不支持的输出格式：{target_format}")


def prepare_frames(
    frames: list[Image.Image],
    target_format: str,
    background: tuple[int, int, int],
) -> list[Image.Image]:
    return [prepare_frame(frame, target_format, background) for frame in frames]


def _jpeg_save_kwargs(quality: int) -> dict[str, object]:
    # 高质量时减少色度抽样，避免文字和边缘出现明显色块
    if quality >= 90:
        subsampling = 0
    elif quality >= 80:
        subsampling = 1
    else:
        subsampling = 2
    return {
        "quality": quality,
        "optimize": True,
        "progressive": True,
        "subsampling": subsampling,
    }


def encode_image(
    frames: list[Image.Image],
    target_format: str,
    quality: int,
    metadata: dict[str, bytes],
    durations: list[int] | None = None,
    loop: int | None = None,
) -> bytes:
    """把已准备好的帧编码为字节；多帧仅 GIF/WebP/TIFF 支持。"""
    if not frames:
        raise ImageCompressorError("没有可编码的图片帧")
    if target_format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF", "HEIF"}:
        raise ImageCompressorError(f"不支持的输出格式：{target_format}")

    first = frames[0]
    buffer = io.BytesIO()
    save_metadata = metadata if target_format in METADATA_FORMATS else {}

    try:
        if target_format == "JPEG":
            first.save(
                buffer,
                "JPEG",
                **_jpeg_save_kwargs(quality),
                **save_metadata,
            )
        elif target_format == "PNG":
            first.save(
                buffer,
                "PNG",
                optimize=True,
                compress_level=9,
                **save_metadata,
            )
        elif target_format == "WEBP":
            if len(frames) > 1:
                first.save(
                    buffer,
                    "WEBP",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations or [100] * len(frames),
                    loop=loop or 0,
                    quality=quality,
                    method=6,
                    **save_metadata,
                )
            else:
                first.save(
                    buffer,
                    "WEBP",
                    quality=quality,
                    method=6,
                    **save_metadata,
                )
        elif target_format == "BMP":
            first.save(buffer, "BMP")
        elif target_format == "TIFF":
            if len(frames) > 1:
                first.save(
                    buffer,
                    "TIFF",
                    save_all=True,
                    append_images=frames[1:],
                    compression="tiff_deflate",
                    **save_metadata,
                )
            else:
                first.save(
                    buffer,
                    "TIFF",
                    compression="tiff_deflate",
                    **save_metadata,
                )
        elif target_format == "GIF":
            if len(frames) > 1:
                first.save(
                    buffer,
                    "GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations or [100] * len(frames),
                    loop=loop or 0,
                    optimize=True,
                    disposal=2,
                )
            else:
                first.save(buffer, "GIF", optimize=True)
        else:  # HEIF
            first.save(buffer, "HEIF", quality=quality)
    except (ValueError, OSError) as exc:
        raise ImageCompressorError(f"{target_format} 编码失败：{exc}") from exc

    data = buffer.getvalue()
    if not data:
        raise ImageCompressorError(f"{target_format} 编码结果为空")
    return data


def scale_frames(frames: list[Image.Image], scale: float) -> list[Image.Image]:
    """按比例缩小已准备的帧，用于无损格式的目标体积搜索。"""
    scaled: list[Image.Image] = []
    for frame in frames:
        base = frame.convert("RGBA") if frame.mode in ("P", "PA") else frame
        width, height = base.size
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        try:
            resized = base.resize(
                size, resample=Image.Resampling.LANCZOS, reducing_gap=3.0
            )
        except (ValueError, OSError):
            resized = base.resize(size, resample=Image.Resampling.BICUBIC)
        scaled.append(resized)
    return scaled


def metadata_for(
    image: Image.Image, config: MetadataConfig, target_format: str
) -> dict[str, bytes]:
    return collect_metadata(image, config, target_format)
