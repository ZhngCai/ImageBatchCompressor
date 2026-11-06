"""格式转换测试：透明通道、背景色、格式互转。"""

from __future__ import annotations

from pathlib import Path

from conftest import make_transparent
from PIL import Image

from image_compressor.config import CompressConfig
from image_compressor.scanner import ImageSource
from image_compressor.worker import process_image


def _source(path: Path) -> ImageSource:
    return ImageSource(path=path, root=path.parent)


def test_png_to_jpeg_uses_white_background(
    transparent_png: Path, output_dir: Path
) -> None:
    config = CompressConfig(
        output_dir=output_dir,
        output_format="JPEG",
        background=(255, 255, 255),
        quality=90,
    )
    result = process_image(_source(transparent_png), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output.endswith(".jpg")
    with Image.open(result.output) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        corner = image.convert("RGB").getpixel((2, 2))
        center = image.convert("RGB").getpixel((200, 150))
        assert all(channel > 245 for channel in corner)
        assert center[0] > 220 and center[1] < 40


def test_png_to_webp_keeps_alpha(
    transparent_png: Path, output_dir: Path
) -> None:
    config = CompressConfig(
        output_dir=output_dir, output_format="WEBP", quality=80
    )
    result = process_image(_source(transparent_png), config)

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.format == "WEBP"
        assert image.mode == "RGBA"
        alpha = image.getchannel("A")
        assert alpha.getpixel((2, 2)) < 10
        assert alpha.getpixel((200, 150)) > 240


def test_jpeg_to_png(photo_path: Path, output_dir: Path) -> None:
    config = CompressConfig(output_dir=output_dir, output_format="PNG")
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output.endswith(".png")
    with Image.open(result.output) as image:
        assert image.format == "PNG"
        assert image.size == (900, 600)


def test_bmp_to_jpeg(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "sample.bmp"
    make_transparent().convert("RGB").save(source)

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, output_format="JPEG")
    )

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.format == "JPEG"


def test_palette_png_with_transparency_to_webp(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "palette.png"
    make_transparent().convert("P", palette=Image.Palette.ADAPTIVE).save(
        source, transparency=0
    )

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, output_format="WEBP")
    )

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.format == "WEBP"
        assert "A" in image.getbands()


def test_webp_to_jpeg(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "source.webp"
    make_transparent().convert("RGB").save(source, "WEBP", quality=90)

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, output_format="JPEG")
    )

    assert result.status == "success"
    assert result.output is not None
    assert result.output.endswith(".jpg")
    with Image.open(result.output) as image:
        assert image.format == "JPEG"


def test_png_to_jpeg_custom_background(
    transparent_png: Path, output_dir: Path
) -> None:
    config = CompressConfig(
        output_dir=output_dir,
        output_format="JPEG",
        background=(0, 0, 255),
        quality=95,
    )
    result = process_image(_source(transparent_png), config)

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        red, green, blue = image.convert("RGB").getpixel((2, 2))
        assert blue > 200
        assert red < 60
        assert green < 60
