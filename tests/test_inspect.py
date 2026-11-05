import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from spectrograph.adapters import pillow


def test_inspect_reads_digest_size_and_format(portrait: Path):
    source = pillow.inspect(portrait)

    assert source.digest == hashlib.sha256(portrait.read_bytes()).hexdigest()[:16]
    assert (source.width, source.height, source.format) == (1024, 768, "png")


def test_a_changed_original_gets_a_new_digest(portrait: Path):
    before = pillow.inspect(portrait)
    Image.new("RGB", (640, 480), (0, 0, 0)).save(portrait, format="PNG")
    stat = portrait.stat()
    os.utime(portrait, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    after = pillow.inspect(portrait)

    assert after.digest != before.digest
    assert (after.width, after.height) == (640, 480)


def test_a_rotated_photo_reports_its_upright_size(tmp_path: Path):
    """EXIF orientation 6 stores the pixels on their side; people see them upright."""
    path = tmp_path / "photo.jpeg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (400, 300)).save(path, format="JPEG", exif=exif)

    source = pillow.inspect(path)

    assert (source.width, source.height, source.format) == (300, 400, "jpeg")


def test_a_phone_photo_in_mpo_reads_as_the_jpeg_it_is(tmp_path: Path):
    """Browsers show an MPO as its first frame, a plain JPEG; image/mpo they would only download."""
    path = tmp_path / "phone.jpeg"
    Image.new("RGB", (64, 48)).save(path, format="MPO", save_all=True, append_images=[Image.new("RGB", (64, 48))])

    assert pillow.inspect(path).format == "jpeg"


def test_a_format_outside_the_readable_set_is_refused(tmp_path: Path):
    """EPS would hand the file to Ghostscript on load."""
    path = tmp_path / "drawing.eps"
    path.write_text("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n", encoding="utf-8", newline="\n")

    with pytest.raises(UnidentifiedImageError):
        pillow.inspect(path)
