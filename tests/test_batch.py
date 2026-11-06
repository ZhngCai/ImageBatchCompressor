"""批量流程测试：扫描、并发、冲突、跳过、GIF、TIFF、CLI。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_animated_gif, make_multipage_tiff, make_photo
from PIL import Image

from image_compressor.cli import _process_sources, run
from image_compressor.config import CompressConfig
from image_compressor.reporter import build_summary, write_report
from image_compressor.scanner import scan_inputs


def _make_jpegs(directory: Path, count: int) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = directory / f"image_{index:02d}.jpg"
        make_photo((320, 240)).save(path, quality=92)
        paths.append(path)
    return paths


def test_recursive_scan_preserves_directory_structure(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    make_photo((300, 200)).save(input_dir / "a.jpg", quality=90)
    make_photo((300, 200)).save(input_dir / "sub" / "b.png")

    scan = scan_inputs([str(input_dir)], recursive=True)
    assert len(scan.sources) == 2

    output_dir = tmp_path / "output"
    config = CompressConfig(output_dir=output_dir, recursive=True, workers=2)
    results, _, cancelled = _process_sources(scan.sources, config, show_progress=False)

    assert not cancelled
    assert all(result.status == "success" for result in results)
    assert (output_dir / "a.jpg").exists()
    assert (output_dir / "sub" / "b.png").exists()


def test_pattern_filter(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_photo((100, 100)).save(input_dir / "a.jpg", quality=90)
    make_photo((100, 100)).save(input_dir / "b.png")

    scan = scan_inputs([str(input_dir)], patterns=("*.png",))
    assert [source.path.name for source in scan.sources] == ["b.png"]


def test_wildcard_input(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_photo((100, 100)).save(input_dir / "a.jpg", quality=90)
    make_photo((100, 100)).save(input_dir / "b.jpg", quality=90)
    (input_dir / "note.txt").write_text("ignore", encoding="utf-8")

    scan = scan_inputs([str(input_dir / "*.jpg")])
    assert len(scan.sources) == 2


def test_concurrent_processing(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _make_jpegs(input_dir, 12)
    scan = scan_inputs([str(input_dir)])
    output_dir = tmp_path / "output"
    config = CompressConfig(output_dir=output_dir, workers=4)

    results, elapsed, cancelled = _process_sources(
        scan.sources, config, show_progress=False
    )

    assert not cancelled
    assert len(results) == 12
    assert all(result.status == "success" for result in results)
    assert len(list(output_dir.glob("*.jpg"))) == 12
    assert elapsed >= 0


def test_corrupt_image_does_not_stop_batch(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_photo((200, 150)).save(input_dir / "good1.jpg", quality=90)
    (input_dir / "broken.jpg").write_bytes(b"this is not an image")
    make_photo((200, 150)).save(input_dir / "good2.jpg", quality=90)

    scan = scan_inputs([str(input_dir)])
    output_dir = tmp_path / "output"
    config = CompressConfig(output_dir=output_dir, workers=2)
    results, _, _ = _process_sources(scan.sources, config, show_progress=False)

    summary = build_summary(results, 0.1)
    assert summary.total == 3
    assert summary.success == 2
    assert summary.failed == 1

    report_path = output_dir / "report.json"
    write_report(report_path, results, summary, {"mode": "quality"}, 0.1)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    failed = [item for item in payload["results"] if item["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["error"]


def test_filename_conflict_rename(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    make_photo((200, 150)).save(first / "same.jpg", quality=90)
    make_photo((200, 150)).save(second / "same.jpg", quality=90)
    scan = scan_inputs([str(first / "same.jpg"), str(second / "same.jpg")])

    output_dir = tmp_path / "output"
    config = CompressConfig(
        output_dir=output_dir,
        keep_structure=False,
        rename_conflicts=True,
        workers=1,
    )
    results, _, _ = _process_sources(scan.sources, config, show_progress=False)

    assert [result.status for result in results] == ["success", "success"]
    outputs = {result.output for result in results}
    assert len(outputs) == 2
    assert all(Path(path).exists() for path in outputs if path)


def test_existing_output_is_skipped_by_default(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((200, 150)).save(source, quality=90)
    output_dir = tmp_path / "output"
    config = CompressConfig(output_dir=output_dir, workers=1)
    source_item = scan_inputs([str(source)]).sources[0]

    first = _process_sources([source_item], config, show_progress=False)[0][0]
    second = _process_sources([source_item], config, show_progress=False)[0][0]

    assert first.status == "success"
    assert second.status == "skipped"
    assert "已存在" in second.note


def test_skip_already_compressed_file(tmp_path: Path) -> None:
    source = tmp_path / "photo_compressed.jpg"
    make_photo((200, 150)).save(source, quality=90)
    scan = scan_inputs([str(source)])

    results, _, _ = _process_sources(
        scan.sources,
        CompressConfig(output_dir=tmp_path / "output", workers=1),
        show_progress=False,
    )

    assert results[0].status == "skipped"
    assert "压缩后缀" in results[0].note


def test_skip_small_files(tmp_path: Path) -> None:
    source = tmp_path / "tiny.jpg"
    make_photo((40, 30)).save(source, quality=80)
    scan = scan_inputs([str(source)])

    results, _, _ = _process_sources(
        scan.sources,
        CompressConfig(
            output_dir=tmp_path / "output", min_size=10 * 1024 * 1024, workers=1
        ),
        show_progress=False,
    )

    assert results[0].status == "skipped"
    assert "跳过阈值" in results[0].note


def test_gif_animation_first_frame_and_all_frames(tmp_path: Path) -> None:
    source = tmp_path / "anim.gif"
    make_animated_gif(source, frames=3)

    default_dir = tmp_path / "default"
    default_result = _process_sources(
        scan_inputs([str(source)]).sources,
        CompressConfig(output_dir=default_dir, workers=1),
        show_progress=False,
    )[0][0]
    assert default_result.status == "success"
    with Image.open(default_result.output) as image:
        assert image.n_frames == 1

    all_dir = tmp_path / "all"
    all_result = _process_sources(
        scan_inputs([str(source)]).sources,
        CompressConfig(output_dir=all_dir, all_frames=True, workers=1),
        show_progress=False,
    )[0][0]
    assert all_result.status == "success"
    with Image.open(all_result.output) as image:
        assert image.n_frames == 3


def test_multipage_tiff_preserved(tmp_path: Path) -> None:
    source = tmp_path / "pages.tiff"
    make_multipage_tiff(source, pages=2)

    output_dir = tmp_path / "output"
    result = _process_sources(
        scan_inputs([str(source)]).sources,
        CompressConfig(output_dir=output_dir, workers=1),
        show_progress=False,
    )[0][0]

    assert result.status == "success"
    with Image.open(result.output) as image:
        assert image.format == "TIFF"
        assert image.n_frames == 2


def test_multipage_tiff_to_jpeg_first_page_only(tmp_path: Path) -> None:
    source = tmp_path / "pages.tiff"
    make_multipage_tiff(source, pages=2)

    result = _process_sources(
        scan_inputs([str(source)]).sources,
        CompressConfig(output_dir=tmp_path / "output", output_format="JPEG", workers=1),
        show_progress=False,
    )[0][0]

    assert result.status == "success"
    assert "仅处理第一页" in result.note
    with Image.open(result.output) as image:
        assert image.format == "JPEG"


def test_cli_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((400, 300)).save(source, quality=92)
    output_dir = tmp_path / "output"

    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--quality",
            "65",
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "压缩任务完成" in captured.out
    assert (output_dir / "photo.jpg").exists()
    report = output_dir / "compression_report.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["summary"]["success"] == 1


def test_cli_missing_input_returns_error(tmp_path: Path) -> None:
    exit_code = run(
        [
            "-i",
            str(tmp_path / "missing"),
            "-o",
            str(tmp_path / "output"),
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    assert exit_code == 1


def test_cli_overwrite_requires_confirmation_in_non_tty(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((200, 150)).save(source, quality=90)
    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(tmp_path / "output"),
            "--overwrite",
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    assert exit_code == 2


def test_cli_output_path_is_file_returns_error(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((200, 150)).save(source, quality=90)
    output_file = tmp_path / "not_a_directory"
    output_file.write_text("x", encoding="utf-8")

    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(output_file),
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    assert exit_code == 2


def test_concurrent_filename_conflict_rename(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    make_photo((320, 240)).save(first / "same.jpg", quality=90)
    make_photo((320, 240)).save(second / "same.jpg", quality=90)
    scan = scan_inputs([str(first / "same.jpg"), str(second / "same.jpg")])

    output_dir = tmp_path / "output"
    results, _, _ = _process_sources(
        scan.sources,
        CompressConfig(
            output_dir=output_dir,
            keep_structure=False,
            rename_conflicts=True,
            workers=4,
        ),
        show_progress=False,
    )

    assert len(results) == 2
    assert all(result.status == "success" for result in results)
    outputs = {Path(result.output) for result in results if result.output}
    assert len(outputs) == 2
    assert all(path.exists() for path in outputs)


def test_concurrent_filename_conflict_skip(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    make_photo((320, 240)).save(first / "same.jpg", quality=90)
    make_photo((320, 240)).save(second / "same.jpg", quality=90)
    scan = scan_inputs([str(first / "same.jpg"), str(second / "same.jpg")])

    output_dir = tmp_path / "output"
    results, _, _ = _process_sources(
        scan.sources,
        CompressConfig(
            output_dir=output_dir,
            keep_structure=False,
            rename_conflicts=False,
            workers=4,
        ),
        show_progress=False,
    )

    statuses = sorted(result.status for result in results)
    assert statuses == ["skipped", "success"]
    assert len(list(output_dir.glob("same*.jpg"))) == 1


def test_cli_cleans_output_before_compression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((400, 300)).save(source, quality=92)
    output_dir = tmp_path / "output"
    (output_dir / "old_dir").mkdir(parents=True)
    (output_dir / "old_dir" / "note.txt").write_text("old", encoding="utf-8")
    (output_dir / "stale.png").write_bytes(b"old")
    (output_dir / ".gitkeep").write_text("", encoding="utf-8")

    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--quality",
            "70",
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "已清理输出目录" in captured.err
    assert not (output_dir / "stale.png").exists()
    assert not (output_dir / "old_dir").exists()
    assert (output_dir / ".gitkeep").exists()
    assert (output_dir / "photo.jpg").exists()
    assert (output_dir / "compression_report.json").exists()


def test_cli_no_clean_output_preserves_existing_files(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((400, 300)).save(source, quality=92)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    stale = output_dir / "stale.txt"
    stale.write_text("keep me", encoding="utf-8")

    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--no-clean-output",
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    assert exit_code == 0
    assert stale.exists()
    assert (output_dir / "photo.jpg").exists()


def test_cli_refuses_to_clean_output_containing_input(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    source = output_dir / "photo.jpg"
    make_photo((200, 150)).save(source, quality=90)

    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--no-progress",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    assert exit_code == 2
    assert source.exists()


def test_cli_preserves_active_log_inside_output(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    make_photo((400, 300)).save(source, quality=92)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    stale = output_dir / "stale.txt"
    stale.write_text("remove me", encoding="utf-8")

    exit_code = run(
        [
            "-i",
            str(source),
            "-o",
            str(output_dir),
            "--no-progress",
            "--log-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert not stale.exists()
    assert (output_dir / "photo.jpg").exists()
    assert list(output_dir.glob("image-compress_*.log"))
