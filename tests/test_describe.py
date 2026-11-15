from spectrograph import describe
from spectrograph.types import Slot, Source


def url_for(key: str, digest: str, filename: str) -> str:
    return f"/portraits/{key}/{digest}/{filename}"


def test_the_descriptor_offers_every_density_and_the_original():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    source = Source(digest="abc", width=1024, height=1024, format="png")

    descriptor = describe.describe(key="athena", source=source, slot=card, url_for=url_for)

    assert descriptor.width == 240
    assert descriptor.height == 240
    assert descriptor.sizes == "240px"
    assert descriptor.src == {"png": "/portraits/athena/abc/card-240.png"}
    assert descriptor.srcset == {
        "png": (
            "/portraits/athena/abc/card-240.png 240w, "
            "/portraits/athena/abc/card-480.png 480w, "
            "/portraits/athena/abc/card-720.png 720w, "
            "/portraits/athena/abc/original.png 1024w"
        )
    }
    assert descriptor.original == "/portraits/athena/abc/original.png"


def test_the_height_follows_the_aspect_ratio_of_the_original():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    source = Source(digest="abc", width=1000, height=500, format="png")

    descriptor = describe.describe(key="athena", source=source, slot=card, url_for=url_for)

    assert (descriptor.width, descriptor.height) == (240, 120)


def test_a_small_original_is_its_own_src():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    source = Source(digest="abc", width=100, height=100, format="png")

    descriptor = describe.describe(key="athena", source=source, slot=card, url_for=url_for)

    assert descriptor.src == {"png": "/portraits/athena/abc/original.png"}
    assert descriptor.srcset == {"png": "/portraits/athena/abc/original.png 100w"}


def test_another_format_carries_only_its_renditions():
    avatar = Slot(name="avatar", width=240, height=240, formats=("avif", "png"), originals=True)
    source = Source(digest="abc", width=500, height=500, format="png")

    descriptor = describe.describe(key="athena", source=source, slot=avatar, url_for=url_for)

    assert descriptor.src["avif"] == "/portraits/athena/abc/avatar-240.avif"
    assert descriptor.srcset["avif"] == "/portraits/athena/abc/avatar-240.avif 240w"


def test_a_sliver_is_described_one_pixel_high():
    card = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
    source = Source(digest="abc", width=5000, height=10, format="png")

    descriptor = describe.describe(key="athena", source=source, slot=card, url_for=url_for)

    assert (descriptor.width, descriptor.height) == (240, 1)


def test_without_originals_no_url_names_the_original():
    card = Slot(name="card", width=240, height=240, formats=("png",))
    source = Source(digest="abc", width=1024, height=1024, format="png")

    descriptor = describe.describe(key="athena", source=source, slot=card, url_for=url_for)

    assert descriptor.original is None
    assert descriptor.srcset["png"].endswith("/portraits/athena/abc/full-1024.png 1024w")
    assert "original" not in descriptor.src["png"] + descriptor.srcset["png"]
