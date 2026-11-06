#!/usr/bin/env python3
"""性能基准：批量吞吐、4K 图片、接近 100MB 的大文件、目标体积搜索。

用法：
    python examples/benchmark.py
    python examples/benchmark.py --source /path/to/photo.heic --count 1000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from image_compressor.utils import ensure_heif_support

DEFAULT_SOURCE = Path(
    "/System/Library/Desktop Pictures/.wallpapers/Sequoia Sunrise/Sequoia Sunrise.heic"
)


def load_source(path: Path) -> Image.Image:
    ensure_heif_support()
    with Image.open(path) as image:
        image.load()
        return image.convert("RGB")


def synthetic_photo(size: tuple[int, int] = (3840, 2160)) -> Image.Image:
    """没有真实素材时生成可用于基准的合成照片。"""
    noise = Image.effect_noise(size, 80).convert("L")
    gradient = Image.linear_gradient("L").resize(size)
    return Image.merge(
        "RGB", (noise, gradient, noise.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    )


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _command(args: list[str]) -> list[str]:
    return [sys.executable, "-m", "image_compressor", *args]


def run_cli(args: list[str]) -> tuple[float, dict[str, object], float | None]:
    elapsed, peak_mb = peak_rss_mb(_command(args), _environment())
    report_path = Path(args[args.index("-o") + 1]) / "compression_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return elapsed, report, peak_mb


def batch_benchmark(
    base: Image.Image, workdir: Path, count: int, workers: int
) -> dict[str, object]:
    input_dir = workdir / "batch_input"
    output_dir = workdir / "batch_output"
    if input_dir.exists():
        shutil.rmtree(input_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    input_dir.mkdir(parents=True)

    image = base.resize((1920, 1080), Image.Resampling.LANCZOS)
    for index in range(count):
        image.save(input_dir / f"image_{index:04d}.jpg", quality=90)

    elapsed, report, peak_mb = run_cli(
        [
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--quality",
            "80",
            "--workers",
            str(workers),
            "--no-progress",
            "--log-dir",
            str(workdir / "logs"),
        ]
    )
    summary = report["summary"]
    return {
        "images": count,
        "workers": workers,
        "wall_seconds": round(elapsed, 2),
        "images_per_second": round(count / elapsed, 2),
        "peak_rss_mb": None if peak_mb is None else round(peak_mb, 1),
        "summary": summary,
    }


def large_file_benchmark(base: Image.Image, workdir: Path) -> dict[str, object]:
    source = workdir / "large_100mb.bmp"
    output_dir = workdir / "large_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    large = base.resize((6000, 5500), Image.Resampling.LANCZOS)
    large.save(source, format="BMP")

    elapsed, report, peak_mb = run_cli(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--quality",
            "85",
            "--format",
            "jpeg",
            "--no-progress",
            "--log-dir",
            str(workdir / "logs"),
        ]
    )
    result = report["results"][0]
    return {
        "input_size_mb": round(source.stat().st_size / 1024 / 1024, 2),
        "output_size_mb": round(result["output_size"] / 1024 / 1024, 2),
        "wall_seconds": round(elapsed, 2),
        "peak_rss_mb": None if peak_mb is None else round(peak_mb, 1),
        "result": result,
    }


def target_benchmark(base: Image.Image, workdir: Path) -> dict[str, object]:
    source = workdir / "target_4k.jpg"
    output_dir = workdir / "target_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    base.resize((3840, 2160), Image.Resampling.LANCZOS).save(source, quality=95)
    original_size = source.stat().st_size

    elapsed, report, _ = run_cli(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--target-size",
            "500KB",
            "--no-progress",
            "--log-dir",
            str(workdir / "logs"),
        ]
    )
    result = report["results"][0]
    return {
        "input_size_kb": round(original_size / 1024, 1),
        "target_kb": 500,
        "output_size_kb": round(result["output_size"] / 1024, 1),
        "quality": result["quality"],
        "image_seconds": round(result["duration"], 3),
        "wall_seconds": round(elapsed, 2),
        "note": result["note"],
    }


def peak_rss_mb(command: list[str], env: dict[str, str]) -> tuple[float, float | None]:
    """在 macOS/Linux 上通过 /usr/bin/time 采集峰值内存。"""
    time_binary = Path("/usr/bin/time")
    if not time_binary.exists():
        started = time.perf_counter()
        subprocess.run(command, cwd=ROOT, env=env, check=False, capture_output=True)
        return time.perf_counter() - started, None

    time_flag = "-l" if sys.platform == "darwin" else "-v"
    started = time.perf_counter()
    completed = subprocess.run(
        [str(time_binary), time_flag, *command],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    match = re.search(r"(\d+)\s+maximum resident set size", completed.stderr)
    if not match:
        match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", completed.stderr)
    if not match:
        return elapsed, None
    value = int(match.group(1))
    if sys.platform == "darwin":
        return elapsed, value / 1024 / 1024
    return elapsed, value / 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--workdir", type=Path, default=ROOT / "examples" / ".benchmark")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-large", action="store_true")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    args.workdir.mkdir(parents=True, exist_ok=True)
    if args.source.exists():
        base = load_source(args.source)
        source_label = str(args.source)
    else:
        print(f"未找到 {args.source}，改用合成测试图（可用 --source 指定真实图片）")
        base = synthetic_photo()
        source_label = "synthetic"

    print(f"基准源图：{source_label}（{base.width}x{base.height}）")
    results: dict[str, object] = {"source": source_label}

    print(f"\n[1/3] 批量吞吐：{args.count} 张 1920x1080 JPEG，{args.workers} 线程")
    batch = batch_benchmark(base, args.workdir, args.count, args.workers)
    results["batch"] = batch
    print(json.dumps(batch, ensure_ascii=False, indent=2))

    print("\n[2/3] 目标体积：4K JPEG -> 500KB")
    target = target_benchmark(base, args.workdir)
    results["target_size"] = target
    print(json.dumps(target, ensure_ascii=False, indent=2))

    if not args.skip_large:
        print("\n[3/3] 大文件：约 100MB BMP -> JPEG")
        large = large_file_benchmark(base, args.workdir)
        results["large_file"] = large
        print(json.dumps(large, ensure_ascii=False, indent=2))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n结果已写入：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
