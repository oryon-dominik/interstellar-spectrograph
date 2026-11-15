"""Describe an image in a slot, from the plan alone: no file is touched."""

from collections.abc import Callable

from . import planning
from .types import Descriptor, Slot, Source

type UrlFor = Callable[[str, str, str], str]


def describe(*, key: str, source: Source, slot: Slot, url_for: UrlFor) -> Descriptor:
    """Build src and srcset per format, the original as the sharpest choice where the slot offers it.

    `url_for(key, digest, filename)` builds the URL — the bridge to whatever serves the files.
    """
    width = planning.fitting_width(source=source, slot=slot)
    original = url_for(key, source.digest, f"original.{source.format}") if slot.originals else None
    planned = planning.renditions(source=source, slot=slot)
    src, srcset = {}, {}
    for image_format in slot.formats:
        candidates = [
            (url_for(key, source.digest, rendition.filename), rendition.width)
            for rendition in planned
            if rendition.format == image_format
        ]
        if original is not None and image_format == source.format:
            candidates.append((original, source.width))
        src[image_format] = next(url for url, candidate_width in candidates if candidate_width >= width)
        srcset[image_format] = ", ".join(f"{url} {candidate_width}w" for url, candidate_width in candidates)
    return Descriptor(
        width=width,
        height=max(1, round(width * source.height / source.width)),
        sizes=f"{width}px",
        src=src,
        srcset=srcset,
        original=original,
    )
