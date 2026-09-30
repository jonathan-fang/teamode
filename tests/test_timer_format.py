"""Unit tests for the pure timer-display helpers in app/timer_format.py."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.constants import (
    NUDGE_MIN_DURATION_MINUTES,
    PHASE_DEEP_FOCUS,
    PHASE_WRAP_UP,
    PROGRESS_BAR_WIDTH,
    WRAP_UP_MINUTES,
)
from app.timer_format import (
    format_hhmm,
    format_mmss,
    format_progress_bar,
    select_phase,
    should_nudge,
)

# ---------------------------------------------------------------------------
# format_mmss
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds_remaining", "expected"),
    [
        (0, "00:00"),
        (5, "00:05"),
        (65, "01:05"),
        (3000, "50:00"),  # long session — minutes exceed 59, no hours field
    ],
)
def test_format_mmss(seconds_remaining: int, expected: str) -> None:
    assert format_mmss(seconds_remaining) == expected


# ---------------------------------------------------------------------------
# format_progress_bar
# ---------------------------------------------------------------------------


def test_progress_bar_at_zero_percent() -> None:
    bar = format_progress_bar(0, 600)
    assert bar == "░" * PROGRESS_BAR_WIDTH + " 0%"


def test_progress_bar_at_fifty_percent() -> None:
    bar = format_progress_bar(300, 600)
    filled = PROGRESS_BAR_WIDTH // 2
    assert bar == "█" * filled + "░" * (PROGRESS_BAR_WIDTH - filled) + " 50%"


def test_progress_bar_at_hundred_percent() -> None:
    bar = format_progress_bar(600, 600)
    assert bar == "█" * PROGRESS_BAR_WIDTH + " 100%"


def test_progress_bar_non_integer_ratio() -> None:
    """1/3 elapsed at width 10 floors to 3 filled cells and 33%."""
    bar = format_progress_bar(200, 600, width=10)
    assert bar == "███░░░░░░░ 33%"


def test_progress_bar_clamps_out_of_range_elapsed() -> None:
    """Elapsed past total (a slightly-late final tick) clamps to 100%."""
    assert format_progress_bar(700, 600) == format_progress_bar(600, 600)
    assert format_progress_bar(-10, 600) == format_progress_bar(0, 600)


def test_progress_bar_guards_zero_total() -> None:
    """A degenerate total_seconds <= 0 renders an empty bar at 0% rather
    than raising ZeroDivisionError."""
    assert format_progress_bar(0, 0) == "░" * PROGRESS_BAR_WIDTH + " 0%"


# ---------------------------------------------------------------------------
# select_phase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("duration_minutes", [5, 10, 25, 50])
def test_phase_switches_exactly_at_wrap_up_boundary(duration_minutes: int) -> None:
    trigger = WRAP_UP_MINUTES * 60
    # One second before the trigger: still Deep focus (only when the
    # session is long enough to have a "before" at all).
    if duration_minutes * 60 > trigger:
        assert select_phase(trigger + 1) == PHASE_DEEP_FOCUS
    # At and after the trigger: Wrap up.
    assert select_phase(trigger) == PHASE_WRAP_UP
    assert select_phase(trigger - 1) == PHASE_WRAP_UP
    assert select_phase(0) == PHASE_WRAP_UP


# ---------------------------------------------------------------------------
# format_hhmm
# ---------------------------------------------------------------------------


def test_format_hhmm_converts_to_target_timezone() -> None:
    # 2026-01-15 23:30 UTC == 2026-01-15 15:30 America/Los_Angeles (PST, UTC-8).
    dt = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    assert format_hhmm(dt, ZoneInfo("America/Los_Angeles")) == "15:30"


# ---------------------------------------------------------------------------
# should_nudge
# ---------------------------------------------------------------------------


def test_should_nudge_true_only_at_trigger_for_long_session() -> None:
    duration = max(NUDGE_MIN_DURATION_MINUTES, WRAP_UP_MINUTES + 1)
    trigger = WRAP_UP_MINUTES * 60
    assert should_nudge(duration, trigger) is True
    assert should_nudge(duration, trigger + 1) is False
    assert should_nudge(duration, trigger - 1) is False


def test_should_nudge_false_for_too_short_duration() -> None:
    short_duration = max(1, NUDGE_MIN_DURATION_MINUTES - 1)
    trigger = WRAP_UP_MINUTES * 60
    assert should_nudge(short_duration, trigger) is False


def test_should_nudge_false_when_trigger_not_before_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duration whose total length doesn't exceed the trigger point never
    nudges — there is no "before wrap-up" phase to nudge into. Exercised
    directly against the trigger/total relationship, independent of the
    current NUDGE_MIN_DURATION_MINUTES value, since real duration buttons
    may not otherwise reach this edge."""
    import app.timer_format as timer_format_module

    monkeypatch.setattr(timer_format_module, "NUDGE_MIN_DURATION_MINUTES", 1)
    trigger_seconds = WRAP_UP_MINUTES * 60
    duration_minutes = WRAP_UP_MINUTES  # total_seconds == trigger_seconds
    assert should_nudge(duration_minutes, trigger_seconds) is False
