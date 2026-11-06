# 不同图片格式压缩效果对比

本报告使用真实照片素材，对比 JPEG、WebP、PNG、BMP、TIFF、GIF 的体积和客观质量（PSNR）。

## 测试素材与方法

- 源图：本机 macOS 壁纸 `Sequoia Sunrise.heic`（3840×2160，真实照片），缩放到 1920×1080。
- 基准：JPEG 质量 95，752.4 KB（770,496 bytes）。
- PSNR 以 1920×1080 RGB 原图为参考，数值越高越接近原图；无损格式显示为 ∞。
- 运行命令：

```bash
python examples/compare_formats.py --json docs/format-comparison-data.json
```

## 对比结果

| 格式 | 设置 | 体积 | 相对 JPEG q95 | PSNR | 类型 |
| --- | --- | ---: | ---: | ---: | --- |
| JPEG | 质量 85，optimize | 450.2 KB | 59.8% | 36.23 dB | 有损 |
| WebP | 质量 85，method 6 | 348.8 KB | 46.4% | 36.87 dB | 有损 |
| PNG | optimize，compress_level 9 | 3269.8 KB | 434.6% | ∞ | 无损 |
| BMP | 24 位未压缩 | 6075.1 KB | 807.4% | ∞ | 无损 |
| TIFF | deflate 压缩 | 4845.5 KB | 644.0% | ∞ | 无损 |
| GIF | 256 色自适应调色板 | 1827.3 KB | 242.8% | 35.22 dB | 有损（调色板） |

## 结果解读

1. **WebP 在本测试中体积最小、PSNR 最高**：348.8 KB、36.87 dB，相比 JPEG q85 再小约 22%，适合 Web 发布和照片压缩。
2. **JPEG q85 是兼容性最好的有损选择**：450.2 KB、36.23 dB，几乎所有平台和旧软件都能打开。
3. **PNG 适合无损和透明场景**：本测试照片为连续色调，PNG 体积约为 JPEG q95 的 4.3 倍；但对截图、图标、带透明通道的素材，PNG 是正确选择。
4. **BMP 和 TIFF 不适合分发**：BMP 无压缩，体积约为 JPEG q95 的 8 倍；TIFF deflate 约为 6.4 倍。TIFF 更适合归档、印刷和多页文档。
5. **GIF 只适合简单图形或动图**：256 色调色板会把照片压缩到 1.8 MB，PSNR 35.22 dB，且会出现色带；照片不建议输出 GIF。
6. **PSNR 只反映像素误差**，不覆盖人眼对色块、锐度、文字边缘的感知。实际选择格式时，建议同时查看样张。

## 目标体积模式对比

同一张 4K JPEG（质量 95，2200.6 KB）使用 `--target-size 500KB`：

| 指标 | 结果 |
| --- | ---: |
| 输出体积 | 496.5 KB |
| 自动搜索质量 | 35 |
| 单张耗时 | 0.524 秒 |
| 是否达到目标 | 是 |

目标体积模式会优先尝试较高质量，再用二分搜索找到满足体积的最高质量；如果最低质量仍无法达到目标，会输出最接近的结果并在 `note` 中说明原因。

## 复现

```bash
python examples/compare_formats.py
python examples/compare_formats.py --source /path/to/photo.jpg --width 2560
```

原始数据见 [`docs/format-comparison-data.json`](format-comparison-data.json)。
