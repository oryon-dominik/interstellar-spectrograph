"""Signed URLs expire in fixed windows, so a page hands out one URL for a whole window."""

from datetime import timedelta

import pytest

from spectrograph import serving

WINDOW = timedelta(days=14)
DAY = 86_400


@pytest.mark.parametrize("offset", [0, 1, 7 * DAY, 14 * DAY - 1])
def test_one_window_hands_out_one_expiry(offset: int):
    start = 1_799_712_000 - 1_799_712_000 % int(WINDOW.total_seconds())

    assert serving.expires_at(now=start + offset, window=WINDOW) == serving.expires_at(now=start, window=WINDOW)


@pytest.mark.parametrize("now", [1_799_712_000, 1_800_000_000, 1_800_500_123])
def test_a_url_lives_at_least_one_window_and_at_most_two(now: int):
    remaining = serving.expires_at(now=now, window=WINDOW) - now

    assert 14 * DAY < remaining <= 28 * DAY
