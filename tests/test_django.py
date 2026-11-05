from datetime import timedelta
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponseForbidden
from django.test import RequestFactory
from django.urls import resolve as resolve_url
from django.urls import set_urlconf

from spectrograph import django as spectrograph_django
from spectrograph.adapters import pillow
from spectrograph.types import Slot

CARD = Slot(name="card", width=240, height=240, formats=("png",))
urlpatterns: list = []


@pytest.fixture(autouse=True)
def unmounted():
    """Route through this module, and clear what a test mounted even when its request failed."""
    set_urlconf(__name__)
    yield
    urlpatterns.clear()
    set_urlconf(None)


@pytest.fixture
def mounted(portrait: Path, tmp_path: Path):
    """The portrait of `athena` mounted under /portraits/, refusing requests without the token for that key."""

    def guard(request, key):
        return None if request.headers.get("Authorization") == f"Bearer {key}" else HttpResponseForbidden()

    urlpatterns[:] = spectrograph_django.urlpatterns(
        prefix="portraits/",
        name="portraits",
        resolve={"athena": portrait}.get,
        slots=[CARD],
        store=renditions(tmp_path),
        guard=guard,
    )
    return pillow.inspect(portrait)


def renditions(tmp_path: Path) -> spectrograph_django.StorageStore:
    """The storage store the project would mount, kept under tmp_path/renditions."""
    storage = spectrograph_django.AtomicFileSystemStorage(location=tmp_path / "renditions")
    return spectrograph_django.StorageStore(storage)


def fetch(path: str, *, method: str = "get", **headers):
    request = getattr(RequestFactory(), method)(path, headers=headers)
    match = resolve_url(path.partition("?")[0])
    return match.func(request, **match.kwargs)


def test_behind_a_guard_the_browser_asks_again_before_it_shows_its_copy(mounted):
    """A revoked user must not keep seeing the image from the browser cache."""
    response = fetch(f"/portraits/athena/{mounted.digest}/card-240.png", Authorization="Bearer athena")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "private, no-cache"
    assert response["ETag"] == f'"{mounted.digest}-card-240.png"'
    assert b"".join(response.streaming_content).startswith(b"\x89PNG")


def test_a_copy_the_browser_still_holds_is_confirmed_without_sending_it_again(mounted):
    path = f"/portraits/athena/{mounted.digest}/card-240.png"
    etag = fetch(path, Authorization="Bearer athena")["ETag"]

    response = fetch(path, Authorization="Bearer athena", **{"If-None-Match": etag})

    assert response.status_code == 304
    assert response["ETag"] == etag
    assert response["Cache-Control"] == "private, no-cache"


def test_the_guard_refuses_a_revoked_user_even_with_a_copy_in_hand(mounted):
    path = f"/portraits/athena/{mounted.digest}/card-240.png"
    etag = fetch(path, Authorization="Bearer athena")["ETag"]

    assert fetch(path, **{"If-None-Match": etag}).status_code == 403


def test_a_broken_slot_fails_when_it_is_mounted_not_on_every_request(portrait: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="card"):
        spectrograph_django.urlpatterns(
            prefix="portraits/",
            name="portraits",
            resolve={"athena": portrait}.get,
            slots=[CARD._replace(formats=("jpg",))],
            store=renditions(tmp_path),
        )


@pytest.mark.parametrize("filename", ["card-240.png", "original.png"])
def test_a_download_is_named_after_the_key_not_the_file_on_disk(mounted, filename: str):
    """Saving the image suggests a name the URL already shows — never how the host stores it."""
    response = fetch(f"/portraits/athena/{mounted.digest}/{filename}", Authorization="Bearer athena")

    assert response["Content-Disposition"] == f'inline; filename="athena-{filename}"'


