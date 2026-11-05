"""Configure Django once for the whole run — the port contract and the view tests both reach a storage."""

import django
from django.conf import settings

if not settings.configured:
    settings.configure(ALLOWED_HOSTS=["testserver"], SECRET_KEY="spectrograph-tests")  # noqa: S106 — the signer tests need a key, this one signs nothing real
    django.setup()
