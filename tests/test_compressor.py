"""压缩核心测试：JPEG、PNG、WebP、目标大小、比例、特殊模式。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_photo
from PIL import Image

from image_compressor.config import CompressConfig
from image_compressor.scanner import ImageSource
from image_compressor.worker import process_image


def _source(path: Path) -> ImageSource:
    return ImageSource(path=path, root=path.parent)


def test_jpeg_quality_compression(photo_path: Path, output_dir: Path) -> None:
    config = CompressConfig(output_dir=output_dir, quality=60)
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size < result.original_size
    assert result.quality == 60
    with Image.open(result.output) as image:
        assert image.format == "JPEG"
        assert image.size == (900, 600)
        assert image.mode == "RGB"


def test_png_lossless_optimization(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "photo.png"
    make_photo().save(source)
    original = source.stat().st_size

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size <= original
    with Image.open(result.output) as image:
        assert image.format == "PNG"
        assert image.size == (900, 600)


def test_webp_compression(photo_path: Path, output_dir: Path) -> None:
    config = CompressConfig(
        output_dir=output_dir, quality=70, output_format="WEBP"
    )
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output.endswith(".webp")
    assert result.output_size < result.original_size
    with Image.open(result.output) as image:
        assert image.format == "WEBP"
        assert image.size == (900, 600)


def test_target_size_binary_search(photo_path: Path, output_dir: Path) -> None:
    target = photo_path.stat().st_size // 4
    config = CompressConfig(output_dir=output_dir, target_size=target)
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size <= target
    assert result.quality is not None
    assert "无法达到目标大小" not in result.note
    with Image.open(result.output) as image:
        assert image.format == "JPEG"


def test_target_size_unreachable_reports_reason(
    photo_path: Path, output_dir: Path
) -> None:
    config = CompressConfig(
        output_dir=output_dir,
        target_size=100,
        quality=95,
        min_quality=90,
    )
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size > 100
    assert "无法达到目标大小" in result.note


def test_ratio_mode(photo_path: Path, output_dir: Path) -> None:
    original = photo_path.stat().st_size
    config = CompressConfig(output_dir=output_dir, ratio=0.5)
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size <= original * 0.5
    with Image.open(result.output) as image:
        assert image.format == "JPEG"


def test_quality_mode_never_enlarges_small_jpeg(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "solid.jpg"
    Image.new("RGB", (64, 64), (120, 140, 160)).save(source, quality=90)
    original = source.stat().st_size

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size <= original


def test_cmyk_jpeg_is_converted_to_rgb(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (120, 90), (0, 255, 255, 0)).save(source, quality=95)

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.mode == "RGB"
        red, green, blue = image.getpixel((10, 10))
        assert red > 180
        assert green < 90
        assert blue < 90


def test_16bit_png_is_processed(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "gray16.png"
    Image.new("I;16", (80, 60), 32000).save(source)

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, output_format="PNG")
    )

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.size == (80, 60)


def test_png_target_size_downscales(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "photo.png"
    make_photo().save(source)
    target = source.stat().st_size // 3

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, target_size=target)
    )

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size <= target
    with Image.open(result.output) as image:
        assert image.size[0] < 900
        assert image.size[1] < 600
    assert "缩放" in result.note


def test_refuses_to_overwrite_original_by_default(
    photo_path: Path,
) -> None:
    config = CompressConfig(
        output_dir=photo_path.parent, suffix="", overwrite=False
    )
    result = process_image(_source(photo_path), config)

    assert result.status == "skipped"
    assert "原始文件相同" in result.note


def test_overwrite_original_when_explicitly_allowed(
    photo_path: Path,
) -> None:
    config = CompressConfig(
        output_dir=photo_path.parent, suffix="", overwrite=True, quality=60
    )
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output == str(photo_path)
    with Image.open(photo_path) as image:
        assert image.format == "JPEG"


def test_external_optimize_is_optional(photo_path: Path, output_dir: Path) -> None:
    config = CompressConfig(output_dir=output_dir, external_optimize=True)
    result = process_image(_source(photo_path), config)

    assert result.status == "success"
    assert result.output is not None


def test_heic_roundtrip_when_plugin_available(
    tmp_path: Path, output_dir: Path
) -> None:
    pytest.importorskip("pillow_heif")
    from image_compressor.utils import ensure_heif_support

    assert ensure_heif_support()
    source = tmp_path / "sample.heic"
    Image.new("RGB", (320, 240), (30, 120, 200)).save(source, format="HEIF")

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, quality=70)
    )

    assert result.status == "success"
    assert result.output is not None
    assert result.output.endswith(".heic")
    with Image.open(result.output) as image:
        assert image.size == (320, 240)


def test_target_size_already_satisfied_keeps_original(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "small.jpg"
    Image.new("RGB", (80, 60), (20, 40, 60)).save(source, quality=85)
    original = source.stat().st_size

    result = process_image(
        _source(source),
        CompressConfig(output_dir=output_dir, target_size=original * 2),
    )

    assert result.status == "success"
    assert result.output is not None
    assert result.output_size == original
    assert "原图已小于目标大小" in result.note


def test_corrupt_file_is_not_copied_when_target_already_satisfied(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "broken.jpg"
    source.write_bytes(b"not an image")

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, target_size=1024 * 1024)
    )

    assert result.status == "failed"
    assert result.output is None
    assert "损坏" in (result.error or "")


def test_output_keeps_original_filename_and_extension(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "photo.JPEG"
    make_photo((320, 240)).save(source, quality=92)

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    assert Path(result.output).name == "photo.JPEG"


def test_output_keeps_tiff_extension(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "scan.tiff"
    make_photo((200, 150)).save(source, format="TIFF")

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    assert Path(result.output).name == "scan.tiff"
