"""Whatever fills a port — the adapter or a test's fake — keeps the promise serve relies on."""

from pathlib import Path

import pytest

from spectrograph import django as spectrograph_django
from spectrograph.adapters import disk, pillow
from spectrograph.types import MEDIA_TYPES, Rendition


@pytest.fixture(params=["pillow", "fake"])
def render(request: pytest.FixtureRequest):
    """The Pillow renderer, then the recording fake."""
    return pillow.render if request.param == "pillow" else request.getfixturevalue("renderer")


@pytest.fixture(params=["pillow", "fake"])
def inspect(request: pytest.FixtureRequest):
    """The Pillow inspector, then the fake that knows every original as SOURCE."""
    return pillow.inspect if request.param == "pillow" else request.getfixturevalue("inspector")


@pytest.fixture(params=["disk", "fake"])
def read(request: pytest.FixtureRequest):
    """The disk reader, then the fake that reads every original as its name."""
    return disk.read if request.param == "disk" else request.getfixturevalue("reader")


@pytest.fixture(params=["disk", "storage", "fake"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    """The disk store, the Django storage adapter, then the in-memory fake."""
    match request.param:
        case "disk":
            return disk.Store(tmp_path)
        case "storage":
            storage = spectrograph_django.AtomicFileSystemStorage(location=tmp_path)
            return spectrograph_django.StorageStore(storage)
        case _:
            return request.getfixturevalue("shelf")


def test_render_hands_back_the_bytes_of_the_rendition(render, portrait: Path):
    data = render(original=portrait.read_bytes(), rendition=Rendition(slot="card", width=240, format="png"))

    assert isinstance(data, bytes)
    assert data


def test_inspect_names_a_digest_a_size_and_a_readable_format(inspect, portrait: Path):
    source = inspect(portrait)

    assert len(source.digest) == 16
    assert int(source.digest, 16) >= 0
    assert source.width > 0
    assert source.height > 0
    assert source.format in MEDIA_TYPES


def test_read_hands_back_the_bytes_of_an_unchanged_original(read, portrait: Path):
    data = read(portrait, digest=pillow.inspect(portrait).digest)

    assert isinstance(data, bytes)
    assert data


def test_a_store_finds_nothing_it_was_not_given(store):
    assert store.find(digest="0123456789abcdef", filename="card-240.png") is None


def test_a_store_finds_a_rendition_where_it_put_it(store):
    written = store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    assert store.find(digest="0123456789abcdef", filename="card-240.png") == written


def test_a_store_opens_what_it_put_under_the_name_it_gave(store):
    name = store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    with store.open(name) as handle:
        assert handle.read() == b"pixels"


def test_a_second_put_of_the_same_content_keeps_one_name(store):
    """Two first requests render the same file; both must point at one copy."""
    first = store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")
    second = store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    assert first == second


@pytest.fixture(params=["django", "fake"])
def signer(request: pytest.FixtureRequest):
    """The Django signer, then the backwards stamp."""
    if request.param == "django":
        return spectrograph_django.URLSigner(salt="portraits")
    return request.getfixturevalue("stamp")


SIGNED_URL = {"key": "athena", "digest": "0123456789abcdef", "filename": "card-240.png", "expires": 1_800_000_000}


def test_a_signer_accepts_its_own_signature(signer):
    signature = signer.sign(**SIGNED_URL)

    assert signer.is_valid(**SIGNED_URL, signature=signature)


@pytest.mark.parametrize("field", ["key", "digest", "filename", "expires"])
def test_a_signer_refuses_a_signature_for_another_url(signer, field: str):
    signature = signer.sign(**SIGNED_URL)
    other = {**SIGNED_URL, field: SIGNED_URL[field] + 1 if field == "expires" else f"{SIGNED_URL[field]}x"}

    assert not signer.is_valid(**other, signature=signature)
