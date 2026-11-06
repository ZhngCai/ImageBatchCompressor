#!/usr/bin/env python3
"""不同图片格式的压缩效果对比：体积与 PSNR。

用法：
    python examples/compare_formats.py
    python examples/compare_formats.py --source /path/to/photo.heic
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "src"))

from image_compressor.utils import ensure_heif_support

DEFAULT_SOURCE = Path(
    "/System/Library/Desktop Pictures/.wallpapers/Sequoia Sunrise/Sequoia Sunrise.heic"
)


def load_source(path: Path, width: int) -> Image.Image:
    ensure_heif_support()
    with Image.open(path) as image:
        image.load()
        rgb = image.convert("RGB")
    if rgb.width > width:
        height = round(rgb.height * width / rgb.width)
        rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
    return rgb


def synthetic_photo(width: int) -> Image.Image:
    size = (width, round(width * 9 / 16))
    noise = Image.effect_noise(size, 80).convert("L")
    gradient = Image.linear_gradient("L").resize(size)
    return Image.merge(
        "RGB", (noise, gradient, noise.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    )


def encode(image: Image.Image, fmt: str, **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def psnr(reference: Image.Image, candidate: Image.Image) -> float:
    difference = ImageChops.difference(
        reference.convert("RGB"), candidate.convert("RGB")
    )
    statistics = ImageStat.Stat(difference)
    mse = sum(statistics.sum2) / (
        reference.width * reference.height * len(statistics.sum2)
    )
    if mse <= 0:
        return float("inf")
    return 10 * math.log10((255**2) / mse)


def measure(name: str, data: bytes, reference: Image.Image) -> dict[str, object]:
    with Image.open(io.BytesIO(data)) as decoded:
        decoded.load()
        value = psnr(reference, decoded)
        mode = decoded.mode
        size = decoded.size
    return {
        "format": name,
        "bytes": len(data),
        "kb": round(len(data) / 1024, 1),
        "psnr": None if math.isinf(value) else round(value, 2),
        "mode": mode,
        "size": size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    if args.source.exists():
        reference = load_source(args.source, args.width)
        source_label = str(args.source)
    else:
        print(f"未找到 {args.source}，改用合成测试图（可用 --source 指定真实图片）")
        reference = synthetic_photo(args.width)
        source_label = "synthetic"

    baseline = encode(reference, "JPEG", quality=95, optimize=True, progressive=True)
    baseline_size = len(baseline)
    print(f"参考图：{source_label} -> {reference.width}x{reference.height}")
    print(f"JPEG q95 基准：{baseline_size / 1024:.1f} KB\n")

    rows = [
        measure("JPEG q85", encode(reference, "JPEG", quality=85, optimize=True), reference),
        measure(
            "WebP q85",
            encode(reference, "WEBP", quality=85, method=6),
            reference,
        ),
        measure(
            "PNG 无损",
            encode(reference, "PNG", optimize=True, compress_level=9),
            reference,
        ),
        measure("BMP", encode(reference, "BMP"), reference),
        measure(
            "TIFF deflate",
            encode(reference, "TIFF", compression="tiff_deflate"),
            reference,
        ),
        measure(
            "GIF 256 色",
            encode(
                reference.convert("P", palette=Image.Palette.ADAPTIVE, colors=256),
                "GIF",
                optimize=True,
            ),
            reference,
        ),
    ]

    print("| 格式 | 体积 | 相对 JPEG q95 | PSNR | 说明 |")
    print("| --- | ---: | ---: | ---: | --- |")
    for row in rows:
        ratio = row["bytes"] / baseline_size * 100
        psnr_text = "∞（无损）" if row["psnr"] is None else f"{row['psnr']} dB"
        note = "有损" if row["format"] in ("JPEG q85", "WebP q85", "GIF 256 色") else "无损"
        print(
            f"| {row['format']} | {row['kb']} KB | {ratio:.1f}% | {psnr_text} | {note} |"
        )

    payload = {
        "source": source_label,
        "width": reference.width,
        "height": reference.height,
        "baseline_jpeg_q95_bytes": baseline_size,
        "rows": rows,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n结果已写入：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
