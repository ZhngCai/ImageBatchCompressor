"""输入扫描：文件、文件夹、通配符与递归遍历。"""

from __future__ import annotations

import fnmatch
import glob
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .utils import is_supported_image

logger = logging.getLogger("image_compressor")


@dataclass(frozen=True)
class ImageSource:
    path: Path
    root: Path
    from_directory: bool = False


@dataclass
class ScanResult:
    sources: list[ImageSource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _matches_patterns(path: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return True
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return any(
        fnmatch.fnmatch(path.name, pattern)
        or fnmatch.fnmatch(relative, pattern)
        or fnmatch.fnmatch(path.as_posix(), pattern)
        for pattern in patterns
    )


def _iter_directory(
    root: Path, recursive: bool, exclude_dirs: set[Path]
) -> list[Path]:
    files: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if (current / name).resolve() not in exclude_dirs
            )
            for name in sorted(filenames):
                candidate = current / name
                if candidate.is_file() and is_supported_image(candidate):
                    files.append(candidate)
    else:
        try:
            entries = sorted(root.iterdir())
        except PermissionError as exc:
            raise PermissionError(f"无法读取文件夹：{root}") from exc
        for entry in entries:
            if entry.is_file() and is_supported_image(entry):
                files.append(entry)
    return files


def scan_inputs(
    inputs: list[str] | tuple[str, ...],
    *,
    recursive: bool = False,
    patterns: tuple[str, ...] = (),
    exclude_dirs: tuple[Path, ...] = (),
) -> ScanResult:
    """扫描所有输入；单个路径失败只记录错误，不中断其他输入。"""
    result = ScanResult()
    seen: set[Path] = set()
    exclude = {path.resolve() for path in exclude_dirs}

    def add_source(path: Path, root: Path, from_directory: bool) -> None:
        try:
            key = path.resolve()
        except OSError:
            key = path.absolute()
        if key in seen:
            return
        if not _matches_patterns(path, root, patterns):
            return
        seen.add(key)
        result.sources.append(ImageSource(path=path, root=root, from_directory=from_directory))

    def collect(raw_path: Path) -> None:
        try:
            path = raw_path.expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve()
        except OSError as exc:
            result.errors.append(f"无法解析路径 {raw_path}：{exc}")
            return

        if path.is_dir():
            if path in exclude:
                return
            try:
                files = _iter_directory(path, recursive, exclude)
            except PermissionError as exc:
                result.errors.append(str(exc))
                return
            if not files:
                logger.warning("文件夹中没有匹配的图片：%s", path)
            for file_path in files:
                add_source(file_path, path, True)
            return

        if path.is_file():
            if not is_supported_image(path):
                result.errors.append(
                    f"不支持的图片格式：{path}（支持：{', '.join(sorted(ext.lstrip('.') for ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.heic', '.heif')))}）"
                )
                return
            add_source(path, path.parent, False)
            return

        result.errors.append(f"路径不存在：{raw_path}")

    for raw in inputs:
        text = str(raw).strip().strip('"').strip("'")
        if not text:
            continue
        expanded = os.path.expanduser(text)
        if glob.has_magic(expanded):
            matches = [Path(item) for item in glob.glob(expanded, recursive=recursive)]
            if not matches:
                result.errors.append(f"通配符未匹配到任何文件：{text}")
                continue
            for match in sorted(matches, key=lambda item: str(item).lower()):
                collect(match)
        else:
            collect(Path(expanded))

    result.sources.sort(key=lambda source: str(source.path).lower())
    return result
