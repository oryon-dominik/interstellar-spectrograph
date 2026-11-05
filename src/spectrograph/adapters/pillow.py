"""Read and render images with Pillow: the one place a file is opened."""

import contextlib
import functools
import io
import struct
from collections.abc import Iterator
from pathlib import Path

from PIL import Image, ImageOps

from ..types import READABLE, Rendition, Source
from . import disk

# EXIF orientations 5 to 8 store the pixels on their side.
SIDEWAYS = {5, 6, 7, 8}
ORIENTATION = 0x0112
# Formats without an alpha channel get the image flattened onto white.
OPAQUE = {"jpeg"}
# Modes whose colour profile still describes the pixels once they are RGB. A CMYK or
# grey profile on RGB pixels would make the browser misread every colour.
RGB_PROFILED = {"RGB", "RGBA", "P", "PA"}


@contextlib.contextmanager
def _unreadable_as_os_error() -> Iterator[None]:
    """Turn each way Pillow refuses an original into the promised OSError.

    A corrupt EXIF block raises SyntaxError, a broken chunk ValueError or struct.error.
    """
    try:
        yield
    except (Image.DecompressionBombError, SyntaxError, ValueError, struct.error) as error:
        raise OSError(str(error)) from error


def _refuse_oversized(image: Image.Image) -> None:
    """Refuse what Pillow only warns about, up to twice its pixel limit."""
    limit = Image.MAX_IMAGE_PIXELS
    if limit is not None and image.width * image.height > limit:
        raise OSError(f"Image size ({image.width * image.height} pixels) exceeds limit of {limit} pixels")


def inspect(path: Path) -> Source:
    """Return an original's digest, upright size and format, cached."""
    stat = path.stat()
    return _inspect(path, stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=1024)
def _inspect(path: Path, mtime_ns: int, size: int) -> Source:
    """Inspect once per mtime and size, so a rewritten file misses the cache.

    A rewrite that keeps both — a coarse clock, the same size — goes unseen here. Its new
    bytes still never go out under the old URL: `disk.read` refuses them, and what the
    store already keeps is what that URL always meant.
    """
    with path.open("rb") as handle, _unreadable_as_os_error():
        digest = disk.content_digest(handle)
        handle.seek(0)
        with Image.open(handle, formats=READABLE) as image:
            _refuse_oversized(image)
            width, height = image.size
            if image.getexif().get(ORIENTATION) in SIDEWAYS:
                width, height = height, width
            # A phone's MPO is a JPEG with extra frames; browsers show it as the JPEG it starts with.
            image_format = "jpeg" if image.format == "MPO" else image.format.lower()
    return Source(digest=digest, width=width, height=height, format=image_format)


def render(*, original: bytes, rendition: Rendition) -> bytes:
    """Turn the original upright, scale it and encode it as the rendition."""
    with _unreadable_as_os_error(), Image.open(io.BytesIO(original), formats=READABLE) as opened:
        _refuse_oversized(opened)
        image = ImageOps.exif_transpose(opened)
        profile = image.info.get("icc_profile") if image.mode in RGB_PROFILED else None
        if image.mode.startswith("I"):
            # 16- and 32-bit greys: a plain convert clips every value above 255 to white.
            image = image.convert("I").point(lambda value: value / 256).convert("L")
        # Work in RGB or RGBA: every target format stores those, and a palette cannot be
        # resampled smoothly. CMYK and palettes do not all survive otherwise.
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
        # A sliver would round to zero rows; one is the least an image can have.
        height = max(1, round(rendition.width * image.height / image.width))
        if (rendition.width, height) != image.size:
            image = image.resize((rendition.width, height), Image.Resampling.LANCZOS)
        if rendition.format in OPAQUE and has_alpha:
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        buffer = io.BytesIO()
        # Every encoder takes the profile given here; left out, some would carry a stale one along.
        # The empty comment stops JPEG copying the original's, which may say as much as EXIF.
        image.save(buffer, format=rendition.format.upper(), icc_profile=profile, comment=b"")
    return buffer.getvalue()
