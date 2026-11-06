"""运行配置与参数校验。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .utils import default_workers


@dataclass(frozen=True)
class ResizeConfig:
    width: int | None = None
    height: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    percent: float | None = None
    resample: int = Image.Resampling.LANCZOS

    @property
    def enabled(self) -> bool:
        return any(
            value is not None
            for value in (
                self.width,
                self.height,
                self.max_width,
                self.max_height,
                self.percent,
            )
        )


@dataclass(frozen=True)
class MetadataConfig:
    keep: bool = True
    strip_gps: bool = False


@dataclass(frozen=True)
class CompressConfig:
    output_dir: Path = Path("output")
    quality: int = 85
    target_size: int | None = None
    ratio: float | None = None
    min_quality: int = 10
    output_format: str | None = None
    background: tuple[int, int, int] = (255, 255, 255)
    resize: ResizeConfig = field(default_factory=ResizeConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    recursive: bool = False
    patterns: tuple[str, ...] = ()
    workers: int = field(default_factory=default_workers)
    overwrite: bool = False
    rename_conflicts: bool = False
    suffix: str = ""
    clean_output: bool = True
    skip_compressed: bool = True
    min_size: int = 0
    keep_structure: bool = True
    all_frames: bool = False
    external_optimize: bool = False

    @property
    def mode(self) -> str:
        if self.target_size is not None:
            return "target"
        if self.ratio is not None:
            return "ratio"
        return "quality"

    def validate(self) -> None:
        if not 1 <= self.quality <= 100:
            raise ValueError("质量必须位于 1-100")
        if not 1 <= self.min_quality <= 100:
            raise ValueError("最低质量必须位于 1-100")
        if self.target_size is not None and self.target_size <= 0:
            raise ValueError("目标大小必须大于 0")
        if self.ratio is not None and not 0 < self.ratio <= 1:
            raise ValueError("压缩比例必须位于 (0, 1] 区间")
        if self.target_size is not None and self.ratio is not None:
            raise ValueError("目标大小与压缩比例不能同时使用")
        if self.workers < 1:
            raise ValueError("并发数必须大于等于 1")
        if self.min_size < 0:
            raise ValueError("最小跳过体积不能为负数")
        if self.overwrite and self.rename_conflicts:
            raise ValueError("覆盖模式与自动重命名不能同时使用")
        for name, value in (
            ("宽度", self.resize.width),
            ("高度", self.resize.height),
            ("最大宽度", self.resize.max_width),
            ("最大高度", self.resize.max_height),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name}必须大于 0")
        if self.resize.percent is not None and self.resize.percent <= 0:
            raise ValueError("缩放百分比必须大于 0")
        if self.suffix and any(char in self.suffix for char in '/\\:*?"<>|'):
            raise ValueError("文件名后缀不能包含路径或非法字符")
