"""结果统计与控制台 / JSON 报告。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import CompressConfig
from .utils import atomic_write, human_size
from .worker import TaskResult


@dataclass(frozen=True)
class Summary:
    total: int
    success: int
    failed: int
    skipped: int
    original_size: int
    output_size: int
    saved_size: int
    ratio: float
    avg_duration: float
    elapsed: float


def build_summary(results: list[TaskResult], elapsed: float) -> Summary:
    successes = [result for result in results if result.status == "success"]
    original_size = sum(result.original_size for result in successes)
    output_size = sum(result.output_size for result in successes)
    saved_size = max(0, original_size - output_size)
    ratio = saved_size / original_size * 100 if original_size else 0.0
    average = (
        sum(result.duration for result in successes) / len(successes)
        if successes
        else 0.0
    )
    return Summary(
        total=len(results),
        success=len(successes),
        failed=sum(1 for result in results if result.status == "failed"),
        skipped=sum(1 for result in results if result.status == "skipped"),
        original_size=original_size,
        output_size=output_size,
        saved_size=saved_size,
        ratio=ratio,
        avg_duration=average,
        elapsed=elapsed,
    )


def print_summary(
    summary: Summary, results: list[TaskResult], report_path: Path | None = None
) -> None:
    print()
    print("压缩任务完成！")
    print()
    print(f"总计：{summary.total} 张")
    print(f"成功：{summary.success} 张")
    print(f"失败：{summary.failed} 张")
    print(f"跳过：{summary.skipped} 张")
    print()
    print(f"原始大小：{human_size(summary.original_size)}")
    print(f"压缩后：{human_size(summary.output_size)}")
    print(f"节省空间：{human_size(summary.saved_size)}")
    print(f"总体压缩率：{summary.ratio:.2f}%")
    print()
    print(f"平均单张耗时：{summary.avg_duration:.3f} 秒")
    print(f"总处理时间：{summary.elapsed:.2f} 秒")
    if report_path:
        print(f"报告文件：{report_path}")

    failures = [result for result in results if result.status == "failed"]
    if failures:
        print()
        print("失败明细：")
        for result in failures[:10]:
            print(f"  - {result.source}：{result.error or '未知错误'}")
        if len(failures) > 10:
            print(f"  ... 其余 {len(failures) - 10} 张失败图片见日志")


def config_snapshot(config: CompressConfig) -> dict[str, object]:
    return {
        "output_dir": str(config.output_dir),
        "quality": config.quality,
        "target_size": config.target_size,
        "ratio": config.ratio,
        "mode": config.mode,
        "min_quality": config.min_quality,
        "output_format": config.output_format,
        "background": list(config.background),
        "resize": asdict(config.resize),
        "metadata": asdict(config.metadata),
        "recursive": config.recursive,
        "patterns": list(config.patterns),
        "workers": config.workers,
        "overwrite": config.overwrite,
        "rename_conflicts": config.rename_conflicts,
        "suffix": config.suffix,
        "clean_output": config.clean_output,
        "skip_compressed": config.skip_compressed,
        "min_size": config.min_size,
        "keep_structure": config.keep_structure,
        "all_frames": config.all_frames,
        "external_optimize": config.external_optimize,
    }


def write_report(
    path: Path,
    results: list[TaskResult],
    summary: Summary,
    config: dict[str, object],
    elapsed: float,
) -> None:
    records = []
    for result in results:
        record = asdict(result)
        record["saved_size"] = result.saved_size
        record["ratio"] = round(result.ratio, 2)
        records.append(record)

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 3),
        "summary": asdict(summary),
        "config": config,
        "results": records,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write(path, data)
