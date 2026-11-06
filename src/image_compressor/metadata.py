"""EXIF / ICC 等元数据处理。"""

from __future__ import annotations

import logging

from PIL import Image, ImageOps

from .config import MetadataConfig

logger = logging.getLogger("image_compressor")

ORIENTATION_TAG = 0x0112
GPS_IFD_TAG = 0x8825

# 这些格式支持写入 EXIF / ICC；GIF、BMP 不支持，避免保存时报错
METADATA_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "TIFF"})


def normalize_orientation(image: Image.Image) -> Image.Image:
    """按 EXIF 方向旋转像素，并移除方向标记，避免二次旋转。"""
    try:
        transposed = ImageOps.exif_transpose(image)
    except Exception as exc:  # noqa: BLE001 - 损坏 EXIF 的兜底
        logger.warning("读取 EXIF 方向失败，按原方向处理：%s", exc)
        return image
    return transposed if transposed is not None else image


def _clean_exif(image: Image.Image, strip_gps: bool) -> bytes | None:
    try:
        exif = image.getexif()
        if not exif:
            return None
        exif.pop(ORIENTATION_TAG, None)
        if strip_gps:
            exif.pop(GPS_IFD_TAG, None)
            # getexif() 可能已缓存 GPS IFD，需要同步移除，否则仍会被序列化
            cached_ifds = getattr(exif, "_ifds", None)
            if isinstance(cached_ifds, dict):
                cached_ifds.pop(GPS_IFD_TAG, None)
        data = exif.tobytes()
        return data or None
    except Exception as exc:  # noqa: BLE001 - 异常 EXIF 的兜底
        logger.warning("处理 EXIF 失败，将不保留元数据：%s", exc)
        return None


def collect_metadata(
    image: Image.Image, config: MetadataConfig, target_format: str
) -> dict[str, bytes]:
    """生成 Pillow 保存参数；默认保留 EXIF 与 ICC，按需清除 GPS。"""
    if not config.keep or target_format not in METADATA_FORMATS:
        return {}

    result: dict[str, bytes] = {}
    exif = _clean_exif(image, config.strip_gps)
    if exif:
        result["exif"] = exif
    icc_profile = image.info.get("icc_profile")
    if icc_profile:
        result["icc_profile"] = icc_profile
    return result
