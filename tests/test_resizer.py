"""尺寸计算与缩放测试。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from image_compressor.config import CompressConfig, ResizeConfig
from image_compressor.resizer import calculate_size, resize_image
from image_compressor.scanner import ImageSource
from image_compressor.worker import process_image


def test_max_dimensions_keep_aspect_ratio() -> None:
    result = calculate_size((1200, 800), ResizeConfig(max_width=600, max_height=600))
    assert (result.width, result.height) == (600, 400)
    assert result.changed


def test_width_only_keeps_aspect_ratio() -> None:
    result = calculate_size((1000, 500), ResizeConfig(width=400))
    assert (result.width, result.height) == (400, 200)


def test_height_only_keeps_aspect_ratio() -> None:
    result = calculate_size((1000, 500), ResizeConfig(height=100))
    assert (result.width, result.height) == (200, 100)


def test_percent_scale() -> None:
    result = calculate_size((800, 600), ResizeConfig(percent=25))
    assert (result.width, result.height) == (200, 150)


def test_never_upscale() -> None:
    result = calculate_size((300, 200), ResizeConfig(max_width=1000, max_height=1000))
    assert (result.width, result.height) == (300, 200)
    assert not result.changed


def test_resize_image_uses_lanczos() -> None:
    image = Image.new("RGB", (500, 300), "red")
    resized = resize_image(image, ResizeConfig(max_width=250))
    assert resized.size == (250, 150)


def test_process_image_resize(photo_path: Path, output_dir: Path) -> None:
    config = CompressConfig(
        output_dir=output_dir,
        resize=ResizeConfig(max_width=300, max_height=300),
    )
    result = process_image(
        ImageSource(path=photo_path, root=photo_path.parent), config
    )

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.size == (300, 200)


def test_process_image_does_not_upscale(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "small.jpg"
    Image.new("RGB", (120, 80), (40, 80, 120)).save(source, quality=90)

    result = process_image(
        ImageSource(path=source, root=source.parent),
        CompressConfig(
            output_dir=output_dir,
            resize=ResizeConfig(max_width=800, max_height=800),
        ),
    )

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.size == (120, 80)
