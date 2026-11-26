"""Unit tests for the pure timer-display helpers in app/timer_format.py."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.constants import (
    MSG_WRAP_UP_NUDGE,
    MSG_WRAP_UP_NUDGE_ONE,
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
    format_wrap_up_nudge,
    minutes_until,
    parse_end_time,
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


# ---------------------------------------------------------------------------
# format_wrap_up_nudge
# ---------------------------------------------------------------------------


def test_format_wrap_up_nudge_singular_at_one_minute() -> None:
    assert format_wrap_up_nudge(1) == MSG_WRAP_UP_NUDGE_ONE


def test_format_wrap_up_nudge_plural_at_two_minutes() -> None:
    assert format_wrap_up_nudge(2) == MSG_WRAP_UP_NUDGE.format(minutes=2)


def test_format_wrap_up_nudge_plural_at_three_minutes() -> None:
    assert format_wrap_up_nudge(3) == MSG_WRAP_UP_NUDGE.format(minutes=3)


# ---------------------------------------------------------------------------
# parse_end_time / minutes_until (Until… button)
# ---------------------------------------------------------------------------

_LA = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("23:55", (23, 55)),
        ("9:05", (9, 5)),
        ("09:05", (9, 5)),
        ("0905", (9, 5)),
        ("905", (9, 5)),
        ("2355", (23, 55)),
        ("00:15", (0, 15)),
        (" 23:55 ", (23, 55)),
        ("11:55pm", (23, 55)),
        ("11:55 PM", (23, 55)),
        ("1155p.m.", (23, 55)),
        ("12:10am", (0, 10)),
        ("12:10pm", (12, 10)),
        ("9:05am", (9, 5)),
        ("24:00", None),
        ("23:60", None),
        ("13:00pm", None),
        ("0:30am", None),
        ("9", None),
        ("9:5", None),
        ("09055", None),
        ("noon", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_end_time(text: str | None, expected: tuple[int, int] | None) -> None:
    assert parse_end_time(text) == expected


def test_minutes_until_later_today() -> None:
    now = datetime(2026, 11, 25, 23, 20, tzinfo=_LA)
    assert minutes_until(23, 55, now, _LA) == 35


def test_minutes_until_rounds_to_nearest_minute() -> None:
    # 34 min 20 s rounds down; 34 min 40 s rounds up.
    assert (
        minutes_until(23, 55, datetime(2026, 11, 25, 23, 20, 40, tzinfo=_LA), _LA) == 34
    )
    assert (
        minutes_until(23, 55, datetime(2026, 11, 25, 23, 20, 20, tzinfo=_LA), _LA) == 35
    )


def test_minutes_until_past_time_rolls_to_tomorrow() -> None:
    now = datetime(2026, 11, 25, 23, 50, tzinfo=_LA)
    assert minutes_until(0, 15, now, _LA) == 25


def test_minutes_until_same_minute_means_tomorrow() -> None:
    now = datetime(2026, 11, 25, 23, 55, tzinfo=_LA)
    assert minutes_until(23, 55, now, _LA) == 24 * 60


def test_minutes_until_converts_now_into_tz() -> None:
    # 07:20 UTC == 23:20 PST (UTC-8) on 2026-11-25.
    now = datetime(2026, 11, 26, 7, 20, tzinfo=timezone.utc)
    assert minutes_until(23, 55, now, _LA) == 35


def test_minutes_until_across_dst_fall_back() -> None:
    # 2026-11-01 01:30 PDT -> 03:00 PST is 2.5 real hours (01:00–02:00 repeats).
    now = datetime(2026, 11, 1, 1, 30, tzinfo=_LA)  # fold=0 -> PDT
    assert minutes_until(3, 0, now, _LA) == 150


def test_minutes_until_across_dst_spring_forward() -> None:
    # 2026-03-08 01:30 PST -> 03:30 PDT is 1 real hour (02:00–03:00 skipped).
    now = datetime(2026, 3, 8, 1, 30, tzinfo=_LA)
    assert minutes_until(3, 30, now, _LA) == 60
