"""Read originals and keep renditions on disk, one directory per digest."""

import hashlib
import io
import os
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

DIGEST_LENGTH = 16


def content_digest(handle: BinaryIO) -> str:
    """Return the digest a URL carries: the start of the content's SHA-256."""
    return hashlib.file_digest(handle, "sha256").hexdigest()[:DIGEST_LENGTH]


def read(path: Path, *, digest: str) -> bytes:
    """Return the original's bytes; raise OSError if `digest` no longer fits.

    Whatever is rendered or kept is made from these very bytes, so a file replaced after
    it was inspected never goes out under the old URL.
    """
    data = path.read_bytes()
    if content_digest(io.BytesIO(data)) != digest:
        raise OSError(f"{path} changed since it was inspected")
    return data


def write_atomically(target: Path, chunks: Iterable[bytes]) -> None:
    """Write through a temporary file, so a reader never sees half a file.

    The file takes the umask's default rights rather than tempfile's 0600, so a web
    server placed in front of the directory can read it.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{secrets.token_hex(8)}.partial")
    try:
        with temporary.open("xb") as file:
            for chunk in chunks:
                file.write(chunk)
        try:
            os.replace(temporary, target)
        except PermissionError:
            # Windows refuses to replace a file a reader holds open. Another request
            # wrote the same content first, so its file stands.
            if not target.is_file():
                raise
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    """Keep served files under `root`, named `<digest>/<filename>`."""

    def __init__(self, root: Path):
        self.root = root

    def find(self, *, digest: str, filename: str) -> str | None:
        name = f"{digest}/{filename}"
        return name if (self.root / name).is_file() else None

    def put(self, *, digest: str, filename: str, data: bytes) -> str:
        name = f"{digest}/{filename}"
        write_atomically(self.root / name, [data])
        return name

    def open(self, name: str) -> BinaryIO:
        return (self.root / name).open("rb")
