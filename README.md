# ImageBatchCompressor

高性能、轻量化的本地批量图片压缩工具。纯 Python CLI，无前端、无后端、无数据库，支持 Windows / macOS / Linux。

- 批量压缩、递归扫描、并发处理
- 质量压缩、目标文件大小、压缩比例三种模式
- JPEG / PNG / WebP / BMP / TIFF / GIF，HEIC / HEIF 可选
- 尺寸调整、格式转换、元数据保留与清理
- 保留目录结构、跳过已压缩文件、冲突处理、原图保护
- 实时进度条、控制台统计、JSON 任务报告
- 72 个 pytest 测试，覆盖 15 类核心场景

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [CLI 参数](#cli-参数)
- [压缩模式](#压缩模式)
- [图片质量保护](#图片质量保护)
- [输出与报告](#输出与报告)
- [性能](#性能)
- [测试](#测试)
- [打包](#打包)
- [项目结构](#项目结构)
- [常见问题](#常见问题)

## 安装

要求 Python 3.11+。

```bash
cd 压缩文件
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

安装后可直接使用 `image-compress` 命令；也可以用 `python -m image_compressor`。

### 可选依赖

HEIC / HEIF 支持：

```bash
pip install -e ".[heif]"
# 或
pip install pillow-heif
```

外部无损优化工具（可选，不安装不影响基础功能）：

```bash
# macOS
brew install oxipng jpeg-turbo

# Ubuntu / Debian
sudo apt install oxipng libjpeg-turbo-progs
```

使用 `--external-optimize` 时，程序会自动检测 `oxipng`（PNG）和 `jpegtran`（JPEG）；工具缺失或执行失败会跳过，不影响主流程。

## 快速开始

```bash
# 1. 压缩单张图片
image-compress -i ./test.jpg -o ./output --quality 85

# 2. 批量压缩整个文件夹
image-compress -i ./images -o ./output --quality 85

# 3. 递归压缩
image-compress -i ./images -o ./output --recursive --quality 80

# 4. 压缩到指定大小
image-compress -i ./images -o ./output --target-size 500KB

# 5. 转换成 WebP
image-compress -i ./images -o ./output --format webp --quality 80

# 6. 调整图片尺寸
image-compress -i ./images -o ./output --max-width 1920 --max-height 1080

# 7. 删除 EXIF 元数据
image-compress -i ./images -o ./output --strip-metadata

# 8. 设置并发数量
image-compress -i ./images -o ./output --workers 8

# 9. 显示帮助
image-compress --help
```

支持一次传入多个文件、文件夹或通配符，也支持把文件拖入终端后得到的带引号路径：

```bash
image-compress -i ./a.jpg ./b.png ./photos "*.webp" -o ./output
```

默认输出到 `output/`，默认质量 85，默认不覆盖原图，并且**保持原文件名和原格式**。未转换格式时，`.jpeg`、`.tif`、`.heif` 等原始扩展名不会被改写。需要给输出文件加后缀时使用 `--suffix`。

每次运行默认会**先清空输出目录内容**，避免旧结果和新结果混在一起；保留 `.gitkeep` 和日志文件/日志目录。需要保留旧输出时使用 `--no-clean-output`。

## CLI 参数

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-i, --input PATH [PATH ...]` | 输入图片、文件夹或通配符，可多个 | 必填 |
| `-o, --output DIR` | 输出目录 | `output` |
| `--quality N` | 压缩质量 1–100 | `85` |
| `--target-size SIZE` | 目标文件大小，如 `500KB`、`1.5MB` | 无 |
| `--ratio RATIO` | 压缩到原体积比例，如 `80%`、`0.8` | 无 |
| `--min-quality N` | 目标大小模式允许的最低质量 | `10` |
| `--format FMT` | 输出格式：`jpg/jpeg/png/webp/bmp/tif/tiff/gif` | 保持原格式 |
| `--width N` | 目标宽度，保持比例 | 无 |
| `--height N` | 目标高度，保持比例 | 无 |
| `--max-width N` | 最大宽度，保持比例 | 无 |
| `--max-height N` | 最大高度，保持比例 | 无 |
| `--scale PERCENT` | 按百分比缩放，如 `50` | 无 |
| `--strip-metadata` | 清除 EXIF、ICC 等全部元数据 | 保留 |
| `--keep-metadata` | 保留元数据 | 默认 |
| `--strip-gps` | 仅清除 GPS 定位信息，保留其他 EXIF | 关闭 |
| `-r, --recursive` | 递归扫描子文件夹 | 关闭 |
| `--pattern GLOB` | 通配符筛选，可重复或逗号分隔 | 全部支持格式 |
| `--workers N` | 并发线程数 | `min(8, CPU 核心数)` |
| `--overwrite` | 覆盖已存在的输出文件 | 关闭 |
| `-y, --yes` | 覆盖模式下跳过交互确认 | 关闭 |
| `--rename-conflicts` | 输出文件已存在时自动追加 `_1`、`_2` | 关闭 |
| `--suffix TEXT` | 输出文件名后缀 | 无（保持原文件名） |
| `--clean-output` | 压缩前清空输出目录内容 | 开启 |
| `--no-clean-output` | 保留输出目录已有内容 | — |
| `--skip-compressed` | 跳过文件名包含压缩标记的图片（默认标记 `_compressed`） | 开启 |
| `--no-skip-compressed` | 不跳过已压缩文件 | — |
| `--skip-smaller-than SIZE` | 跳过小于指定体积的图片，如 `10KB` | `0` |
| `--keep-structure` | 保留输入文件夹目录结构 | 开启 |
| `--no-keep-structure` | 所有输出放在同一目录 | — |
| `--all-frames` | 保留 GIF / WebP 动画全部帧 | 关闭 |
| `--background COLOR` | 透明图片转 JPEG/BMP 的背景色 | `white` |
| `--external-optimize` | 使用 oxipng / jpegtran 做无损后处理 | 关闭 |
| `--report FILE` | JSON 报告路径 | 输出目录/`compression_report.json` |
| `--log-dir DIR` | 日志目录 | `logs` |
| `--log-level LEVEL` | `DEBUG/INFO/WARNING/ERROR` | `INFO` |
| `--no-progress` | 关闭进度条 | 关闭 |
| `--version` | 显示版本 | — |

## 压缩模式

### 模式 A：指定质量

```bash
image-compress -i ./images -o ./output --quality 80
```

- JPEG / WebP 使用 1–100 质量。
- PNG 使用无损优化和 `compress_level=9`，不会因为质量参数产生有损色块。
- 默认质量 85。
- JPEG 质量 ≥90 使用 4:4:4 色度采样，≥80 使用 4:2:2，降低文字和边缘的色块。

### 模式 B：目标文件大小

```bash
image-compress -i ./images -o ./output --target-size 500KB
image-compress -i ./images -o ./output --target-size 200KB --min-quality 20
```

- 有损格式（JPEG / WebP / HEIF）：先尝试较高质量，再用二分搜索寻找满足目标体积的最高质量。
- 无损格式（PNG / BMP / TIFF / GIF）：质量参数不改变体积，改为二分搜索满足目标体积的最大尺寸。
- 目标大小属于尽力优化；如果最低质量仍无法达到，会输出最接近的结果，并在报告的 `note` 中说明。
- `--min-quality` 防止为了追求体积而无限降低质量，默认 10。

### 模式 C：指定压缩比例

```bash
image-compress -i ./images -o ./output --ratio 80%
image-compress -i ./images -o ./output --ratio 0.5
```

按原文件体积比例计算目标大小，复用目标大小搜索算法。`80%`、`80`、`0.8` 等价。

## 图片质量保护

- **EXIF 方向**：读取时按方向旋转像素，并移除方向标记，避免二次旋转。
- **透明通道**：PNG 透明通道在 PNG/WebP/TIFF/GIF 输出中保留；转 JPEG/BMP 时按 `--background` 合成背景，默认白色，不会出现黑底。
- **ICC 色彩**：默认保留 ICC 配置；CMYK 图片优先使用嵌入 ICC 转换为 sRGB，缺失时使用 Pillow 普通转换。
- **EXIF / GPS**：默认保留 EXIF；`--strip-gps` 仅清除 GPS；`--strip-metadata` 清除全部元数据。
- **GIF 动画**：默认仅处理第一帧；`--all-frames` 保留全部帧和帧间隔。
- **TIFF 多页**：输出 TIFF 时默认保留全部页面；转换为 JPEG/PNG 等单页格式时处理第一页并在报告中说明。
- **特殊模式**：16 位灰度、调色板、CMYK、带透明通道的图片会转换为目标格式可安全保存的模式。
- **避免越压越大**：同格式、无缩放且压缩结果未变小时，保留原始文件数据；格式转换或缩放场景除外。

## 输出与报告

输出目录默认保留输入文件夹结构，并保持原文件名和原扩展名：

> 需要区分原图与压缩结果时，可加 `--suffix _compressed`，输出会变成 `a_compressed.jpg`。

每次压缩开始前会清空输出目录内容（保留 `.gitkeep` 与日志文件/日志目录）。为避免误删，程序会拒绝清理以下目录：

- 文件系统根目录、用户主目录、系统临时目录
- 当前工作目录或其上级目录
- 包含输入文件的目录

如不希望清理，使用 `--no-clean-output`。

```text
images/
├── a.jpg
└── sub/
    └── b.png

output/
├── a.jpg
└── sub/
    └── b.png
```

每次任务完成后输出统计：

```text
压缩任务完成！

总计：100 张
成功：98 张
失败：2 张
跳过：0 张

原始大小：120 MB
压缩后：38 MB
节省空间：82 MB
总体压缩率：68.33%

平均单张耗时：0.12 秒
总处理时间：12.34 秒
报告文件：output/compression_report.json
```

JSON 报告包含汇总、完整配置和每张图片的原始大小、输出大小、耗时、质量、缩放比例、备注与错误信息。示例：

```json
{
  "generated_at": "2026-11-06T18:00:00+08:00",
  "elapsed_seconds": 12.34,
  "summary": {
    "total": 100,
    "success": 98,
    "failed": 2,
    "skipped": 0,
    "original_size": 125829120,
    "output_size": 39845888,
    "saved_size": 85983232,
    "ratio": 68.33,
    "avg_duration": 0.12,
    "elapsed": 12.34
  },
  "config": { "...": "..." },
  "results": [
    {
      "source": "/path/a.jpg",
      "output": "/path/output/a.jpg",
      "status": "success",
      "original_size": 2048000,
      "output_size": 512000,
      "duration": 0.08,
      "format": "JPEG",
      "quality": 82,
      "scale": 1.0,
      "note": "",
      "error": null
    }
  ]
}
```

日志默认写入 `logs/image-compress_YYYYmmdd_HHMMSS.log`，包含线程、级别和完整错误堆栈。

## 性能

本机实测（Apple Silicon 14 核、24 GB、Python 3.12、Pillow 13）：

| 场景 | 结果 |
| --- | ---: |
| 10000 张 160×120 小图 | 5.08 秒，峰值约 76.6 MiB，0 失败 |
| 200 张 1920×1080 JPEG | 6.40 秒，31.25 张/秒，峰值 456.1 MB |
| 1000 张 1920×1080 JPEG | 32.17 秒，31.08 张/秒，峰值 500.2 MB |
| 4K JPEG → 500 KB | 496.5 KB，自动质量 35，0.524 秒 |
| 94.41 MB BMP → JPEG | 3.54 MB，0.77 秒，峰值 402.5 MB |

完整数据、测试方法和结论见 [docs/performance.md](docs/performance.md)。

不同格式的体积与 PSNR 对比见 [docs/format-comparison.md](docs/format-comparison.md)。本机实测 1920×1080 真实照片：

| 格式 | 体积 | 相对 JPEG q95 | PSNR |
| --- | ---: | ---: | ---: |
| JPEG q85 | 450.2 KB | 59.8% | 36.23 dB |
| WebP q85 | 348.8 KB | 46.4% | 36.87 dB |
| PNG 无损 | 3269.8 KB | 434.6% | ∞ |
| BMP | 6075.1 KB | 807.4% | ∞ |
| TIFF deflate | 4845.5 KB | 644.0% | ∞ |
| GIF 256 色 | 1827.3 KB | 242.8% | 35.22 dB |

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

当前结果：**72 passed**。

| 需求 | 测试文件 |
| --- | --- |
| JPG 压缩 | `tests/test_compressor.py::test_jpeg_quality_compression` |
| PNG 无损优化 | `tests/test_compressor.py::test_png_lossless_optimization` |
| WebP 压缩 | `tests/test_compressor.py::test_webp_compression` |
| PNG 透明通道保护 | `tests/test_converter.py::test_png_to_webp_keeps_alpha` |
| JPG 方向信息处理 | `tests/test_metadata.py::test_exif_orientation_is_applied_and_removed` |
| 图片格式转换 | `tests/test_converter.py` |
| 图片尺寸调整 | `tests/test_resizer.py` |
| 指定目标大小压缩 | `tests/test_compressor.py::test_target_size_binary_search` |
| 文件夹递归扫描 | `tests/test_batch.py::test_recursive_scan_preserves_directory_structure` |
| 多线程并发 | `tests/test_batch.py::test_concurrent_processing` |
| 损坏图片异常处理 | `tests/test_batch.py::test_corrupt_image_does_not_stop_batch` |
| 文件名冲突处理 | `tests/test_batch.py::test_filename_conflict_rename` |
| 元数据保留和清理 | `tests/test_metadata.py` |
| GIF 动画处理 | `tests/test_batch.py::test_gif_animation_first_frame_and_all_frames` |
| TIFF 多页处理 | `tests/test_batch.py::test_multipage_tiff_preserved` |

静态检查：

```bash
ruff check src tests examples
```

## 打包

不同操作系统需要分别构建，PyInstaller 不支持跨平台交叉编译。

### macOS

```bash
./packaging/build_macos.sh
# 产物：dist/image-compress/image-compress
```

Apple Silicon 与 Intel 需分别在对应架构的 Mac 上执行；如需通用二进制，可分别构建后用 `lipo` 合并，或使用 GitHub Actions 的 `macos-13` / `macos-14` runner。

### Windows

```bat
packaging\build_windows.bat
:: 产物：dist\image-compress\image-compress.exe
```

在 Windows 10/11 的 Python 3.11+ 环境中运行；建议使用 64 位 Python。

### Linux

```bash
./packaging/build_linux.sh
# 产物：dist/image-compress/image-compress
```

建议在目标发行版或较旧的 glibc 环境中构建，以获得更好的兼容性。

### 打包说明

- 打包脚本会自动安装项目与 PyInstaller，并调用 `packaging/image-compress.spec`。
- 已安装 `pillow-heif` 时，spec 会自动收集其子模块；未安装时基础功能仍可用。
- 打包后可在 `dist/image-compress/` 目录内直接运行，不需要目标机器安装 Python。
- 外部工具 `oxipng` / `jpegtran` 不打包；需要时由用户单独安装。

## 项目结构

```text
.
├── src/
│   └── image_compressor/
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py
│       ├── cli.py
│       ├── config.py
│       ├── scanner.py
│       ├── compressor.py
│       ├── converter.py
│       ├── resizer.py
│       ├── optimizer.py
│       ├── metadata.py
│       ├── worker.py
│       ├── reporter.py
│       └── utils.py
├── tests/
│   ├── conftest.py
│   ├── test_compressor.py
│   ├── test_converter.py
│   ├── test_resizer.py
│   ├── test_metadata.py
│   ├── test_batch.py
│   └── test_cli.py
├── examples/
│   ├── benchmark.py
│   └── compare_formats.py
├── docs/
│   ├── performance.md
│   ├── format-comparison.md
│   ├── performance-data.json
│   ├── performance-data-1000.json
│   └── format-comparison-data.json
├── packaging/
│   ├── entrypoint.py
│   ├── image-compress.spec
│   ├── build_macos.sh
│   ├── build_windows.bat
│   └── build_linux.sh
├── output/
│   └── .gitkeep
├── logs/
│   └── .gitkeep
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── requirements-optional.txt
├── README.md
└── LICENSE
```

运行时自动创建 `output/` 和 `logs/`。

## 常见问题

### 为什么输出文件比原图还大？

格式转换（如 PNG 转 BMP）、无损格式或原图本身已经高度压缩时，输出可能变大。程序在“同格式、无缩放、压缩结果未减小”时会保留原始数据；如果显式指定了 `--format`，则按目标格式输出。建议照片使用 JPEG/WebP，截图和透明素材使用 PNG。

### 透明 PNG 转 JPEG 出现黑底怎么办？

程序默认用白色背景合成透明区域，不会出现黑底。需要其他颜色时使用：

```bash
image-compress -i ./images -o ./output --format jpg --background "#f5f5f5"
```

支持 `white`、`#rrggbb`、`255,255,255` 等写法。

### 为什么目标大小没有达到？

目标大小是尽力优化。若最低质量（默认 10）仍无法达到目标，程序会输出最接近的结果，并在 JSON 报告的 `note` 中说明。可以降低 `--min-quality`，或同时使用 `--max-width/--max-height` 缩小尺寸。

### 如何清除照片中的 GPS 定位？

```bash
image-compress -i ./images -o ./output --strip-gps
```

保留其他 EXIF；如需清除全部元数据，使用 `--strip-metadata`。

### HEIC / HEIF 无法打开？

安装可选依赖：

```bash
pip install pillow-heif
```

未安装时程序会给出明确错误，其他格式不受影响。

### 如何覆盖原图？

默认拒绝覆盖原始文件。确认要覆盖时：

```bash
image-compress -i ./images -o ./images --overwrite --yes
```

`--overwrite` 在交互终端会再次询问；非交互环境必须同时提供 `--yes`。

### 输出文件已存在怎么办？

默认会先清空输出目录，因此不会出现旧文件冲突。使用 `--no-clean-output` 保留旧文件时，同名输出默认跳过并计入“跳过数量”；需要覆盖用 `--overwrite`，需要保留旧文件并生成新名字用 `--rename-conflicts`。

### 如何保留输出目录里的旧文件？

加 `--no-clean-output`。注意：保留旧文件且输出同名时，默认会跳过已存在的输出；需要重新生成请配合 `--overwrite`，需要生成新名字请配合 `--rename-conflicts`。

### 想重新压缩文件名带 `_compressed` 的图片？

默认会跳过这类输入；加 `--no-skip-compressed` 可重新处理。输出文件名默认保持不变，如需区分新旧文件可加 `--suffix`。

### 处理大图时内存占用高怎么办？

降低并发：

```bash
image-compress -i ./images -o ./output --workers 2
```

任务队列本身有界，不会一次性加载所有图片；峰值主要来自同时解码的图片数量。

### GIF 动画只剩第一帧？

默认只处理第一帧以控制体积；保留动画使用：

```bash
image-compress -i ./anim.gif -o ./output --all-frames
```

### TIFF 多页只剩第一页？

输出 TIFF 时默认保留全部页面；转换为 JPEG/PNG 等单页格式时只处理第一页，并在报告 `note` 中说明。

### 外部优化工具没有生效？

`--external-optimize` 只使用已安装的 `oxipng` 和 `jpegtran`。未安装或执行失败会自动跳过，不影响主流程。可通过 `--log-level DEBUG` 查看原因。

## 开发

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,heif]"
pytest
ruff check src tests examples
```

代码遵循 PEP 8，关键算法（目标体积二分搜索、无损缩放搜索、EXIF 方向、透明合成、ICC 转换）均有注释说明。

## 许可

MIT License，见 [LICENSE](LICENSE)。
