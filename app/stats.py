"""Pure aggregation and copy-rendering for /stats.

No ``discord`` import — callers pass ``now`` (aware) and ``tz`` in
explicitly, the same way ``app/timer_format.py`` stays Discord-free so it
can be unit tested in isolation with a fixed clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from app.constants import (
    STATS_ROW_7D,
    STATS_ROW_30D,
    STATS_ROW_ALL,
    STATS_ROW_VALUE,
    STATS_ROW_VALUE_NO_RATE,
    STATS_SESSIONS,
    STATS_SESSIONS_ONE,
    STATS_STREAK,
    STATS_STREAK_ONE,
    STATS_WINDOWS_DAYS,
)
from app.db import StatsSessionRow


@dataclass(frozen=True)
class WindowStats:
    """Aggregated stats for one time window."""

    sessions: int
    minutes: int
    rate: int | None  # completion rate as a whole percent, None when undefined


def _parse_started_at(started_at: str) -> datetime:
    """Parse an ISO-8601 (``+00:00``-suffixed) ``started_at`` into an aware datetime."""
    return datetime.fromisoformat(started_at)


def _rows_in_window(
    rows: list[StatsSessionRow],
    *,
    now: datetime,
    window_days: int | None,
) -> list[StatsSessionRow]:
    """Filter *rows* to those started within *window_days* of *now*.

    ``window_days=None`` means all time (no filtering). Rows with no
    ``started_at`` (should not occur for qualifying sessions) are excluded.
    """
    cutoff = None if window_days is None else now - timedelta(days=window_days)
    result = []
    for row in rows:
        if row.started_at is None:
            continue
        started = _parse_started_at(row.started_at)
        if cutoff is None or started >= cutoff:
            result.append(row)
    return result


def compute_window_stats(
    rows: list[StatsSessionRow],
    *,
    now: datetime,
    window_days: int | None,
) -> WindowStats:
    """Aggregate *rows* within *window_days* of *now* into a :class:`WindowStats`.

    Sessions is the row count; focus minutes sums ``duration_minutes``
    (NULL treated as 0); completion rate is
    ✅ count ÷ (✅ + ⛔) count, rounded to a whole percent, or ``None`` when
    that denominator is 0 (no ✅/⛔ answers in the window).
    """
    windowed = _rows_in_window(rows, now=now, window_days=window_days)
    sessions = len(windowed)
    minutes = sum(row.duration_minutes or 0 for row in windowed)
    completed = sum(1 for row in windowed if row.completed_intention == 1)
    answered = sum(1 for row in windowed if row.completed_intention is not None)
    rate = round(100 * completed / answered) if answered > 0 else None
    return WindowStats(sessions=sessions, minutes=minutes, rate=rate)


def compute_stats_summary(
    rows: list[StatsSessionRow],
    *,
    now: datetime,
) -> tuple[WindowStats, WindowStats, WindowStats]:
    """Return (7-day, 30-day, all-time) :class:`WindowStats` for *rows*.

    The 7/30-day window lengths come from :data:`STATS_WINDOWS_DAYS`.
    """
    seven_days, thirty_days = STATS_WINDOWS_DAYS
    return (
        compute_window_stats(rows, now=now, window_days=seven_days),
        compute_window_stats(rows, now=now, window_days=thirty_days),
        compute_window_stats(rows, now=now, window_days=None),
    )


def compute_streak(
    rows: list[StatsSessionRow],
    *,
    now: datetime,
    tz: tzinfo,
) -> int:
    """Return the personal streak: consecutive local calendar days in *tz*.

    A day counts when it has >= 1 qualifying session, and the streak must
    end today or yesterday (local to *tz*) — otherwise it is 0.
    """
    days_with_session = {
        _parse_started_at(row.started_at).astimezone(tz).date()
        for row in rows
        if row.started_at is not None
    }
    today = now.astimezone(tz).date()
    yesterday = today - timedelta(days=1)
    if today in days_with_session:
        cursor = today
    elif yesterday in days_with_session:
        cursor = yesterday
    else:
        return 0

    streak = 0
    while cursor in days_with_session:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------------------
# Rendering — copy assembled only from app.constants strings.
# ---------------------------------------------------------------------------


def render_sessions_text(n: int) -> str:
    """Render the sessions-count fragment: singular for 1, else plural."""
    if n == 1:
        return STATS_SESSIONS_ONE
    return STATS_SESSIONS.format(n=n)


def render_row_value(stats: WindowStats) -> str:
    """Render one window's row value, omitting the rate when undefined."""
    sessions_text = render_sessions_text(stats.sessions)
    if stats.rate is None:
        return STATS_ROW_VALUE_NO_RATE.format(
            sessions=sessions_text, minutes=stats.minutes
        )
    return STATS_ROW_VALUE.format(
        sessions=sessions_text, minutes=stats.minutes, rate=stats.rate
    )


def render_streak_line(streak_days: int) -> str | None:
    """Render the streak line, or ``None`` when it should be hidden (0 days)."""
    if streak_days == 0:
        return None
    if streak_days == 1:
        return STATS_STREAK_ONE
    return STATS_STREAK.format(days=streak_days)


def render_section_value(
    summary: tuple[WindowStats, WindowStats, WindowStats],
    *,
    streak_line: str | None = None,
) -> str:
    """Render an embed field value: one ``{label}: {row value}`` line per window.

    *streak_line*, when given, is appended as a trailing line (used for the
    "You" field only).
    """
    seven, thirty, all_time = summary
    lines = [
        f"{STATS_ROW_7D}: {render_row_value(seven)}",
        f"{STATS_ROW_30D}: {render_row_value(thirty)}",
        f"{STATS_ROW_ALL}: {render_row_value(all_time)}",
    ]
    if streak_line is not None:
        lines.append(streak_line)
    return "\n".join(lines)
