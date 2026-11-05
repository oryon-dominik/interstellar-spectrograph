"""Fakes for serve's ports — typed stand-ins that never open an image and never touch a disk."""

import io

import pytest

from spectrograph.types import Rendition, Source

SOURCE = Source(digest="0123456789abcdef", width=1024, height=1024, format="png")


class Renderer:
    """Counts its calls, so a test can see whether a rendition was made or reused."""

    def __init__(self):
        self.calls: list[Rendition] = []

    def __call__(self, *, original: bytes, rendition: Rendition) -> bytes:
        self.calls.append(rendition)
        return rendition.filename.encode() + b" from " + original


class Shelf:
    """Keeps renditions in memory by name."""

    def __init__(self):
        self.kept: dict[str, bytes] = {}

    def find(self, *, digest: str, filename: str) -> str | None:
        name = f"{digest}/{filename}"
        return name if name in self.kept else None

    def put(self, *, digest: str, filename: str, data: bytes) -> str:
        name = f"{digest}/{filename}"
        self.kept[name] = data
        return name

    def open(self, name: str) -> io.BytesIO:
        return io.BytesIO(self.kept[name])


@pytest.fixture
def renderer() -> Renderer:
    """A render port that records every call."""
    return Renderer()


@pytest.fixture
def inspector():
    """An inspect port that knows every original as SOURCE."""
    return lambda path: SOURCE


@pytest.fixture
def reader():
    """A read port that hands back the original's name as its bytes, whatever the digest."""
    return lambda path, *, digest: f"bytes of {path.name}".encode()


@pytest.fixture
def shelf() -> Shelf:
    """A store port that keeps everything in memory."""
    return Shelf()


class Stamp:
    """Signs by spelling the URL backwards — enough to tell one URL from another."""

    def sign(self, *, key: str, digest: str, filename: str, expires: int) -> str:
        return f"{key}/{digest}/{filename}/{expires}"[::-1]

    def is_valid(self, *, key: str, digest: str, filename: str, expires: int, signature: str) -> bool:
        return signature == self.sign(key=key, digest=digest, filename=filename, expires=expires)


@pytest.fixture
def stamp() -> Stamp:
    """A signer port without a secret."""
    return Stamp()