@pytest.mark.parametrize("token", [None, "Bearer hermes"])
def test_the_guard_refuses_before_anything_is_served(mounted, tmp_path: Path, token: str | None):
    headers = {"Authorization": token} if token else {}
    response = fetch(f"/portraits/athena/{mounted.digest}/card-240.png", **headers)

    assert response.status_code == 403
    assert not (tmp_path / "renditions").exists()


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_only_reading_methods_are_answered(mounted, method: str):
    response = fetch(f"/portraits/athena/{mounted.digest}/card-240.png", method=method, Authorization="Bearer athena")

    assert response.status_code == 405


def test_a_stale_url_is_not_found(mounted):
    with pytest.raises(Http404):
        fetch("/portraits/athena/fedcba9876543210/card-240.png", Authorization="Bearer athena")


def test_url_for_builds_the_urls_describe_needs(mounted):
    url_for = spectrograph_django.url_for(name="portraits")

    assert url_for("athena", mounted.digest, "card-240.png") == f"/portraits/athena/{mounted.digest}/card-240.png"


def test_without_a_guard_shared_caches_may_keep_the_answer(portrait: Path, tmp_path: Path):
    urlpatterns[:] = spectrograph_django.urlpatterns(
        prefix="portraits/",
        name="portraits",
        resolve={"athena": portrait}.get,
        slots=[CARD],
        store=renditions(tmp_path),
    )

    response = fetch(f"/portraits/athena/{pillow.inspect(portrait).digest}/card-240.png")

    assert response["Cache-Control"] == "max-age=31536000, immutable"


def test_a_reader_never_sees_half_a_rendition(tmp_path: Path):
    """While the rendition is being written, its name stays absent — then it appears whole."""
    storage = spectrograph_django.AtomicFileSystemStorage(location=tmp_path)
    seen_mid_write = []

    class Halves(ContentFile):
        def chunks(self, chunk_size=None):
            yield b"first half "
            seen_mid_write.append(storage.exists("0123456789abcdef/card-240.png"))
            yield b"second half"

    storage.save("0123456789abcdef/card-240.png", Halves(b""))

    assert seen_mid_write == [False]
    assert (tmp_path / "0123456789abcdef" / "card-240.png").read_bytes() == b"first half second half"


def test_two_writers_of_one_rendition_leave_one_file(tmp_path: Path):
    """The storage hands the second writer a fresh name; the store drops that copy."""
    store = renditions(tmp_path)

    store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")
    store.put(digest="0123456789abcdef", filename="card-240.png", data=b"pixels")

    assert [path.name for path in (tmp_path / "renditions" / "0123456789abcdef").iterdir()] == ["card-240.png"]


@pytest.fixture
def signed(portrait: Path, tmp_path: Path):
    """The portrait mounted with a signer and a guard that lets everyone through."""
    signer = spectrograph_django.URLSigner(salt="portraits")
    urlpatterns[:] = spectrograph_django.urlpatterns(
        prefix="portraits/",
        name="portraits",
        resolve={"athena": portrait}.get,
        slots=[CARD],
        store=renditions(tmp_path),
        signer=signer,
        guard=lambda request, key: None,
    )
    return signer, pillow.inspect(portrait)


def test_a_signed_url_from_url_for_is_served(signed):
    signer, source = signed
    url = spectrograph_django.url_for(name="portraits", signer=signer)("athena", source.digest, "card-240.png")

    response = fetch(url)

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-cache"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?expires=1800000000",
        "?expires=1800000000&signature=forged",
        "?expires=soon&signature=forged",
        "?expires=²&signature=forged",
    ],
)
def test_an_unsigned_or_forged_url_is_not_found(signed, query: str):
    _, source = signed

    with pytest.raises(Http404):
        fetch(f"/portraits/athena/{source.digest}/card-240.png{query}")


def test_an_expired_url_is_not_found_though_its_signature_holds(signed):
    signer, source = signed
    expires = 1_000_000_000
    signature = signer.sign(key="athena", digest=source.digest, filename="card-240.png", expires=expires)

    with pytest.raises(Http404):
        fetch(f"/portraits/athena/{source.digest}/card-240.png?expires={expires}&signature={signature}")


