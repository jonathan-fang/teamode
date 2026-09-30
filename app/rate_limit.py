"""In-memory per-user and per-guild rate limiting for /teamode invocations.

Pure logic — no ``discord`` import — with injectable clocks so tests never
wait on real time. State resets on process restart; that is accepted (see
Task Prompt).

Two independent limits:

- **Per-user sliding window**: each user may make ``RATE_LIMIT_ALLOWANCE``
  counted invocations per ``RATE_LIMIT_WINDOW_SECONDS``. The window slides —
  once the oldest counted call ages out of the window, a new call is
  allowed again. Backed by ``time.monotonic`` (injectable).
- **Per-guild daily cap**: ``GUILD_DAILY_CAP`` counted invocations per guild
  per *local calendar day*, where "local" means the configured timezone
  (``app.config.TEAMODE_TIMEZONE``). Backed by an aware ``datetime.now(tz)``
  clock (injectable) so the boundary is midnight in that timezone, not UTC.

Only an *allowed* call is recorded — a refused call must not extend the
user's window or consume the guild's daily cap.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from math import ceil

from app.constants import (
    GUILD_DAILY_CAP,
    RATE_LIMIT_ALLOWANCE,
    RATE_LIMIT_WINDOW_SECONDS,
)


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a rate-limit check.

    ``allowed`` is False when the call was refused. ``reason`` distinguishes
    which limit refused it (``"user"`` or ``"guild"``); ``retry_after_seconds``
    is populated only for a user refusal (seconds until the oldest counted
    call ages out of the window, rounded up, minimum 1).
    """

    allowed: bool
    reason: str | None = None
    retry_after_seconds: int | None = None


class RateLimiter:
    """Tracks per-user sliding-window and per-guild daily-cap invocation counts.

    Check order (documented decision): the per-user limit is checked first,
    then the per-guild limit. A user refusal never touches the guild cap,
    and a guild refusal never touches the user's window — only a call that
    passes *both* checks is recorded against *both* counters.
    """

    def __init__(
        self,
        tz: tzinfo,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._tz = tz
        self._monotonic = monotonic
        self._now = now
        # user_id -> deque of monotonic timestamps of counted calls, oldest first.
        self._user_calls: dict[str, deque[float]] = defaultdict(deque)
        # guild_id -> (local_date_isoformat, count) for the current day's tally.
        self._guild_calls: dict[str, tuple[str, int]] = {}

    def check_and_record(self, user_id: str, guild_id: str) -> RateLimitResult:
        """Check both limits for this call and record it if allowed.

        Per-user check runs first; a user refusal returns immediately
        without touching the guild cap. Only a call that clears both
        checks is recorded.
        """
        user_result = self._check_user(user_id)
        if not user_result.allowed:
            return user_result

        guild_result = self._check_guild(guild_id)
        if not guild_result.allowed:
            return guild_result

        # Both checks passed — record against both counters.
        self._user_calls[user_id].append(self._monotonic())
        self._record_guild(guild_id)
        return RateLimitResult(allowed=True)

    def _check_user(self, user_id: str) -> RateLimitResult:
        now = self._monotonic()
        calls = self._user_calls[user_id]

        # Drop calls that have aged out of the window.
        while calls and now - calls[0] >= RATE_LIMIT_WINDOW_SECONDS:
            calls.popleft()

        if len(calls) < RATE_LIMIT_ALLOWANCE:
            return RateLimitResult(allowed=True)

        oldest = calls[0]
        retry_after = ceil(RATE_LIMIT_WINDOW_SECONDS - (now - oldest))
        retry_after = max(retry_after, 1)
        return RateLimitResult(
            allowed=False, reason="user", retry_after_seconds=retry_after
        )

    def _check_guild(self, guild_id: str) -> RateLimitResult:
        today = self._now().astimezone(self._tz).date().isoformat()
        stored_date, count = self._guild_calls.get(guild_id, (today, 0))

        if stored_date != today:
            # Day rolled over — the stored tally no longer applies.
            count = 0

        if count < GUILD_DAILY_CAP:
            return RateLimitResult(allowed=True)

        return RateLimitResult(allowed=False, reason="guild")

    def _record_guild(self, guild_id: str) -> None:
        today = self._now().astimezone(self._tz).date().isoformat()
        stored_date, count = self._guild_calls.get(guild_id, (today, 0))
        if stored_date != today:
            count = 0
        self._guild_calls[guild_id] = (today, count + 1)
