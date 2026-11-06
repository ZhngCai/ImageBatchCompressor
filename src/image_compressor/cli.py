"""命令行入口。"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from tqdm import tqdm

from . import __version__
from .config import CompressConfig, MetadataConfig, ResizeConfig
from .reporter import (
    build_summary,
    config_snapshot,
    print_summary,
    write_report,
)
from .scanner import ImageSource, scan_inputs
from .utils import (
    ImageCompressorError,
    UnsupportedFormatError,
    clean_output_directory,
    default_workers,
    ensure_output_dir,
    friendly_error,
    human_size,
    normalize_format,
    parse_color,
    parse_ratio,
    parse_size,
    setup_logging,
    validate_clean_output_dir,
)
from .worker import TaskResult, process_image

logger = logging.getLogger("image_compressor")

EPILOG = """示例：
  image-compress -i ./test.jpg -o ./output --quality 85
  image-compress -i ./images -o ./output --recursive --quality 80
  image-compress -i ./images -o ./output --target-size 500KB
  image-compress -i ./images -o ./output --format webp --quality 80
  image-compress -i ./images -o ./output --max-width 1920 --max-height 1080
  image-compress -i ./images -o ./output --strip-metadata
  image-compress -i ./images -o ./output --workers 8
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-compress",
        description="ImageBatchCompressor：高性能本地批量图片压缩工具",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        nargs="+",
        required=True,
        metavar="PATH",
        help="输入图片、文件夹或通配符，可一次指定多个",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        metavar="DIR",
        help="输出目录（默认：output）",
    )
    parser.add_argument("--quality", type=int, default=85, help="压缩质量 1-100（默认：85）")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--target-size",
        metavar="SIZE",
        help="目标文件大小，例如 500KB、1.5MB",
    )
    target_group.add_argument(
        "--ratio",
        metavar="RATIO",
        help="压缩到原体积的比例，例如 80%% 或 0.8",
    )
    parser.add_argument(
        "--min-quality",
        type=int,
        default=10,
        help="目标大小模式允许的最低质量（默认：10）",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "gif"],
        help="输出格式（默认：保持原格式）",
    )
    parser.add_argument("--width", type=int, help="目标宽度，保持比例")
    parser.add_argument("--height", type=int, help="目标高度，保持比例")
    parser.add_argument("--max-width", type=int, help="最大宽度，保持比例")
    parser.add_argument("--max-height", type=int, help="最大高度，保持比例")
    parser.add_argument("--scale", type=float, metavar="PERCENT", help="按百分比缩放，例如 50")
    metadata_group = parser.add_mutually_exclusive_group()
    metadata_group.add_argument(
        "--strip-metadata",
        dest="keep_metadata",
        action="store_false",
        help="清除 EXIF、ICC 等全部元数据",
    )
    metadata_group.add_argument(
        "--keep-metadata",
        dest="keep_metadata",
        action="store_true",
        help="保留 EXIF、ICC 等元数据（默认）",
    )
    parser.set_defaults(keep_metadata=True)
    parser.add_argument(
        "--strip-gps", action="store_true", help="保留其他元数据，仅清除 GPS 定位信息"
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="递归扫描子文件夹"
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        metavar="GLOB",
        help="通配符筛选，例如 --pattern '*.jpg'，可重复或逗号分隔",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"并发线程数（默认：{default_workers()}）",
    )
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出文件")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="覆盖模式下跳过交互确认"
    )
    parser.add_argument(
        "--rename-conflicts",
        action="store_true",
        help="输出文件已存在时自动追加 _1、_2 后缀",
    )
    parser.add_argument(
        "--suffix",
        default="",
        metavar="TEXT",
        help="输出文件名后缀（默认：无，保持原文件名）",
    )
    parser.add_argument(
        "--clean-output",
        dest="clean_output",
        action="store_true",
        help="压缩前清空输出目录内容（默认开启）",
    )
    parser.add_argument(
        "--no-clean-output",
        dest="clean_output",
        action="store_false",
        help="保留输出目录已有内容",
    )
    parser.set_defaults(clean_output=True)
    parser.add_argument(
        "--skip-compressed",
        dest="skip_compressed",
        action="store_true",
        help="跳过文件名包含压缩标记的图片（默认标记：_compressed）",
    )
    parser.add_argument(
        "--no-skip-compressed",
        dest="skip_compressed",
        action="store_false",
        help="不跳过已压缩文件",
    )
    parser.set_defaults(skip_compressed=True)
    parser.add_argument(
        "--skip-smaller-than",
        default="0",
        metavar="SIZE",
        help="跳过小于指定体积的图片，例如 10KB",
    )
    parser.add_argument(
        "--keep-structure",
        dest="keep_structure",
        action="store_true",
        help="保留输入文件夹的目录结构（默认开启）",
    )
    parser.add_argument(
        "--no-keep-structure",
        dest="keep_structure",
        action="store_false",
        help="所有输出文件放在同一目录",
    )
    parser.set_defaults(keep_structure=True)
    parser.add_argument(
        "--all-frames", action="store_true", help="保留 GIF/WebP 动画的全部帧"
    )
    parser.add_argument(
        "--background",
        default="white",
        metavar="COLOR",
        help="透明图片转 JPEG/BMP 时的背景色（默认：white）",
    )
    parser.add_argument(
        "--external-optimize",
        action="store_true",
        help="使用可选的 oxipng / jpegtran 做无损后处理",
    )
    parser.add_argument(
        "--report", metavar="FILE", help="JSON 报告路径（默认：输出目录/compression_report.json）"
    )
    parser.add_argument(
        "--log-dir", default="logs", metavar="DIR", help="日志目录（默认：logs）"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别（默认：INFO）",
    )
    parser.add_argument("--no-progress", action="store_true", help="关闭进度条")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def _parse_min_size(value: str) -> int:
    text = value.strip().lower()
    if text in {"0", "0b", "0kb", "0mb", "0kib", "0mib"}:
        return 0
    return parse_size(value)


