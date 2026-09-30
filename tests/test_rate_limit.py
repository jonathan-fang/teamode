"""Tests for app.rate_limit — per-user sliding window and per-guild daily cap."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.constants import GUILD_DAILY_CAP
from app.rate_limit import RateLimiter


class FakeMonotonic:
    """A controllable stand-in for time.monotonic."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


class FakeNow:
    """A controllable stand-in for a clock returning an aware datetime."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


# ---------------------------------------------------------------------------
# Per-user sliding window
# ---------------------------------------------------------------------------


def test_user_allows_up_to_allowance_within_window() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    for _ in range(3):
        result = limiter.check_and_record(user_id="u1", guild_id="g1")
        assert result.allowed is True


def test_user_fourth_call_refused_with_seconds_remaining() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    limiter.check_and_record(user_id="u1", guild_id="g1")  # t=0
    clock.value = 10
    limiter.check_and_record(user_id="u1", guild_id="g1")  # t=10
    clock.value = 20
    limiter.check_and_record(user_id="u1", guild_id="g1")  # t=20

    clock.value = 25
    result = limiter.check_and_record(user_id="u1", guild_id="g1")

    assert result.allowed is False
    assert result.reason == "user"
    # Oldest call (t=0) ages out at t=300; now t=25 -> 275 seconds remaining.
    assert result.retry_after_seconds == 275


def test_user_window_slides_once_oldest_ages_out() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    limiter.check_and_record(user_id="u1", guild_id="g1")  # t=0
    clock.value = 1
    limiter.check_and_record(user_id="u1", guild_id="g1")  # t=1
    clock.value = 2
    limiter.check_and_record(user_id="u1", guild_id="g1")  # t=2

    clock.value = 5
    refused = limiter.check_and_record(user_id="u1", guild_id="g1")
    assert refused.allowed is False

    # Advance past the window for the oldest call (t=0 ages out at t=300).
    clock.value = 301
    allowed_again = limiter.check_and_record(user_id="u1", guild_id="g1")
    assert allowed_again.allowed is True


def test_refused_user_call_does_not_extend_window() -> None:
    """A refusal must not be recorded — it shouldn't consume a slot."""
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    for _ in range(3):
        limiter.check_and_record(user_id="u1", guild_id="g1")

    clock.value = 10
    refused = limiter.check_and_record(user_id="u1", guild_id="g1")
    assert refused.allowed is False

    # Advance just past the original window boundary (t=0 ages out at 300).
    clock.value = 300.5
    allowed = limiter.check_and_record(user_id="u1", guild_id="g1")
    assert allowed.allowed is True


def test_user_refusal_does_not_consume_guild_cap() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    for _ in range(3):
        limiter.check_and_record(user_id="u1", guild_id="g1")
    refused = limiter.check_and_record(user_id="u1", guild_id="g1")
    assert refused.allowed is False

    # The guild cap already holds u1's 3 successful calls. The remaining
    # allowance (cap - 3) must still be fully available to other users —
    # proving the refused 4th call above was never counted against it.
    for i in range(GUILD_DAILY_CAP - 3):
        result = limiter.check_and_record(user_id=f"other-{i}", guild_id="g1")
        assert result.allowed is True

    # And the cap is now genuinely exhausted at exactly GUILD_DAILY_CAP.
    exhausted = limiter.check_and_record(user_id="one-more", guild_id="g1")
    assert exhausted.allowed is False


# ---------------------------------------------------------------------------
# Per-guild daily cap
# ---------------------------------------------------------------------------


def test_guild_allows_up_to_daily_cap() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    for i in range(GUILD_DAILY_CAP):
        # Distinct users so the per-user limit never trips.
        result = limiter.check_and_record(user_id=f"u{i}", guild_id="g1")
        assert result.allowed is True


def test_guild_fifty_first_call_refused() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    for i in range(GUILD_DAILY_CAP):
        limiter.check_and_record(user_id=f"u{i}", guild_id="g1")

    result = limiter.check_and_record(user_id="uNext", guild_id="g1")
    assert result.allowed is False
    assert result.reason == "guild"


def test_guild_refusal_does_not_consume_user_allowance() -> None:
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    limiter = RateLimiter(tz=ZoneInfo("UTC"), monotonic=clock, now=now)

    for i in range(GUILD_DAILY_CAP):
        limiter.check_and_record(user_id=f"u{i}", guild_id="g1")

    refused = limiter.check_and_record(user_id="uNext", guild_id="g1")
    assert refused.allowed is False

    # uNext's own per-user window must still be fully available.
    for _ in range(3):
        result = limiter.check_and_record(user_id="uNext", guild_id="g2")
        assert result.allowed is True


def test_guild_cap_resets_at_local_midnight_non_utc_zone() -> None:
    """The day boundary is local midnight, not UTC midnight.

    23:59 America/Los_Angeles on 2026-01-01 is 07:59 UTC on 2026-01-02 —
    the UTC date has already rolled over while the LA date has not. Then
    00:01 America/Los_Angeles on 2026-01-02 is a genuine new local day and
    must reset the cap, proving the local date (not the UTC date) governs
    the boundary.
    """
    tz = ZoneInfo("America/Los_Angeles")
    clock = FakeMonotonic()
    now = FakeNow(datetime(2026, 1, 1, 23, 59, tzinfo=tz))
    limiter = RateLimiter(tz=tz, monotonic=clock, now=now)

    for i in range(GUILD_DAILY_CAP):
        limiter.check_and_record(user_id=f"u{i}", guild_id="g1")

    # Still 2026-01-01 locally — cap is exhausted.
    refused = limiter.check_and_record(user_id="uNext", guild_id="g1")
    assert refused.allowed is False

    # Advance two minutes of wall-clock time to 00:01 local on 2026-01-02 —
    # a new local calendar day.
    now.value = datetime(2026, 1, 2, 0, 1, tzinfo=tz)
    allowed = limiter.check_and_record(user_id="uNext", guild_id="g1")
    assert allowed.allowed is True
