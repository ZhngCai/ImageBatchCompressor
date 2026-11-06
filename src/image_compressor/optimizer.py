"""可选外部优化工具：oxipng / jpegtran，缺失时自动跳过。"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("image_compressor")


def _run(command: list[str], timeout: int = 60) -> bool:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("外部优化工具执行失败：%s", exc)
        return False
    if completed.returncode != 0:
        logger.debug(
            "外部优化工具返回 %s：%s",
            completed.returncode,
            completed.stderr.decode("utf-8", errors="ignore").strip(),
        )
        return False
    return True


def external_optimize(path: Path, target_format: str) -> tuple[bool, str]:
    """无损后处理，只有体积变小才替换；任何失败都不影响主流程。"""
    if target_format == "PNG":
        tool = shutil.which("oxipng")
        if not tool:
            return False, "未找到 oxipng，已跳过外部优化"
        with tempfile.NamedTemporaryFile(
            suffix=".png", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
        try:
            shutil.copy2(path, temp_path)
            if not _run([tool, "-o", "4", "--strip", "none", "--quiet", str(temp_path)]):
                return False, "oxipng 优化失败，已保留 Pillow 结果"
            if temp_path.stat().st_size < path.stat().st_size:
                temp_path.replace(path)
                return True, "已使用 oxipng 进一步优化"
            return False, "oxipng 未减小体积"
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    if target_format == "JPEG":
        tool = shutil.which("jpegtran")
        if not tool:
            return False, "未找到 jpegtran，已跳过外部优化"
        with tempfile.NamedTemporaryFile(
            suffix=".jpg", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
        try:
            if not _run(
                [
                    tool,
                    "-copy",
                    "all",
                    "-optimize",
                    "-progressive",
                    "-outfile",
                    str(temp_path),
                    str(path),
                ]
            ):
                return False, "jpegtran 优化失败，已保留 Pillow 结果"
            if temp_path.stat().st_size < path.stat().st_size:
                temp_path.replace(path)
                return True, "已使用 jpegtran 进一步优化"
            return False, "jpegtran 未减小体积"
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    return False, "当前格式不支持外部优化"