def _build_config(args: argparse.Namespace) -> CompressConfig:
    patterns: list[str] = []
    for value in args.pattern:
        patterns.extend(part.strip() for part in value.split(",") if part.strip())

    output_format = normalize_format(args.output_format) if args.output_format else None
    config = CompressConfig(
        output_dir=Path(args.output).expanduser(),
        quality=args.quality,
        target_size=parse_size(args.target_size) if args.target_size else None,
        ratio=parse_ratio(args.ratio) if args.ratio else None,
        min_quality=args.min_quality,
        output_format=output_format,
        background=parse_color(args.background),
        resize=ResizeConfig(
            width=args.width,
            height=args.height,
            max_width=args.max_width,
            max_height=args.max_height,
            percent=args.scale,
        ),
        metadata=MetadataConfig(keep=args.keep_metadata, strip_gps=args.strip_gps),
        recursive=args.recursive,
        patterns=tuple(patterns),
        workers=args.workers if args.workers is not None else default_workers(),
        overwrite=args.overwrite,
        rename_conflicts=args.rename_conflicts,
        suffix=args.suffix,
        clean_output=args.clean_output,
        skip_compressed=args.skip_compressed,
        min_size=_parse_min_size(args.skip_smaller_than),
        keep_structure=args.keep_structure,
        all_frames=args.all_frames,
        external_optimize=args.external_optimize,
    )
    config.validate()
    return config


