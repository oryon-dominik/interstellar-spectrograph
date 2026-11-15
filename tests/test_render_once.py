"""Each rendition is made once per worker, a bounded number at a time, or ahead of any request."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from spectrograph import planning, serving
from spectrograph.types import Rendition, Slot
from tests.fixtures import ports
from tests.fixtures.ports import Renderer, Shelf

CARD = Slot(name="card", width=240, height=240, formats=("png", "webp"))
ORIGINAL = Path("originals", "athena.png")


class SlowRenderer(Renderer):
    """Holds every render until released, and records how many ran at once.

    With `release_at`, it releases itself once that many renders run together.
    """

    def __init__(self, *, release_at: int | None = None):
        super().__init__()
        self.release_at = release_at
        self.release = threading.Event()
        self.running = 0
        self.most_at_once = 0
        self._count = threading.Lock()

    def __call__(self, *, original: bytes, rendition: Rendition) -> bytes:
        with self._count:
            self.running += 1
            self.most_at_once = max(self.most_at_once, self.running)
            if self.running == self.release_at:
                self.release.set()
        self.release.wait(timeout=5)
        try:
            return super().__call__(original=original, rendition=rendition)
        finally:
            with self._count:
                self.running -= 1


def serve(filename: str, *, render, inspector, reader, shelf: Shelf):
    """serve with the key `athena` registered and every port faked."""
    return serving.serve(
        key="athena",
        digest=ports.SOURCE.digest,
        filename=filename,
        resolve={"athena": ORIGINAL}.get,
        slots=[CARD],
        store=shelf,
        inspect=inspector,
        read=reader,
        render=render,
    )


def test_ten_first_requests_for_one_rendition_render_it_once(inspector, reader, shelf: Shelf):
    renderer = SlowRenderer()
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [
            pool.submit(serve, "card-480.png", render=renderer, inspector=inspector, reader=reader, shelf=shelf)
            for _ in range(10)
        ]
        # Release once all ten wait on the one flight: nine behind the lock, one rendering.
        deadline = time.monotonic() + 5
        name = f"{ports.SOURCE.digest}/card-480.png"
        while time.monotonic() < deadline and getattr(serving._flights.get(name), "waiting", 0) < 10:
            time.sleep(0.01)
        renderer.release.set()
        answers = [future.result(timeout=10) for future in futures]

    assert renderer.calls == [Rendition(slot="card", width=480, format="png")]
    assert {answer.name for answer in answers} == {f"{ports.SOURCE.digest}/card-480.png"}


def test_no_more_renders_run_at_once_than_the_limit(monkeypatch, inspector, reader, shelf: Shelf):
    monkeypatch.setattr(serving, "RENDERS_AT_ONCE", threading.BoundedSemaphore(2))
    renderer = SlowRenderer(release_at=2)
    filenames = [rendition.filename for rendition in planning.renditions(source=ports.SOURCE, slot=CARD)]
    with ThreadPoolExecutor(max_workers=len(filenames)) as pool:
        futures = [
            pool.submit(serve, filename, render=renderer, inspector=inspector, reader=reader, shelf=shelf)
            for filename in filenames
        ]
        for future in futures:
            future.result(timeout=10)

    assert renderer.most_at_once == 2
    assert len(renderer.calls) == len(filenames)


def test_warm_makes_every_planned_rendition_ahead_of_any_request(renderer: Renderer, inspector, reader, shelf: Shelf):
    names = serving.warm(
        key="athena",
        resolve={"athena": ORIGINAL}.get,
        slots=[CARD],
        store=shelf,
        inspect=inspector,
        read=reader,
        render=renderer,
    )

    planned = planning.renditions(source=ports.SOURCE, slot=CARD)
    assert renderer.calls == planned
    assert names == [f"{ports.SOURCE.digest}/{rendition.filename}" for rendition in planned]
    assert set(shelf.kept) == set(names)


def test_warm_makes_the_shared_full_width_rendition_once(renderer: Renderer, inspector, reader, shelf: Shelf):
    hero = Slot(name="hero", width=720, height=720, formats=("png",))
    names = serving.warm(
        key="athena",
        resolve={"athena": ORIGINAL}.get,
        slots=[CARD, hero],
        store=shelf,
        inspect=inspector,
        read=reader,
        render=renderer,
    )

    full = Rendition(slot="full", width=ports.SOURCE.width, format="png")
    assert renderer.calls.count(full) == 1
    assert len(names) == len(set(names))


def test_warm_knows_nothing_of_an_unknown_key(renderer: Renderer, inspector, reader, shelf: Shelf):
    names = serving.warm(
        key="hermes",
        resolve={"athena": ORIGINAL}.get,
        slots=[CARD],
        store=shelf,
        inspect=inspector,
        read=reader,
        render=renderer,
    )

    assert names == []
    assert renderer.calls == []


@pytest.fixture(autouse=True)
def _no_flight_left_behind():
    """Every test ends with no flight still registered — the table never grows."""
    yield
    assert serving._flights == {}
