import logging
import os
from pathlib import Path

import pytest
from PIL import Image

from spectrograph import serving
from spectrograph.adapters import pillow
from spectrograph.types import Rendition, Slot
from tests.fixtures import ports
from tests.fixtures.ports import Renderer, Shelf

CARD = Slot(name="card", width=240, height=240, formats=("png",), originals=True)
ORIGINAL = Path("originals", "athena.png")


@pytest.fixture
def served(renderer: Renderer, inspector, reader, shelf: Shelf):
    """serve with the key `athena` registered and every port faked."""

    def serve(*, key: str = "athena", digest: str = ports.SOURCE.digest, filename: str):
        return serving.serve(
            key=key,
            digest=digest,
            filename=filename,
            resolve={"athena": ORIGINAL}.get,
            slots=[CARD],
            store=shelf,
            inspect=inspector,
            read=reader,
            render=renderer,
        )

    return serve


def test_a_planned_rendition_is_rendered_once_and_then_reused(served, renderer: Renderer, shelf: Shelf):
    first = served(filename="card-480.png")
    second = served(filename="card-480.png")

    assert first == second
    assert shelf.kept[first.name] == b"card-480.png from bytes of athena.png"
    assert first.mime == "image/png"
    assert first.headers == {"Cache-Control": "max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}
    assert renderer.calls == [Rendition(slot="card", width=480, format="png")]


def test_the_original_is_kept_beside_its_renditions_as_it_is(served, renderer: Renderer, shelf: Shelf):
    result = served(filename="original.png")

    assert shelf.kept[result.name] == b"bytes of athena.png"
    assert renderer.calls == []


def test_a_stale_digest_serves_nothing(served):
    assert served(digest="fedcba9876543210", filename="card-240.png") is None


def test_an_unregistered_key_serves_nothing(served):
    assert served(key="../../etc", filename="card-240.png") is None


@pytest.mark.parametrize("filename", ["card-999.png", "card-240.avif", "original.jpeg", "../card-240.png"])
def test_anything_the_plan_does_not_name_serves_nothing(served, renderer: Renderer, filename: str):
    assert served(filename=filename) is None
    assert renderer.calls == []


def test_an_original_outside_the_rendition_formats_is_served_with_its_media_type(
    renderer: Renderer, reader, shelf: Shelf
):
    result = serving.serve(
        key="athena",
        digest=ports.SOURCE.digest,
        filename="original.gif",
        resolve={"athena": ORIGINAL}.get,
        slots=[CARD],
        store=shelf,
        inspect=lambda path: ports.SOURCE._replace(format="gif"),
        read=reader,
        render=renderer,
    )

    assert result.mime == "image/gif"


@pytest.mark.parametrize("content", [None, b"not an image"])
def test_an_original_that_is_gone_or_no_image_serves_nothing(
    tmp_path: Path, shelf: Shelf, content: bytes | None, caplog: pytest.LogCaptureFixture
):
    path = tmp_path / "athena.png"
    if content is not None:
        path.write_bytes(content)

    with caplog.at_level(logging.WARNING, logger="spectrograph"):
        result = serving.serve(
            key="athena",
            digest=ports.SOURCE.digest,
            filename="card-240.png",
            resolve={"athena": path}.get,
            slots=[CARD],
            store=shelf,
        )

    assert result is None
    assert str(path) in caplog.text


@pytest.mark.parametrize("filename", ["card-240.png", "original.png"])
def test_an_original_changed_since_it_was_inspected_serves_nothing(
    inspector, renderer: Renderer, shelf: Shelf, caplog: pytest.LogCaptureFixture, filename: str
):
    def changed(path: Path, *, digest: str) -> bytes:
        raise OSError("changed since it was inspected")

    with caplog.at_level(logging.WARNING, logger="spectrograph"):
        result = serving.serve(
            key="athena",
            digest=ports.SOURCE.digest,
            filename=filename,
            resolve={"athena": ORIGINAL}.get,
            slots=[CARD],
            store=shelf,
            inspect=inspector,
            read=changed,
            render=renderer,
        )

    assert result is None
    assert shelf.kept == {}
    assert "changed" in caplog.text


def test_an_original_that_cannot_be_rendered_serves_nothing(
    inspector, reader, shelf: Shelf, caplog: pytest.LogCaptureFixture
):
    def truncated(*, original: bytes, rendition: Rendition) -> bytes:
        raise OSError("image file is truncated")

    with caplog.at_level(logging.WARNING, logger="spectrograph"):
        result = serving.serve(
            key="athena",
            digest=ports.SOURCE.digest,
            filename="card-240.png",
            resolve={"athena": ORIGINAL}.get,
            slots=[CARD],
            store=shelf,
            inspect=inspector,
            read=reader,
            render=truncated,
        )

    assert result is None
    assert shelf.kept == {}
    assert "truncated" in caplog.text


@pytest.mark.parametrize("filename", ["card-240.png", "original.tiff"])
def test_a_rewrite_the_inspect_cache_misses_never_goes_out_under_the_old_digest(
    tmp_path: Path, shelf: Shelf, filename: str
):
    """A filesystem with coarse timestamps keeps mtime and size across a same-size rewrite."""
    path = tmp_path / "athena.tiff"
    Image.new("RGB", (600, 600), "red").save(path, format="TIFF")
    old = pillow.inspect(path)
    times = path.stat()
    Image.new("RGB", (600, 600), "blue").save(path, format="TIFF")
    assert path.stat().st_size == times.st_size
    os.utime(path, ns=(times.st_atime_ns, times.st_mtime_ns))

    result = serving.serve(
        key="athena",
        digest=old.digest,
        filename=filename,
        resolve={"athena": path}.get,
        slots=[CARD],
        store=shelf,
    )

    assert result is None
    assert shelf.kept == {}


def test_changing_one_answer_s_headers_leaves_the_next_one_alone(served):
    served(filename="original.png").headers.pop("Cache-Control")

    assert "Cache-Control" in served(filename="original.png").headers


def test_without_originals_the_original_serves_nothing(renderer: Renderer, inspector, reader, shelf: Shelf):
    result = serving.serve(
        key="athena",
        digest=ports.SOURCE.digest,
        filename=f"original.{ports.SOURCE.format}",
        resolve={"athena": ORIGINAL}.get,
        slots=[CARD._replace(originals=False)],
        store=shelf,
        inspect=inspector,
        read=reader,
        render=renderer,
    )

    assert result is None
    assert shelf.kept == {}
