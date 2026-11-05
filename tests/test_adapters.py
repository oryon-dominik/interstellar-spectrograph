import io
import os
import stat
from pathlib import Path

import pytest
from PIL import Image, ImageCms

from spectrograph.adapters import disk, pillow
from spectrograph.types import RENDITION_FORMATS, Rendition


@pytest.mark.parametrize("image_format", ["png", "jpeg", "webp", "avif"])
def test_render_shrinks_to_the_rendition_width_in_its_format(portrait: Path, image_format: str):
    data = pillow.render(
        original=portrait.read_bytes(), rendition=Rendition(slot="card", width=240, format=image_format)
    )

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.size == (240, 180)
        assert rendered.format.lower() == image_format


def test_render_turns_a_rotated_photo_upright(tmp_path: Path):
    path = tmp_path / "photo.jpeg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (400, 300)).save(path, format="JPEG", exif=exif)

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=150, format="png"))

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.size == (150, 200)


@pytest.mark.parametrize(("mode", "image_format"), [("CMYK", "png"), ("CMYK", "avif"), ("P", "jpeg"), ("LA", "jpeg")])
def test_render_handles_modes_the_target_format_cannot_store(tmp_path: Path, mode: str, image_format: str):
    path = tmp_path / "original.tiff"
    original = Image.new(mode, (400, 300))
    if mode == "P":
        original.info["transparency"] = 0
    original.save(path, format="TIFF")

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=200, format=image_format))

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.size == (200, 150)


@pytest.mark.parametrize("image_format", RENDITION_FORMATS)
def test_render_keeps_the_colour_profile_of_an_rgb_original(tmp_path: Path, image_format: str):
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = tmp_path / "photo.png"
    Image.new("RGB", (400, 300)).save(path, format="PNG", icc_profile=profile)

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=200, format=image_format))

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.info.get("icc_profile") == profile


@pytest.mark.parametrize("image_format", RENDITION_FORMATS)
def test_render_drops_the_profile_of_a_cmyk_original_once_its_pixels_are_rgb(tmp_path: Path, image_format: str):
    """A CMYK profile on RGB pixels tells the browser to read the colours as ink."""
    path = tmp_path / "print.tiff"
    Image.new("CMYK", (400, 300)).save(path, format="TIFF", icc_profile=b"a cmyk profile")

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=200, format=image_format))

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.info.get("icc_profile") is None


def test_render_refuses_a_truncated_original_with_an_os_error(tmp_path: Path):
    """Its header reads fine, so only rendering finds out."""
    path = tmp_path / "photo.jpeg"
    buffer = io.BytesIO()
    Image.effect_noise((800, 600), 64).convert("RGB").save(buffer, format="JPEG")
    path.write_bytes(buffer.getvalue()[:4000])

    with pytest.raises(OSError, match="truncated"):
        pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=240, format="png"))


def test_an_oversized_original_is_refused_with_an_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Pillow's own refusal is no OSError; the ports promise one for every unreadable original."""
    path = tmp_path / "huge.png"
    Image.new("RGB", (100, 100)).save(path, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(OSError, match="exceeds limit"):
        pillow.inspect(path)
    with pytest.raises(OSError, match="exceeds limit"):
        pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=50, format="png"))


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_an_original_just_above_the_pixel_limit_is_refused_not_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Up to twice the limit Pillow only warns and decodes anyway."""
    path = tmp_path / "huge.png"
    Image.new("RGB", (100, 100)).save(path, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 9000)

    with pytest.raises(OSError, match="exceeds limit"):
        pillow.inspect(path)
    with pytest.raises(OSError, match="exceeds limit"):
        pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=50, format="png"))


@pytest.mark.parametrize("image_format", ["png", "webp"])
def test_a_corrupt_exif_block_is_refused_with_an_os_error(tmp_path: Path, image_format: str):
    """Pillow reports it as a SyntaxError, which nothing behind the ports expects."""
    path = tmp_path / f"photo.{image_format}"
    Image.new("RGB", (400, 300)).save(path, format=image_format.upper(), exif=b"MM\x00\x1cnot a tiff header")

    with pytest.raises(OSError, match="TIFF"):
        pillow.inspect(path)
    with pytest.raises(OSError, match="TIFF"):
        pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=200, format="png"))


@pytest.mark.parametrize("image_format", RENDITION_FORMATS)
def test_a_rendition_leaves_the_exif_of_its_original_behind(tmp_path: Path, image_format: str):
    """EXIF can carry where a photo was taken; the README promises it stays with the original."""
    path = tmp_path / "photo.jpeg"
    exif = Image.Exif()
    exif[0x010F] = "a camera maker"
    exif.get_ifd(0x8825)[2] = (52.0, 31.0, 0.0)
    Image.new("RGB", (400, 300)).save(path, format="JPEG", exif=exif)

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=200, format=image_format))

    with Image.open(io.BytesIO(data)) as rendered:
        assert not rendered.getexif()


def test_read_hands_back_the_bytes_that_hash_to_the_digest(portrait: Path):
    assert disk.read(portrait, digest=pillow.inspect(portrait).digest) == portrait.read_bytes()


def test_read_refuses_bytes_that_no_longer_hash_to_the_digest(portrait: Path):
    with pytest.raises(OSError, match="changed"):
        disk.read(portrait, digest="fedcba9876543210")


def test_render_keeps_a_sliver_one_pixel_high(tmp_path: Path):
    path = tmp_path / "banner.png"
    Image.new("RGB", (5000, 10)).save(path, format="PNG")

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=240, format="png"))

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.size == (240, 1)


def test_render_scales_a_16_bit_grey_instead_of_clipping_it_to_white(tmp_path: Path):
    path = tmp_path / "scan.png"
    Image.new("I;16", (400, 300), 40000).save(path, format="PNG")

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=200, format="png"))

    with Image.open(io.BytesIO(data)) as rendered:
        assert rendered.convert("L").getpixel((100, 75)) == 40000 // 256


def test_the_store_writes_the_bytes_and_leaves_nothing_beside_them(tmp_path: Path):
    name = disk.Store(tmp_path).put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    assert (tmp_path / name).read_bytes() == b"pixels"
    assert [path.name for path in (tmp_path / "0123456789abcdef").iterdir()] == ["card-240.png"]


def test_the_store_replaces_a_rendition_a_reader_holds_open(tmp_path: Path):
    """Two first requests render the same file; the second finds the first one already streaming it."""
    store = disk.Store(tmp_path)
    name = store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    with store.open(name):
        store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    assert [path.name for path in (tmp_path / "0123456789abcdef").iterdir()] == ["card-240.png"]


def test_a_failed_write_leaves_no_temporary_file(tmp_path: Path):
    store = disk.Store(tmp_path)

    with pytest.raises(TypeError):
        store.put(digest="0123456789abcdef", filename="card-240.png", data="not bytes")

    assert list((tmp_path / "0123456789abcdef").iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows has no umask and no group or other bits")
def test_a_rendition_takes_the_default_rights_so_a_web_server_can_read_it(tmp_path: Path):
    previous = os.umask(0o022)
    try:
        name = disk.Store(tmp_path).put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")
    finally:
        os.umask(previous)

    assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o644


def test_render_leaves_a_jpeg_comment_behind(tmp_path: Path):
    """A comment can carry as much as EXIF does, and Pillow would copy it into the rendition."""
    path = tmp_path / "photo.jpeg"
    Image.new("RGB", (400, 300)).save(path, format="JPEG", comment=b"taken at home")

    data = pillow.render(original=path.read_bytes(), rendition=Rendition(slot="card", width=150, format="jpeg"))

    assert b"taken at home" not in data
