"""Which renditions a slot needs — pure arithmetic, no image is opened.

The idea follows django-cast: fit the original into the slot, offer pixel densities
one to three, and skip a width above 80% of the original's, because the original
serves it better. Nothing is ever scaled up. A slot without originals gets a rendition
at the original's full width in its format instead.
"""

from .types import RENDITION_FORMATS, Rendition, Slot, Source

DENSITIES = (1, 2, 3)
CLOSE_TO_ORIGINAL = 0.8


def fitting_width(*, source: Source, slot: Slot) -> int:
    """Return the width the image shows at, never above the original's."""
    if source.width / source.height > slot.width / slot.height:
        width = slot.width
    else:
        width = max(1, round(slot.height * source.width / source.height))
    return min(width, source.width)


def check(slot: Slot) -> None:
    """Raise a ValueError naming a slot no rendition can be planned for."""
    if slot.width < 1 or slot.height < 1:
        raise ValueError(
            f"Slot {slot.name!r} needs a width and a height of at least 1, not {slot.width}x{slot.height}"
        )
    if unknown := [image_format for image_format in slot.formats if image_format not in RENDITION_FORMATS]:
        raise ValueError(
            f"Slot {slot.name!r} asks for unsupported formats {unknown} — known: {list(RENDITION_FORMATS)}"
        )


def renditions(*, source: Source, slot: Slot) -> list[Rendition]:
    """List the renditions the slot needs, by format, smallest first."""
    check(slot)
    width = fitting_width(source=source, slot=slot)
    planned = []
    for image_format in slot.formats:
        widths = [width * density for density in DENSITIES if width * density <= source.width * CLOSE_TO_ORIGINAL]
        if image_format == source.format and not slot.originals:
            # The original's place at the top: same width, without its metadata.
            widths.append(source.width)
        elif not widths and image_format != source.format:
            # Too small to shrink, but the slot wants another format: convert at full size.
            widths = [width]
        planned.extend(Rendition(slot=slot.name, width=each, format=image_format) for each in widths)
    return planned
