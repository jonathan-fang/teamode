"""Pure timer-display formatting: MM:SS, progress bar, phase, HH:MM, nudge trigger.

No ``discord`` import and no ``app.config`` import — callers pass a ``tzinfo``
in explicitly (``format_hhmm``) so this module stays unit-testable in
isolation, the same way ``app/session.py`` stays Discord-free.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo

from app.constants import (
    MSG_WRAP_UP_NUDGE,
    MSG_WRAP_UP_NUDGE_ONE,
    NUDGE_MIN_DURATION_MINUTES,
    PHASE_DEEP_FOCUS,
    PHASE_WRAP_UP,
    PROGRESS_BAR_WIDTH,
    TIMER_PROGRESS,
    WRAP_UP_MINUTES,
)

_PROGRESS_FILLED = "█"
_PROGRESS_EMPTY = "░"


def format_mmss(seconds_remaining: int) -> str:
    """Format *seconds_remaining* as zero-padded ``MM:SS``.

    Minutes are not capped at 59 — a long session (e.g. 50 min) renders as
    ``50:00``, not wrapping into an hours field.
    """
    minutes, seconds = divmod(seconds_remaining, 60)
    return f"{minutes:02d}:{seconds:02d}"


def format_progress_bar(
    elapsed_seconds: int, total_seconds: int, width: int = PROGRESS_BAR_WIDTH
) -> str:
    """Render an elapsed-time progress bar via :data:`TIMER_PROGRESS`.

    Progress is the **elapsed** fraction — the bar fills as time passes, so
    a full bar / 100% appears only once the session ends. *elapsed_seconds*
    is clamped to ``[0, total_seconds]`` so a slightly-early or slightly-late
    caller never produces a negative or overflowing bar. ``total_seconds <=
    0`` is guarded (degenerate/misconfigured duration) and renders an empty
    bar at 0%.
    """
    if total_seconds <= 0:
        filled = 0
        percent = 0
    else:
        clamped = max(0, min(elapsed_seconds, total_seconds))
        filled = (width * clamped) // total_seconds
        percent = (100 * clamped) // total_seconds

    bar = _PROGRESS_FILLED * filled + _PROGRESS_EMPTY * (width - filled)
    return TIMER_PROGRESS.format(bar=bar, percent=percent)


def select_phase(seconds_remaining: int) -> str:
    """Return the active phase label for *seconds_remaining* left.

    Wrap up starts at ``WRAP_UP_MINUTES * 60`` seconds remaining (inclusive)
    and holds through 0, for every duration — including a session shorter
    than double the wrap-up window, which is briefly Deep focus before
    immediately entering Wrap up.
    """
    if seconds_remaining <= WRAP_UP_MINUTES * 60:
        return PHASE_WRAP_UP
    return PHASE_DEEP_FOCUS


def format_hhmm(dt: datetime, tz: tzinfo) -> str:
    """Format *dt* as 24-hour ``HH:MM`` local to *tz*."""
    return dt.astimezone(tz).strftime("%H:%M")


def should_nudge(duration_minutes: int, seconds_remaining: int) -> bool:
    """Return whether the one-time wrap-up nudge should fire now.

    True exactly when *seconds_remaining* hits the wrap-up trigger
    (``WRAP_UP_MINUTES * 60``) for a session long enough to have a Deep
    focus phase before it (``duration_minutes >= NUDGE_MIN_DURATION_MINUTES``
    and the trigger point is strictly before the session's total length —
    guards a duration shorter than or equal to the trigger, which would
    otherwise fire the nudge at, or before, the very start).
    """
    trigger_seconds = WRAP_UP_MINUTES * 60
    total_seconds = duration_minutes * 60
    if duration_minutes < NUDGE_MIN_DURATION_MINUTES:
        return False
    if trigger_seconds >= total_seconds:
        return False
    return seconds_remaining == trigger_seconds


def format_wrap_up_nudge(minutes: int) -> str:
    """Return the wrap-up nudge message for *minutes* left.

    Singular copy (:data:`MSG_WRAP_UP_NUDGE_ONE`) for exactly 1 minute,
    plural (:data:`MSG_WRAP_UP_NUDGE`) for 2 or more.
    """
    if minutes == 1:
        return MSG_WRAP_UP_NUDGE_ONE
    return MSG_WRAP_UP_NUDGE.format(minutes=minutes)


_END_TIME_RE = re.compile(
    r"^(?:(?P<h>\d{1,2}):(?P<m>\d{2})|(?P<hc>\d{1,2})(?P<mc>\d{2}))"
    r"\s*(?P<ampm>[ap]\.?m\.?)?$"
)


def parse_end_time(text: str | None) -> tuple[int, int] | None:
    """Parse a wall-clock end time into ``(hour, minute)`` (24-hour), or ``None``.

    Accepts ``23:55``, ``9:05``, ``09:05``, ``0905``, ``905`` and 12-hour
    forms with an am/pm suffix (``11:55pm``, ``11:55 PM``, ``1155p.m.``).
    With am/pm the hour must be 1–12; without, 0–23.
    """
    match = _END_TIME_RE.match((text or "").strip().lower())
    if match is None:
        return None
    hour = int(match["h"] or match["hc"])
    minute = int(match["m"] or match["mc"])
    if minute > 59:
        return None
    ampm = match["ampm"]
    if ampm is None:
        return (hour, minute) if hour <= 23 else None
    if not 1 <= hour <= 12:
        return None
    hour %= 12
    if ampm.startswith("p"):
        hour += 12
    return hour, minute


def minutes_until(hour: int, minute: int, now: datetime, tz: tzinfo) -> int:
    """Whole minutes (rounded to nearest) from *now* until the next ``hour:minute``
    wall-clock time in *tz*.

    A time at or before *now* means tomorrow. The gap is measured in UTC so a
    DST transition in between is accounted for.
    """
    local_now = now.astimezone(tz)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target = (target.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=tz)
    delta = target.astimezone(timezone.utc) - local_now.astimezone(timezone.utc)
    return round(delta.total_seconds() / 60)
