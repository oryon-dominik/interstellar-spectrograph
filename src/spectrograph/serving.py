"""Hand out a rendition or the original, framework-free.

An adapter such as `spectrograph.django` wraps this into a web framework.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Protocol

from . import planning
from .adapters import disk, pillow
from .types import MEDIA_TYPES, Rendition, Served, Slot, Source

# The URL carries the content digest, so its content never changes. A shared cache
# may keep such an answer; one served behind a login must not (the Django view replaces
# the header when it has a guard).
HEADERS = {"Cache-Control": "max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}

# A signed URL expires at the end of the window after the running one: a page hands
# out one URL for a whole window, so browser caches hit, and none lives past two.
WINDOW = timedelta(days=14)

log = logging.getLogger("spectrograph")

type Resolve = Callable[[str], Path | None]
# The ports below raise OSError for an original they cannot read.
type Inspect = Callable[[Path], Source]


class Read(Protocol):
    """Return the original's bytes, refused once they no longer match `digest`."""

    def __call__(self, path: Path, *, digest: str) -> bytes: ...


class Render(Protocol):
    """Encode one rendition of the original's bytes."""

    def __call__(self, *, original: bytes, rendition: Rendition) -> bytes: ...


class Store(Protocol):
    """Keep served files by name: `find` looks one up, `put` adds one."""

    def find(self, *, digest: str, filename: str) -> str | None: ...

    def put(self, *, digest: str, filename: str, data: bytes) -> str: ...

    def open(self, name: str) -> BinaryIO: ...


class Signer(Protocol):
    """Sign a URL with its expiry; `is_valid` checks a presented signature."""

    def sign(self, *, key: str, digest: str, filename: str, expires: int) -> str: ...

    def is_valid(self, *, key: str, digest: str, filename: str, expires: int, signature: str) -> bool: ...


def expires_at(*, now: float, window: timedelta) -> int:
    """Return the expiry of a URL signed at `now`: the next window's end."""
    seconds = int(window.total_seconds())
    return (int(now) // seconds + 2) * seconds


def serve(
    *,
    key: str,
    digest: str,
    filename: str,
    resolve: Resolve,
    slots: Sequence[Slot],
    store: Store,
    inspect: Inspect = pillow.inspect,
    read: Read = disk.read,
    render: Render = pillow.render,
) -> Served | None:
    """Return the file behind a URL, or None when it names nothing current.

    Only keys `resolve` knows and only renditions the plan names are served — no path
    and no width is taken from the URL itself. A file is made and kept on first request,
    the original too, always from bytes whose digest was checked.
    """
    source_path = resolve(key)
    if source_path is None:
        return None
    try:
        source = inspect(source_path)
    except OSError as error:
        # Gone since `resolve` found it, unreadable, or not in a readable format.
        log.warning("Cannot read the original %s: %s", source_path, error)
        return None
    if source.digest != digest:
        return None
    if filename == f"original.{source.format}":
        # The original may be any readable format, GIF and TIFF included.
        rendition, image_format = None, source.format
    else:
        planned = {each.filename: each for slot in slots for each in planning.renditions(source=source, slot=slot)}
        rendition = planned.get(filename)
        if rendition is None:
            return None
        image_format = rendition.format
    name = store.find(digest=digest, filename=filename)
    if name is None:
        try:
            original = read(source_path, digest=digest)
            data = original if rendition is None else render(original=original, rendition=rendition)
        except OSError as error:
            # Changed since inspected, or a header that reads fine over a broken body.
            log.warning("Cannot serve %s from %s: %s", filename, source_path, error)
            return None
        name = store.put(digest=digest, filename=filename, data=data)
    return Served(name=name, mime=MEDIA_TYPES[image_format], headers=dict(HEADERS))
