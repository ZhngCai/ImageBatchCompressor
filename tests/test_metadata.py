"""元数据处理测试：EXIF 方向、GPS、ICC、清除元数据。"""

from __future__ import annotations

from pathlib import Path

from conftest import make_photo, srgb_profile
from PIL import Image

from image_compressor.config import CompressConfig, MetadataConfig
from image_compressor.scanner import ImageSource
from image_compressor.worker import process_image


def _source(path: Path) -> ImageSource:
    return ImageSource(path=path, root=path.parent)


def _make_exif_jpeg(path: Path, *, gps: bool = False, icc: bool = False) -> None:
    image = make_photo((120, 80))
    exif = image.getexif()
    exif[0x010E] = "unit-test-description"
    exif[0x0112] = 6
    if gps:
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (39.0, 54.0, 27.0)
        gps_ifd[3] = "E"
        gps_ifd[4] = (116.0, 23.0, 17.0)
    kwargs = {"quality": 95, "exif": exif.tobytes()}
    if icc:
        kwargs["icc_profile"] = srgb_profile()
    image.save(path, **kwargs)


def test_exif_orientation_is_applied_and_removed(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "oriented.jpg"
    _make_exif_jpeg(source)

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.size == (80, 120)
        exif = image.getexif()
        assert 0x0112 not in exif
        assert exif.get(0x010E) == "unit-test-description"


def test_strip_metadata_removes_exif_and_icc(
    tmp_path: Path, output_dir: Path
) -> None:
    source = tmp_path / "metadata.jpg"
    _make_exif_jpeg(source, icc=True)
    config = CompressConfig(
        output_dir=output_dir, metadata=MetadataConfig(keep=False)
    )

    result = process_image(_source(source), config)

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert len(dict(image.getexif())) == 0
        assert not image.info.get("icc_profile")


def test_strip_gps_keeps_other_exif(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "gps.jpg"
    _make_exif_jpeg(source, gps=True)
    config = CompressConfig(
        output_dir=output_dir, metadata=MetadataConfig(keep=True, strip_gps=True)
    )

    result = process_image(_source(source), config)

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        exif = image.getexif()
        assert exif.get(0x010E) == "unit-test-description"
        assert 0x8825 not in exif
        assert dict(exif.get_ifd(0x8825)) == {}


def test_icc_profile_is_preserved(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "icc.jpg"
    _make_exif_jpeg(source, icc=True)
    original_profile = srgb_profile()

    result = process_image(_source(source), CompressConfig(output_dir=output_dir))

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as image:
        assert image.info.get("icc_profile") == original_profile


def test_png_transparency_preserved(tmp_path: Path, output_dir: Path) -> None:
    source = tmp_path / "alpha.png"
    image = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    image.putpixel((30, 20), (255, 0, 0, 255))
    image.save(source)

    result = process_image(
        _source(source), CompressConfig(output_dir=output_dir, output_format="PNG")
    )

    assert result.status == "success"
    assert result.output is not None
    with Image.open(result.output) as output:
        assert output.mode in ("RGBA", "LA", "P")
        rgba = output.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getpixel((30, 20))[3] == 255
