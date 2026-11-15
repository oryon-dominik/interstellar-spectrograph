import pytest

from spectrograph import planning
from spectrograph.types import Rendition, Slot, Source


def source(*, width: int, height: int, format: str = "png") -> Source:
    return Source(digest="0123456789abcdef", width=width, height=height, format=format)


def test_a_wide_image_fills_the_slot_width():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    assert planning.fitting_width(source=source(width=2000, height=1000), slot=card) == 240


def test_a_tall_image_is_bound_by_the_slot_height():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    assert planning.fitting_width(source=source(width=1000, height=2000), slot=card) == 120


def test_a_small_image_is_never_scaled_up():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    assert planning.fitting_width(source=source(width=100, height=100), slot=card) == 100


def test_a_large_original_gets_all_three_densities():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    planned = planning.renditions(source=source(width=1024, height=1024), slot=card)
    assert planned == [
        Rendition(slot="card", width=240, format="png"),
        Rendition(slot="card", width=480, format="png"),
        Rendition(slot="card", width=720, format="png"),
    ]


def test_a_density_close_to_the_original_is_skipped():
    """480 and 720 exceed 80 % of 500 — the original serves those densities itself."""
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    planned = planning.renditions(source=source(width=500, height=500), slot=card)
    assert planned == [Rendition(slot="card", width=240, format="png")]


def test_a_small_original_in_its_own_format_needs_no_rendition():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    assert planning.renditions(source=source(width=100, height=100), slot=card) == []


def test_a_small_original_in_another_format_is_converted_at_its_size():
    avatar = Slot(name="avatar", width=240, height=240, formats=("avif", "png"), originals=True)
    planned = planning.renditions(source=source(width=100, height=100), slot=avatar)
    assert planned == [Rendition(slot="avatar", width=100, format="avif")]


def test_an_unknown_format_is_refused():
    card = Slot(name="card", width=240, height=240, formats=("gif",), originals=True)
    with pytest.raises(ValueError, match="gif"):
        planning.renditions(source=source(width=1024, height=1024), slot=card)


def test_a_rendition_names_its_file():
    assert Rendition(slot="card", width=480, format="png").filename == "card-480.png"


def test_a_sliver_is_planned_at_least_one_pixel_wide():
    hero = Slot(name="hero", width=100, height=100, formats=("png",), originals=True)
    assert planning.fitting_width(source=source(width=1, height=10000), slot=hero) == 1


@pytest.mark.parametrize(
    ("width", "height", "formats"), [(0, 240, ("png",)), (240, -1, ("png",)), (240, 240, ("jpg",))]
)
def test_a_slot_without_area_or_with_an_unknown_format_is_refused(width: int, height: int, formats: tuple[str, ...]):
    with pytest.raises(ValueError, match="card"):
        planning.check(Slot(name="card", width=width, height=height, formats=formats))


def test_without_originals_a_full_width_rendition_takes_the_original_s_place():
    """The original's own format still reaches its full width, re-encoded without metadata."""
    card = Slot(name="card", width=240, height=240, formats=("png", "webp"))
    planned = planning.renditions(source=source(width=1024, height=1024), slot=card)
    assert planned == [
        Rendition(slot="card", width=240, format="png"),
        Rendition(slot="card", width=480, format="png"),
        Rendition(slot="card", width=720, format="png"),
        Rendition(slot="card", width=1024, format="png"),
        Rendition(slot="card", width=240, format="webp"),
        Rendition(slot="card", width=480, format="webp"),
        Rendition(slot="card", width=720, format="webp"),
    ]


def test_without_originals_a_small_original_is_re_encoded_at_its_size():
    card = Slot(name="card", width=240, height=240, formats=("png",))
    assert planning.renditions(source=source(width=100, height=100), slot=card) == [
        Rendition(slot="card", width=100, format="png")
    ]
