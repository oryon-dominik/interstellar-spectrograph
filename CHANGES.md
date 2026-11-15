# spectrograph Changelog

---

## [2026.11.1](https://github.com/oryon-dominik/interstellar-spectrograph/compare/2026.11.0..2026.11.1) - 2026-11-15

### Django

#### Bug Fixes

- **(django)** a signed URL whose expiry overflows int() answers 404 — it raised a server error - ([2a1edd8](https://github.com/oryon-dominik/interstellar-spectrograph/commit/2a1edd8f2270ee889e9fb8a1722c56efd51d26df))



### Planning

#### Bug Fixes

- **(planning)** slots share one full-width rendition — each made its own copy of the same bytes - ([74f8f0f](https://github.com/oryon-dominik/interstellar-spectrograph/commit/74f8f0fa430493699702357ab76aa53d2fbd89f2))



### Pyproject

#### Features

- **(pyproject)** [**breaking**] the package installs as cyberise-spectrograph — the index refuses the bare name - ([f604746](https://github.com/oryon-dominik/interstellar-spectrograph/commit/f6047464b2924e29b99061497cd0d7247d49e579))



### Serving

#### Features

- **(serving)** render each file once per worker, bounded, or ahead with warm — first requests pile up - ([e5c214e](https://github.com/oryon-dominik/interstellar-spectrograph/commit/e5c214e1221d39416a91874eac0c8aad6e314314))



### Slots

#### Features

- **(slots)** [**breaking**] originals stay home unless a slot offers them — they carry EXIF, place included - ([dce5806](https://github.com/oryon-dominik/interstellar-spectrograph/commit/dce5806346122447416ce533f00183f5d1138b44))




---

## [2026.11.0] - 2026-11-05

### Spectrograph

#### Features

- **(spectrograph)** one source image, many renditions — slots, srcset, cache-forever URLs - ([4a19ba7](https://github.com/oryon-dominik/interstellar-spectrograph/commit/4a19ba735cac567b898e15858f32972596fb3ee2))