def _process_sources(
    sources: list[ImageSource], config: CompressConfig, show_progress: bool
) -> tuple[list[TaskResult], float, bool]:
    """有界任务队列：同时最多保留 workers*4 个待处理任务。"""
    started = time.perf_counter()
    results: list[TaskResult] = []
    cancelled = False
    iterator = iter(sources)
    pending: dict[Future[TaskResult], ImageSource] = {}
    window = max(4, config.workers * 4)
    executor = ThreadPoolExecutor(
        max_workers=config.workers, thread_name_prefix="compress"
    )

    def submit_next() -> None:
        source = next(iterator, None)
        if source is not None:
            pending[executor.submit(process_image, source, config)] = source

    try:
        for _ in range(min(window, len(sources))):
            submit_next()
        with tqdm(
            total=len(sources),
            desc="压缩",
            unit="张",
            disable=not show_progress,
            dynamic_ncols=True,
        ) as progress:
            while pending:
                done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    source = pending.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:  # noqa: BLE001 - worker 已兜底
                        result = TaskResult(
                            source=str(source.path),
                            output=None,
                            status="failed",
                            error=friendly_error(exc),
                        )
                    results.append(result)
                    progress.update(1)
                    submit_next()
    except KeyboardInterrupt:
        cancelled = True
        logger.warning("收到中断信号，正在等待已开始的任务结束...")
        for future in pending:
            future.cancel()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    return results, time.perf_counter() - started, cancelled


def _describe_mode(config: CompressConfig) -> str:
    if config.target_size is not None:
        return f"目标大小 {human_size(config.target_size)}"
    if config.ratio is not None:
        return f"压缩比例 {config.ratio * 100:.0f}%"
    return f"质量 {config.quality}"


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = _build_config(args)
    except (ValueError, UnsupportedFormatError) as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return 2

    try:
        log_path = setup_logging(Path(args.log_dir).expanduser(), args.log_level)
    except OSError as exc:
        print(f"无法初始化日志：{friendly_error(exc)}", file=sys.stderr)
        return 2

    try:
        ensure_output_dir(config.output_dir)
    except ImageCompressorError as exc:
        logger.error("%s", exc)
        return 2

    if config.overwrite and not args.yes:
        if not sys.stdin.isatty():
            logger.error("--overwrite 需要配合 --yes 使用（当前不是交互终端）")
            return 2
        answer = input("确认覆盖已存在的输出文件？[y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("已取消")
            return 0

    scan = scan_inputs(
        args.input,
        recursive=config.recursive,
        patterns=config.patterns,
        exclude_dirs=(config.output_dir,),
    )
    for error in scan.errors:
        logger.error("%s", error)
    if not scan.sources:
        logger.error("没有找到可处理的图片")
        return 1

    if config.clean_output:
        try:
            validate_clean_output_dir(
                config.output_dir, [source.path for source in scan.sources]
            )
            removed_files, removed_dirs = clean_output_directory(
                config.output_dir, preserve_paths=(log_path,)
            )
        except ImageCompressorError as exc:
            logger.error("%s", exc)
            return 2
        if removed_files or removed_dirs:
            logger.info(
                "已清理输出目录：删除 %d 个文件、%d 个目录",
                removed_files,
                removed_dirs,
            )

    print(f"输入图片：{len(scan.sources)} 张")
    print(f"输出目录：{config.output_dir}")
    print(f"压缩模式：{_describe_mode(config)}")
    print(f"输出格式：{config.output_format or '保持原格式'}")
    if config.resize.enabled:
        resize = config.resize
        parts = []
        if resize.width:
            parts.append(f"宽度 {resize.width}")
        if resize.height:
            parts.append(f"高度 {resize.height}")
        if resize.max_width:
            parts.append(f"最大宽度 {resize.max_width}")
        if resize.max_height:
            parts.append(f"最大高度 {resize.max_height}")
        if resize.percent:
            parts.append(f"缩放 {resize.percent:.0f}%")
        print(f"尺寸调整：{', '.join(parts)}")
    print(f"并发线程：{config.workers}")
    print(f"保留元数据：{'是' if config.metadata.keep else '否'}")
    print()

    results, elapsed, cancelled = _process_sources(
        scan.sources, config, show_progress=not args.no_progress
    )
    summary = build_summary(results, elapsed)

    report_path = (
        Path(args.report).expanduser()
        if args.report
        else config.output_dir / "compression_report.json"
    )
    try:
        write_report(
            report_path, results, summary, config_snapshot(config), elapsed
        )
    except OSError as exc:
        logger.error("写入 JSON 报告失败：%s", friendly_error(exc))
        report_path = None  # type: ignore[assignment]

    print_summary(summary, results, report_path)
    if cancelled:
        return 130
    return 1 if summary.failed else 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
