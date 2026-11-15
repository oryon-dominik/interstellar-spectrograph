"""The values spectrograph passes around: plain tuples, nothing more."""

from typing import NamedTuple

# What an original may be, and the media type it is served as. Anything else Pillow knows
# stays closed: EPS, for one, hands the file to Ghostscript on load. A phone's MPO opens
# through JPEG.
MEDIA_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "avif": "image/avif",
    "gif": "image/gif",
    "tiff": "image/tiff",
}
READABLE = tuple(image_format.upper() for image_format in MEDIA_TYPES)
# What renditions are made in.
RENDITION_FORMATS = ("png", "jpeg", "webp", "avif")


class Slot(NamedTuple):
    """A place an image shows in: its box, the formats it accepts, and whether it offers the original.

    An original goes out byte for byte, metadata and all, so a slot offers it only when asked to.
    """

    name: str
    width: int
    height: int
    formats: tuple[str, ...]
    originals: bool = False


class Source(NamedTuple):
    """An original as spectrograph sees it: digest, size and format."""

    digest: str
    width: int
    height: int
    format: str


class Rendition(NamedTuple):
    """One derived file at one width in one format: a slot's, or the full-width one slots share."""

    slot: str
    width: int
    format: str

    @property
    def filename(self) -> str:
        return f"{self.slot}-{self.width}.{self.format}"


class Descriptor(NamedTuple):
    """What a client needs to pick an image; `_asdict()` is JSON-ready."""

    width: int
    height: int
    sizes: str
    src: dict[str, str]
    srcset: dict[str, str]
    original: str | None


class Served(NamedTuple):
    """A file ready to send: its store name, media type and headers."""

    name: str
    mime: str
    headers: dict[str, str]