def test_the_signature_is_checked_before_the_guard(portrait: Path, tmp_path: Path):
    """No answer may tell an outsider whether the image exists — not even a 403."""
    asked = []
    urlpatterns[:] = spectrograph_django.urlpatterns(
        prefix="portraits/",
        name="portraits",
        resolve={"athena": portrait}.get,
        slots=[CARD],
        store=renditions(tmp_path),
        signer=spectrograph_django.URLSigner(salt="portraits"),
        guard=lambda request, key: asked.append(key),
    )

    with pytest.raises(Http404):
        fetch(f"/portraits/athena/{pillow.inspect(portrait).digest}/card-240.png")

    assert asked == []


def test_url_for_without_a_signer_builds_the_plain_url(mounted):
    assert "?" not in spectrograph_django.url_for(name="portraits")("athena", mounted.digest, "card-240.png")


def bucket(tmp_path: Path, *, redirect: timedelta | None) -> spectrograph_django.StorageStore:
    """A storage with a URL of its own, as a bucket hands out — here the file system behind a fake host."""
    storage = spectrograph_django.AtomicFileSystemStorage(
        location=tmp_path / "bucket", base_url="https://bucket.test/"
    )
    return spectrograph_django.StorageStore(storage, redirect=redirect)


def mount_bucket(portrait: Path, tmp_path: Path, **options) -> str:
    urlpatterns[:] = spectrograph_django.urlpatterns(
        prefix="portraits/",
        name="portraits",
        resolve={"athena": portrait}.get,
        slots=[CARD],
        store=bucket(tmp_path, redirect=timedelta(minutes=50)),
        **options,
    )
    return pillow.inspect(portrait).digest


def test_a_store_with_redirect_sends_the_browser_to_the_storage_url(portrait: Path, tmp_path: Path):
    """The bucket serves the bytes; the redirect may be kept no longer than the storage's own URL lives."""
    digest = mount_bucket(portrait, tmp_path)

    response = fetch(f"/portraits/athena/{digest}/card-240.png")

    assert response.status_code == 302
    assert response["Location"] == f"https://bucket.test/{digest}/card-240.png"
    assert response["Cache-Control"] == "private, max-age=3000"


def test_the_redirect_comes_only_after_signature_and_guard(portrait: Path, tmp_path: Path):
    digest = mount_bucket(portrait, tmp_path, guard=lambda request, key: HttpResponseForbidden())

    assert fetch(f"/portraits/athena/{digest}/card-240.png").status_code == 403

    mount_bucket(portrait, tmp_path, signer=spectrograph_django.URLSigner(salt="portraits"))

    with pytest.raises(Http404):
        fetch(f"/portraits/athena/{digest}/card-240.png")


def test_a_guarded_redirect_asks_the_guard_again(portrait: Path, tmp_path: Path):
    """A browser that kept the redirect would skip the guard, and a revoked user with it."""
    digest = mount_bucket(portrait, tmp_path, guard=lambda request, key: None)

    response = fetch(f"/portraits/athena/{digest}/card-240.png")

    assert response.status_code == 302
    assert response["Cache-Control"] == "private, no-cache"


def test_a_signed_answer_stays_out_of_shared_caches(portrait: Path, tmp_path: Path):
    """A shared cache would keep answering after the signature has expired."""
    signer = spectrograph_django.URLSigner(salt="portraits")
    urlpatterns[:] = spectrograph_django.urlpatterns(
        prefix="portraits/",
        name="portraits",
        resolve={"athena": portrait}.get,
        slots=[CARD],
        store=renditions(tmp_path),
        signer=signer,
    )
    source = pillow.inspect(portrait)
    url = spectrograph_django.url_for(name="portraits", signer=signer)("athena", source.digest, "card-240.png")

    response = fetch(url)

    assert response["Cache-Control"] == "private, max-age=31536000, immutable"
