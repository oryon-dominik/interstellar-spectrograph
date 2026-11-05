"""Serve renditions from a Django project: `spectrograph[django]`.

The project mounts `urlpatterns(...)` wherever it likes and hands `url_for(...)` to
`describe`. No settings of its own, no models: everything is passed in.
"""

import time
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlencode

from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import URLPattern, path, reverse
from django.utils.cache import get_conditional_response
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_safe

from . import planning, serving
from .adapters import disk
from .describe import UrlFor
from .types import Slot

type Guard = Callable[[HttpRequest, str], HttpResponse | None]


class AtomicFileSystemStorage(FileSystemStorage):
    """Write atomically, so a reader never sees half a rendition.

    FileSystemStorage writes straight into the target path, so a second worker that sees
    `exists()` while the first still writes would serve half a file — and under
    `immutable` a browser keeps it for a year.
    """

    def _save(self, name: str, content) -> str:
        target = Path(self.path(name))
        disk.write_atomically(target, content.chunks())
        if self.file_permissions_mode is not None:
            target.chmod(self.file_permissions_mode)
        if self.directory_permissions_mode is not None:
            target.parent.chmod(self.directory_permissions_mode)
        return str(name).replace("\\", "/")


class StorageStore:
    """Renditions in any Django storage — the file system or a bucket.

    With `redirect`, the view sends the browser to `storage.url(name)` instead of streaming
    the bytes, and the redirect may be cached that long. A bucket hands out a presigned
    URL there, so `redirect` must stay shorter than that URL's lifetime.
    """

    def __init__(self, storage: Storage, *, redirect: timedelta | None = None):
        self.storage = storage
        self.redirect = redirect

    def find(self, *, digest: str, filename: str) -> str | None:
        name = f"{digest}/{filename}"
        return name if self.storage.exists(name) else None

    def put(self, *, digest: str, filename: str, data: bytes) -> str:
        """Keep the file, dropping the copy when another worker came first.

        A storage that hands out a second name means that worker won. The digest fixes
        the content, so the first name stands.
        """
        name = f"{digest}/{filename}"
        saved = self.storage.save(name, ContentFile(data))
        if saved != name:
            self.storage.delete(saved)
        return name

    def open(self, name: str) -> BinaryIO:
        return self.storage.open(name, "rb")


class URLSigner:
    """Sign URLs with Django's signer and one salt per route.

    Not TimestampSigner: it embeds the moment of signing, so every rendered page would
    carry a new URL and no cache would ever hit.
    """

    def __init__(self, *, salt: str):
        self._signer = signing.Signer(salt=salt)

    def sign(self, *, key: str, digest: str, filename: str, expires: int) -> str:
        return self._signer.signature(f"{key}/{digest}/{filename}/{expires}")

    def is_valid(self, *, key: str, digest: str, filename: str, expires: int, signature: str) -> bool:
        expected = self.sign(key=key, digest=digest, filename=filename, expires=expires)
        return constant_time_compare(signature, expected)


def _signed(request: HttpRequest, signer: serving.Signer, *, key: str, digest: str, filename: str) -> bool:
    """Tell whether the URL carries a current expiry and a valid signature."""
    expires = request.GET.get("expires", "")
    signature = request.GET.get("signature", "")
    if not expires.isdecimal() or not signature or int(expires) < time.time():
        return False
    return signer.is_valid(key=key, digest=digest, filename=filename, expires=int(expires), signature=signature)


def urlpatterns(
    *,
    prefix: str,
    name: str,
    resolve: serving.Resolve,
    slots: Sequence[Slot],
    store: serving.Store,
    signer: serving.Signer | None = None,
    guard: Guard | None = None,
) -> list[URLPattern]:
    """Mount `<prefix><key>/<digest>/<filename>`, for GET and HEAD only.

    `guard(request, key)` may refuse a request before any file is touched. Behind a guard
    the answer is `private, no-cache`: no shared cache keeps it, and the browser asks the
    guard again before it shows its copy — answered 304 while that copy is current.
    Behind a signer alone the answer is `private`: a shared cache would outlive the expiry.
    An invalid slot raises ValueError here, at mount.
    """
    for slot in slots:
        planning.check(slot)

    @require_safe
    def view(request: HttpRequest, key: str, digest: str, filename: str) -> HttpResponse:
        if signer is not None and not _signed(request, signer, key=key, digest=digest, filename=filename):
            raise Http404
        if guard is not None and (refused := guard(request, key)) is not None:
            return refused
        served = serving.serve(key=key, digest=digest, filename=filename, resolve=resolve, slots=slots, store=store)
        if served is None:
            raise Http404
        if isinstance(store, StorageStore) and store.redirect is not None:
            moved = HttpResponseRedirect(store.storage.url(served.name))
            lifetime = int(store.redirect.total_seconds())
            moved["Cache-Control"] = "private, no-cache" if guard is not None else f"private, max-age={lifetime}"
            return moved
        # A saved image is named after the key, never after the file the host keeps.
        response = FileResponse(store.open(served.name), content_type=served.mime, filename=f"{key}-{filename}")
        for header, value in served.headers.items():
            response[header] = value
        response["ETag"] = f'"{digest}-{filename}"'
        if guard is not None:
            response["Cache-Control"] = "private, no-cache"
        elif signer is not None:
            response["Cache-Control"] = f"private, {response['Cache-Control']}"
        answer = get_conditional_response(request, etag=response["ETag"], response=response)
        if answer is not response:
            response.close()
        return answer

    return [path(f"{prefix}<str:key>/<str:digest>/<str:filename>", view, name=name)]


def url_for(
    *,
    name: str,
    signer: serving.Signer | None = None,
    window: timedelta = serving.WINDOW,
    now: Callable[[], float] = time.time,
) -> UrlFor:
    """Build the `url_for` of `describe` for the route mounted under `name`."""

    def build(key: str, digest: str, filename: str) -> str:
        url = reverse(name, kwargs={"key": key, "digest": digest, "filename": filename})
        if signer is None:
            return url
        expires = serving.expires_at(now=now(), window=window)
        signature = signer.sign(key=key, digest=digest, filename=filename, expires=expires)
        return f"{url}?{urlencode({'expires': expires, 'signature': signature})}"

    return build
