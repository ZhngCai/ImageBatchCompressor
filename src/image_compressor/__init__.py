"""ImageBatchCompressor：本地批量图片压缩工具。"""

from __future__ import annotations

__version__ = "1.0.0"

from .config import CompressConfig, MetadataConfig, ResizeConfig
from .scanner import ImageSource, scan_inputs
from .worker import TaskResult, TaskStatus, process_image

__all__ = [
    "CompressConfig",
    "ImageSource",
    "MetadataConfig",
    "ResizeConfig",
    "TaskResult",
    "TaskStatus",
    "__version__",
    "process_image",
    "scan_inputs",
]
