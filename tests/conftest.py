"""测试公共夹具与图片生成工具。"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PIL import Image, ImageCms, ImageDraw


def make_photo(size: tuple[int, int] = (900, 600)) -> Image.Image:
    noise = Image.effect_noise(size, 90).convert("L")
    gradient = Image.linear_gradient("L").resize(size)
    flipped = noise.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return Image.merge("RGB", (noise, gradient, flipped))


def make_transparent(size: tuple[int, int] = (400, 300)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4],
        fill=(255, 0, 0, 255),
    )
    return image


def make_animated_gif(path: Path, frames: int = 3) -> None:
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    images = [
        Image.new("RGB", (120, 80), colors[index % len(colors)])
        for index in range(frames)
    ]
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
    )


def make_multipage_tiff(path: Path, pages: int = 2) -> None:
    images = [
        Image.new("RGB", (160, 120), (30 + index * 60, 80, 160))
        for index in range(pages)
    ]
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        compression="tiff_deflate",
    )


def srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@pytest.fixture
def photo_path(tmp_path: Path) -> Path:
    path = tmp_path / "photo.jpg"
    make_photo().save(path, quality=95)
    return path


@pytest.fixture
def transparent_png(tmp_path: Path) -> Path:
    path = tmp_path / "transparent.png"
    make_transparent().save(path)
    return path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    path = tmp_path / "output"
    path.mkdir()
    return path


@pytest.fixture
def random_seed() -> int:
    return random.randint(0, 10_000)
