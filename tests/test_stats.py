"""Tests for /stats: db read helpers, pure aggregation, and the command.

Covers: only completed/followup_timeout rows count, 7d/30d/all-time window
filtering, completion rate (undefined when no ✅/⛔ answers), singular
sessions/streak copy, streak hidden at 0, streak counts consecutive local
days (including a UTC-midnight-crossing case) ending today or yesterday,
"You" uses the original facilitator_id (never handoff_facilitator_id),
"This server" filters by guild_id, empty data renders STATS_EMPTY, and the
command responds ephemerally with a STATS_TITLE embed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
import pytest

from app.constants import (
    MSG_WRONG_CHANNEL,
    STATS_EMPTY,
    STATS_ROW_VALUE,
    STATS_ROW_VALUE_NO_RATE,
    STATS_SECTION_SERVER,
    STATS_SECTION_YOU,
    STATS_STREAK,
    STATS_STREAK_ONE,
    STATS_TITLE,
)
from app.db import (
    fetch_facilitator_stats_rows,
    fetch_guild_stats_rows,
    init_db,
    insert_pending_session,
    update_completed,
    update_duration,
    update_followup_timeout,
    update_handoff_facilitator,
    update_started_at_active,
    update_to_followup,
)
from app.discord_bot import TeaModeBot
from app.session import SessionRegistry
from app.stats import (
    compute_stats_summary,
    compute_streak,
    render_row_value,
    render_sessions_text,
    render_streak_line,
)

# ---------------------------------------------------------------------------
# Fixtures / seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn() -> sqlite3.Connection:
    return init_db(":memory:")


def _seed(
    conn: sqlite3.Connection,
    *,
    guild_id: str = "111",
    facilitator_id: str = "222",
    status: str,
    started_at: str,
    duration_minutes: int | None = 25,
    completed_intention: int | None = 1,
    handoff_facilitator_id: str | None = None,
) -> int:
    """Insert a session row and drive it to *status* with the given fields."""
    session_id = insert_pending_session(
        conn,
        guild_id=guild_id,
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id=facilitator_id,
    )
    if duration_minutes is not None:
        update_duration(conn, session_id=session_id, duration_minutes=duration_minutes)
    update_started_at_active(conn, session_id=session_id, started_at=started_at)
    if handoff_facilitator_id is not None:
        update_handoff_facilitator(
            conn, session_id=session_id, handoff_facilitator_id=handoff_facilitator_id
        )

    if status == "completed":
        update_to_followup(conn, session_id=session_id)
        update_completed(
            conn,
            session_id=session_id,
            completed_intention=completed_intention
            if completed_intention is not None
            else 0,
            followup_note=None,
        )
        if completed_intention is None:
            conn.execute(
                "UPDATE sessions SET completed_intention = NULL WHERE id = ?",
                (session_id,),
            )
            conn.commit()
    elif status == "followup_timeout":
        update_to_followup(conn, session_id=session_id)
        update_followup_timeout(conn, session_id=session_id)
    elif status == "cancelled":
        conn.execute(
            "UPDATE sessions SET status = 'cancelled' WHERE id = ?", (session_id,)
        )
        conn.commit()
    elif status == "pending":
        pass
    elif status == "active":
        pass
    elif status == "crashed":
        conn.execute(
            "UPDATE sessions SET status = 'crashed' WHERE id = ?", (session_id,)
        )
        conn.commit()
    else:
        raise ValueError(f"unexpected status {status!r}")

    return session_id


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# db read helpers
# ---------------------------------------------------------------------------


def test_fetch_facilitator_rows_only_qualifying_statuses(
    conn: sqlite3.Connection,
) -> None:
    _seed(conn, facilitator_id="1", status="completed", started_at=_iso(NOW))
    _seed(conn, facilitator_id="1", status="followup_timeout", started_at=_iso(NOW))
    _seed(conn, facilitator_id="1", status="cancelled", started_at=_iso(NOW))
    _seed(conn, facilitator_id="1", status="pending", started_at=_iso(NOW))
    _seed(conn, facilitator_id="1", status="active", started_at=_iso(NOW))
    _seed(conn, facilitator_id="1", status="crashed", started_at=_iso(NOW))

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="1")
    assert len(rows) == 2


def test_fetch_facilitator_rows_use_original_facilitator_not_handoff(
    conn: sqlite3.Connection,
) -> None:
    _seed(
        conn,
        facilitator_id="1",
        status="completed",
        started_at=_iso(NOW),
        handoff_facilitator_id="2",
    )

    assert len(fetch_facilitator_stats_rows(conn, facilitator_id="1")) == 1
    assert len(fetch_facilitator_stats_rows(conn, facilitator_id="2")) == 0


def test_fetch_guild_rows_filters_by_guild(conn: sqlite3.Connection) -> None:
    _seed(conn, guild_id="A", status="completed", started_at=_iso(NOW))
    _seed(conn, guild_id="B", status="completed", started_at=_iso(NOW))

    assert len(fetch_guild_stats_rows(conn, guild_id="A")) == 1
    assert len(fetch_guild_stats_rows(conn, guild_id="B")) == 1


# ---------------------------------------------------------------------------
# compute_stats_summary — windows, minutes, completion rate
# ---------------------------------------------------------------------------


def test_windows_filter_by_started_at(conn: sqlite3.Connection) -> None:
    _seed(conn, status="completed", started_at=_iso(NOW - timedelta(days=1)))
    _seed(conn, status="completed", started_at=_iso(NOW - timedelta(days=10)))
    _seed(conn, status="completed", started_at=_iso(NOW - timedelta(days=40)))

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    seven, thirty, all_time = compute_stats_summary(rows, now=NOW)

    assert seven.sessions == 1
    assert thirty.sessions == 2
    assert all_time.sessions == 3


def test_focus_minutes_sum_treats_null_as_zero(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        status="completed",
        started_at=_iso(NOW),
        duration_minutes=None,
    )
    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    _, _, all_time = compute_stats_summary(rows, now=NOW)
    assert all_time.minutes == 0


def test_completion_rate_is_yes_over_yes_plus_no(conn: sqlite3.Connection) -> None:
    _seed(conn, status="completed", started_at=_iso(NOW), completed_intention=1)
    _seed(conn, status="completed", started_at=_iso(NOW), completed_intention=1)
    _seed(conn, status="completed", started_at=_iso(NOW), completed_intention=0)

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    _, _, all_time = compute_stats_summary(rows, now=NOW)
    assert all_time.rate == 67  # round(2/3 * 100)


def test_completion_rate_undefined_renders_no_rate_copy(
    conn: sqlite3.Connection,
) -> None:
    _seed(conn, status="followup_timeout", started_at=_iso(NOW))

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    _, _, all_time = compute_stats_summary(rows, now=NOW)
    assert all_time.rate is None
    value = render_row_value(all_time)
    assert value == STATS_ROW_VALUE_NO_RATE.format(sessions="1 session", minutes=25)
    assert "%" not in value


def test_rate_defined_uses_row_value_template() -> None:
    from app.stats import WindowStats

    stats = WindowStats(sessions=2, minutes=50, rate=100)
    assert render_row_value(stats) == STATS_ROW_VALUE.format(
        sessions="2 sessions", minutes=50, rate=100
    )


# ---------------------------------------------------------------------------
# Singular copy
# ---------------------------------------------------------------------------


def test_render_sessions_text_singular_and_plural() -> None:
    assert render_sessions_text(1) == "1 session"
    assert render_sessions_text(0) == "0 sessions"
    assert render_sessions_text(2) == "2 sessions"


def test_render_streak_line_singular_and_hidden() -> None:
    assert render_streak_line(0) is None
    assert render_streak_line(1) == STATS_STREAK_ONE
    assert render_streak_line(3) == STATS_STREAK.format(days=3)


# ---------------------------------------------------------------------------
# Streak — consecutive local calendar days ending today or yesterday
# ---------------------------------------------------------------------------


def test_streak_consecutive_days_ending_today(conn: sqlite3.Connection) -> None:
    tz = ZoneInfo("UTC")
    now = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
    _seed(conn, status="completed", started_at=_iso(now))
    _seed(conn, status="completed", started_at=_iso(now - timedelta(days=1)))
    _seed(conn, status="completed", started_at=_iso(now - timedelta(days=2)))

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    assert compute_streak(rows, now=now, tz=tz) == 3


def test_streak_zero_when_gap_before_yesterday(conn: sqlite3.Connection) -> None:
    tz = ZoneInfo("UTC")
    now = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
    _seed(conn, status="completed", started_at=_iso(now - timedelta(days=3)))

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    assert compute_streak(rows, now=now, tz=tz) == 0


def test_streak_crosses_utc_midnight_but_not_local_midnight(
    conn: sqlite3.Connection,
) -> None:
    """A session stored as UTC that is late-night in a non-UTC zone still
    counts for the correct *local* day, and does not get miscounted as the
    next UTC day."""
    tz = ZoneInfo("America/Los_Angeles")  # UTC-7 in late September (PDT)
    # 2026-09-30 05:00 UTC == 2026-09-29 22:00 PDT (previous local day).
    session_utc = datetime(2026, 9, 30, 5, 0, tzinfo=timezone.utc)
    # "Now" is later the same UTC day but still 2026-09-29 local.
    now_utc = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)

    _seed(conn, status="completed", started_at=_iso(session_utc))

    rows = fetch_facilitator_stats_rows(conn, facilitator_id="222")
    # Local "today" (2026-09-29) has a qualifying session -> streak of 1.
    assert compute_streak(rows, now=now_utc, tz=tz) == 1


# ---------------------------------------------------------------------------
# Empty data
# ---------------------------------------------------------------------------


def test_empty_summary_has_zero_sessions(conn: sqlite3.Connection) -> None:
    rows = fetch_facilitator_stats_rows(conn, facilitator_id="nobody")
    _, _, all_time = compute_stats_summary(rows, now=NOW)
    assert all_time.sessions == 0


# ---------------------------------------------------------------------------
# The /stats command
# ---------------------------------------------------------------------------


def _make_stats_interaction(*, guild_id: int | None = 222, user_id: int = 111) -> Any:
    inter = AsyncMock()
    inter.guild_id = guild_id
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    inter.user = user
    inter.response = AsyncMock()
    return inter


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    return SessionRegistry(conn)


@pytest.fixture()
def bot(conn: sqlite3.Connection, registry: SessionRegistry) -> TeaModeBot:
    return TeaModeBot(conn=conn, registry=registry)


@pytest.mark.asyncio
async def test_command_responds_ephemeral_with_titled_embed(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    _seed(
        conn,
        guild_id="222",
        facilitator_id="111",
        status="completed",
        started_at=_iso(NOW),
    )
    inter = _make_stats_interaction(guild_id=222, user_id=111)

    await bot._handle_stats(inter)

    inter.response.send_message.assert_awaited_once()
    call = inter.response.send_message.call_args
    assert call.kwargs.get("ephemeral") is True
    embed: discord.Embed = call.kwargs["embed"]
    assert embed.title == STATS_TITLE


@pytest.mark.asyncio
async def test_command_no_guild_sends_wrong_channel_refusal(bot: TeaModeBot) -> None:
    inter = _make_stats_interaction(guild_id=None, user_id=111)

    await bot._handle_stats(inter)

    inter.response.send_message.assert_awaited_once_with(
        MSG_WRONG_CHANNEL, ephemeral=True
    )


@pytest.mark.asyncio
async def test_command_empty_data_shows_stats_empty(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    inter = _make_stats_interaction(guild_id=222, user_id=111)

    await bot._handle_stats(inter)

    embed: discord.Embed = inter.response.send_message.call_args.kwargs["embed"]
    assert embed.description == STATS_EMPTY
    assert len(embed.fields) == 0


@pytest.mark.asyncio
async def test_command_has_you_and_server_sections(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    _seed(
        conn,
        guild_id="222",
        facilitator_id="111",
        status="completed",
        started_at=_iso(NOW),
    )
    inter = _make_stats_interaction(guild_id=222, user_id=111)

    await bot._handle_stats(inter)

    embed: discord.Embed = inter.response.send_message.call_args.kwargs["embed"]
    field_names = [f.name for f in embed.fields]
    assert field_names == [STATS_SECTION_YOU, STATS_SECTION_SERVER]
    for f in embed.fields:
        assert f.inline is False
