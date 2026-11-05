# spectrograph

One source image, many renditions: slots, `srcset`, cache-forever URLs.

A spectrograph splits one beam of light into its bands and records them. This package
does the same with an image: the original stays untouched, and every place that shows
it — a card, an avatar, a hero — gets renditions at the widths and in the formats it
needs. Full quality stays one URL away.

- **Slots, declared by you.** A slot is a box and the formats it accepts. Each slot
  gets renditions at one, two and three times the width the image shows at; a width
  above 80% of the original's is skipped, because the original serves it better.
  Nothing is ever scaled up.
- **Cache forever.** Every URL carries the digest of the original. When the original
  changes, the URL changes; until then a client never downloads twice.
- **Data, not markup.** The descriptor holds `src`, `srcset`, `sizes`, `width`,
  `height` and the original — render it into `<picture>`, or send it as JSON to a
  client that picks its own size.
- **No trust in the URL.** Only keys you resolve and only renditions the plan names
  are served. No path and no width is read from a URL. The key is: your `resolve`
  receives it raw and must refuse what it does not know.

## Install

Requires Python 3.14 or newer.

```bash
# the core: planning, Pillow, disk store, serve
uv add spectrograph
# plus a view and urlpatterns for Django 6.1 or newer
uv add "spectrograph[django]"
```

## Use with Django

```python
from pathlib import Path

from spectrograph import describe
from spectrograph import django as spectrograph_django
from spectrograph.adapters import pillow
from spectrograph.types import Slot

CARD = Slot(name="card", width=240, height=240, formats=("webp", "png"))
PORTRAITS = Path("portraits")


def portrait(key: str) -> Path | None:
    path = PORTRAITS / f"{key}.png"
    # The key comes from the URL: refuse any that leads out of the folder.
    return path if path.parent == PORTRAITS and path.is_file() else None


urlpatterns = spectrograph_django.urlpatterns(
    prefix="portraits/",
    name="portraits",
    resolve=portrait,
    slots=[CARD],
    store=spectrograph_django.StorageStore(spectrograph_django.AtomicFileSystemStorage(location="renditions")),
    guard=None,  # or guard(request, key), returning a response to refuse the request
)

descriptor = describe.describe(
    key="ada",
    source=pillow.inspect(portrait("ada")),
    slot=CARD,
    url_for=spectrograph_django.url_for(name="portraits"),
)
descriptor._asdict()  # JSON-ready
```

`src` and `srcset` hold one entry per format of the slot:

```html
<picture>
  <source type="image/webp" srcset="{{ srcset.webp }}" sizes="{{ sizes }}">
  <img src="{{ src.png }}" srcset="{{ srcset.png }}" sizes="{{ sizes }}"
       width="{{ width }}" height="{{ height }}" alt="">
</picture>
```

### Storage

Renditions are made on first request and kept in the store under `<digest>/<filename>`;
an original is kept there too, once it is requested. The store only grows: nothing ever
deletes a rendition.

When an original changes, its old URLs answer `404`. A page cached with those URLs shows
broken images until it is rendered again.

Any Django storage works. `AtomicFileSystemStorage` writes through a temporary file, so a
second worker never sends half a rendition; a bucket storage writes whole objects anyway.

`StorageStore(storage, redirect=timedelta(minutes=50))` sends the browser to
`storage.url(name)` instead of streaming. A private bucket hands out a presigned URL
there, so keep `redirect` shorter than that URL's lifetime: it is the `max-age` of the
redirect. The view checks the signature and the guard before redirecting. Once the browser
holds the storage's URL, it reaches the bucket directly, so neither applies to that URL.

`urlpatterns()` raises `ValueError` for an invalid slot.

### Guards

With a guard, the view answers `private, no-cache`, redirects included: no proxy or
content delivery network keeps a guarded image, and the browser asks the guard again
before it shows its copy — answered `304 Not Modified` while that copy is current.

### Signed URLs

Pass one `URLSigner(salt="portraits")` to both `urlpatterns(signer=...)` and
`url_for(name=..., signer=...)`. URLs then carry `?expires=…&signature=…`, signed with
the project's `SECRET_KEY`. A missing, forged or expired signature answers `404` before
the guard runs, so nobody learns whether the image exists.

The expiry jumps in fixed windows (`url_for(window=...)`, 14 days by default): a page hands
out one URL for a whole window, so browser caches hit, and a URL lives at least one window
and at most two. A page carrying signed URLs must not be cached longer than one window.

A signed answer is `private`, so no shared cache outlives its expiry. A browser that
already holds the file keeps its copy; only a guard asks again.

## Without Django

`spectrograph.serving.serve(...)` returns the store name, media type and headers of the
file behind a URL, or `None`. Any framework can wrap it in a few lines. Serving behind
a login, answer `Cache-Control: private, no-cache` instead — shared caches may keep the
answer otherwise, and a browser would show it for a year without asking.

## Behind a web server

Renditions and originals are written with the default file permissions, so nginx or any
other web server can serve the storage's location directly and take the load off Django.
Three things stay yours:

- A file exists only after its first request, so fall back to Django when it is missing.
- The URL carries the key and the store name does not: map
  `<prefix><key>/<digest>/<filename>` to `<digest>/<filename>`.
- Set the `Cache-Control` and `X-Content-Type-Options` headers yourself.

Only without a guard and without a signer: both live in the view, and a web server
reading the files skips them.

## Formats

Renditions in PNG, JPEG, WebP and AVIF — AVIF through Pillow's built-in support.
Originals may also be GIF or TIFF; any other format is refused, never opened. An animated
original renders its first frame.

The original is served byte for byte, metadata included: a phone photo carries its EXIF
block, and with it the place it was taken. Renditions leave EXIF, XMP and comments behind.
Strip what must not travel before `resolve` returns the path.

## Development

```bash
just install-dependencies
just test
just lint
```

## Thanks

The planning idea comes from [django-cast](https://github.com/ephes/django-cast) by
Jochen Wersdörfer: fit into a slot, offer densities one to three, skip what comes too
close to the original, and keep planning apart from rendering. spectrograph carries
the idea without Wagtail.

## Licence

MIT
