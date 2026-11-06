"""CLI 参数解析与工具函数测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from image_compressor.cli import build_parser
from image_compressor.utils import (
    ImageCompressorError,
    UnsupportedFormatError,
    human_size,
    normalize_format,
    parse_color,
    parse_ratio,
    parse_size,
    unique_path,
    validate_clean_output_dir,
)


def test_parse_size_units() -> None:
    assert parse_size("500KB") == 500 * 1024
    assert parse_size("1.5MB") == int(1.5 * 1024 * 1024)
    assert parse_size("2GiB") == 2 * 1024**3
    assert parse_size("1024") == 1024


def test_parse_size_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        parse_size("abc")
    with pytest.raises(ValueError):
        parse_size("0")


def test_parse_ratio_formats() -> None:
    assert parse_ratio("80%") == 0.8
    assert parse_ratio("80") == 0.8
    assert parse_ratio("0.8") == 0.8
    assert parse_ratio(50) == 0.5


def test_parse_ratio_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        parse_ratio("0")
    with pytest.raises(ValueError):
        parse_ratio("150%")


def test_parse_color_formats() -> None:
    assert parse_color("white") == (255, 255, 255)
    assert parse_color("#000000") == (0, 0, 0)
    assert parse_color("12,34,56") == (12, 34, 56)


def test_human_size() -> None:
    assert human_size(0) == "0 B"
    assert human_size(1024) == "1 KB"
    assert human_size(120 * 1024 * 1024) == "120 MB"


def test_normalize_format_aliases() -> None:
    assert normalize_format("jpg") == "JPEG"
    assert normalize_format("tif") == "TIFF"
    with pytest.raises(UnsupportedFormatError):
        normalize_format("avif")


def test_unique_path(tmp_path) -> None:
    target = tmp_path / "a.jpg"
    target.write_bytes(b"x")
    candidate = unique_path(target)
    assert candidate.name == "a_1.jpg"


def test_target_size_and_ratio_are_mutually_exclusive() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["-i", "a.jpg", "--target-size", "500KB", "--ratio", "80%"]
        )


def test_cli_defaults() -> None:
    args = build_parser().parse_args(["-i", "a.jpg"])
    assert args.quality == 85
    assert args.output == "output"
    assert args.keep_metadata is True
    assert args.skip_compressed is True
    assert args.keep_structure is True
    assert args.suffix == ""
    assert args.clean_output is True


def test_clean_output_refuses_current_directory() -> None:
    with pytest.raises(ImageCompressorError):
        validate_clean_output_dir(Path.cwd(), [])


def test_clean_output_refuses_input_inside_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    source = output_dir / "photo.jpg"
    source.write_bytes(b"x")

    with pytest.raises(ImageCompressorError):
        validate_clean_output_dir(output_dir, [source])
