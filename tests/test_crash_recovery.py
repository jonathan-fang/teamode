"""Crash recovery: message ids persisted, reconcile returns crashed sessions,
and startup cleanup tidies the Discord messages a killed process left behind."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.constants import SESSION_RECORD_INTERRUPTED
from app.db import CrashedSession, init_db, reconcile_crashed_sessions
from app.discord_bot import TeaModeBot
from app.discord_bot.views import IntentionModal
from app.session import SessionRegistry
from tests.test_bot_invocation import _make_voice_interaction

# 2026-11-26T07:52:44Z == 23:52 America/Los_Angeles (PST).
_RESTART_UTC = "2026-11-26T07:52:44.526990+00:00"
_STARTED_UTC = "2026-11-26T07:28:19.195880+00:00"


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    return SessionRegistry(conn)


def _row(conn: sqlite3.Connection, session_id: int) -> dict[str, Any]:
    cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row))


def _insert(
    conn: sqlite3.Connection,
    status: str,
    *,
    welcome: str | None = None,
    timer: str | None = None,
    handoff: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO sessions (
            guild_id, text_channel_id, voice_channel_id, facilitator_id,
            started_at, duration_minutes, intention, status, mode,
            welcome_message_id, timer_message_id, handoff_facilitator_id
        ) VALUES ('g', '333', '333', '111', ?, 27, 'ship it', ?, 'groove', ?, ?, ?)
        """,
        (_STARTED_UTC, status, welcome, timer, handoff),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def test_init_db_adds_message_id_columns_to_old_table(tmp_path: Path) -> None:
    """An older sessions table gains the two columns; existing rows get NULL."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
            text_channel_id TEXT NOT NULL, voice_channel_id TEXT NOT NULL,
            facilitator_id TEXT NOT NULL, started_at TEXT, duration_minutes INTEGER,
            intention TEXT, ended_at TEXT, completed_intention INTEGER,
            followup_note TEXT, status TEXT NOT NULL, handoff_facilitator_id TEXT,
            mode TEXT NOT NULL DEFAULT 'voice'
        )
        """
    )
    old.execute(
        "INSERT INTO sessions (guild_id, text_channel_id, voice_channel_id,"
        " facilitator_id, status) VALUES ('g', '1', '1', 'f', 'completed')"
    )
    old.commit()
    old.close()

    conn = init_db(path)
    init_db(path).close()  # idempotent on a second run
    row = _row(conn, 1)
    assert row["welcome_message_id"] is None
    assert row["timer_message_id"] is None


# ---------------------------------------------------------------------------
# reconcile_crashed_sessions return value
# ---------------------------------------------------------------------------


def test_reconcile_returns_crashed_sessions_with_pre_crash_state(
    conn: sqlite3.Connection,
) -> None:
    active = _insert(conn, "active", welcome="10", timer="20", handoff="222")
    pending = _insert(conn, "pending", welcome="30")
    _insert(conn, "completed", timer="40")

    crashed = reconcile_crashed_sessions(conn)

    assert [c.session_id for c in crashed] == [active, pending]
    first = crashed[0]
    assert first.previous_status == "active"
    assert first.mode == "groove"
    assert first.text_channel_id == "333"
    assert first.facilitator_id == "222"  # handoff facilitator wins
    assert first.intention == "ship it"
    assert first.duration_minutes == 27
    assert first.started_at == _STARTED_UTC
    assert first.welcome_message_id == 10
    assert first.timer_message_id == 20
    assert first.ended_at == _row(conn, active)["ended_at"]
    assert crashed[1].previous_status == "pending"
    assert crashed[1].timer_message_id is None


# ---------------------------------------------------------------------------
# Message ids persisted during a session
# ---------------------------------------------------------------------------


def test_record_message_unknown_session_raises(registry: SessionRegistry) -> None:
    with pytest.raises(ValueError):
        registry.record_welcome_message(session_id=999, message_id=1)
    with pytest.raises(ValueError):
        registry.record_timer_message(session_id=999, message_id=1)


@pytest.mark.asyncio
async def test_session_start_persists_welcome_message_id(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot = TeaModeBot(conn=conn, registry=registry)
    inter = _make_voice_interaction()
    inter.original_response.return_value.id = 4242

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._handle_teamode(inter)

    (session_id,) = conn.execute("SELECT id FROM sessions").fetchone()
    assert _row(conn, session_id)["welcome_message_id"] == "4242"


@pytest.mark.asyncio
async def test_activation_persists_timer_message_id(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot = TeaModeBot(conn=conn, registry=registry)
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    registry.set_duration(session_id=session.session_id, duration_minutes=25)
    channel = MagicMock(spec=discord.VoiceChannel)
    timer_message = AsyncMock()
    timer_message.id = 9090
    channel.send = AsyncMock(return_value=timer_message)
    modal = IntentionModal(bot=bot, session_id=session.session_id, channel=channel)
    inter = AsyncMock()
    inter.response = AsyncMock()

    def _close(coro: object, **_kwargs: object) -> None:
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]

    with (
        patch("app.discord_bot.views.voice.connect", return_value=AsyncMock()),
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close),
    ):
        await modal.on_submit(inter)

    assert _row(conn, session.session_id)["timer_message_id"] == "9090"


# ---------------------------------------------------------------------------
# Startup cleanup
# ---------------------------------------------------------------------------


def _crashed(status: str, **overrides: Any) -> CrashedSession:
    fields: dict[str, Any] = {
        "session_id": 155,
        "previous_status": status,
        "mode": "groove",
        "text_channel_id": "333",
        "facilitator_id": "111",
        "intention": "settling the tutoring lead",
        "duration_minutes": 27,
        "started_at": _STARTED_UTC,
        "ended_at": _RESTART_UTC,
        "welcome_message_id": 10,
        "timer_message_id": 20,
    }
    fields.update(overrides)
    return CrashedSession(**fields)


def _bot_with_channel(
    conn: sqlite3.Connection, registry: SessionRegistry, crashed: list[CrashedSession]
) -> tuple[TeaModeBot, MagicMock, dict[int, AsyncMock]]:
    """Bot whose client resolves channel 333 to a fake text channel; returns
    the channel and a message_id -> partial-message map."""
    bot = TeaModeBot(conn=conn, registry=registry, crashed_sessions=crashed)
    partials: dict[int, AsyncMock] = {}
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 333

    def _partial(message_id: int) -> AsyncMock:
        return partials.setdefault(message_id, AsyncMock())

    channel.get_partial_message = MagicMock(side_effect=_partial)
    client = MagicMock(spec=discord.Client)
    client.user = None
    client.get_channel = MagicMock(
        side_effect=lambda cid: channel if cid == 333 else None
    )
    bot.client = client  # type: ignore[assignment]
    return bot, channel, partials


@pytest.mark.asyncio
async def test_cleanup_active_rewrites_frozen_timer_as_interrupted(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot, _channel, partials = _bot_with_channel(conn, registry, [])
    await bot._cleanup_crashed_sessions([_crashed("active")])

    kwargs = partials[20].edit.call_args.kwargs
    assert kwargs["embed"] is None
    assert kwargs["content"].splitlines() == [
        "🍵 Facilitator's Intention: settling the tutoring lead",
        "27 min session · Facilitated by <@111>",
        SESSION_RECORD_INTERRUPTED.format(hhmm="23:52"),
    ]
    assert 10 not in partials  # welcome untouched for an active session


@pytest.mark.asyncio
async def test_cleanup_followup_writes_normal_record(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot, _channel, partials = _bot_with_channel(conn, registry, [])
    await bot._cleanup_crashed_sessions([_crashed("followup")])

    content = partials[20].edit.call_args.kwargs["content"]
    assert content.splitlines()[-1] == "23:28 to 23:55"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "intention_set"])
async def test_cleanup_setup_disables_welcome_buttons(
    conn: sqlite3.Connection, registry: SessionRegistry, status: str
) -> None:
    bot, _channel, partials = _bot_with_channel(conn, registry, [])
    await bot._cleanup_crashed_sessions([_crashed(status)])

    kwargs = partials[10].edit.call_args.kwargs
    assert kwargs["content"] == SESSION_RECORD_INTERRUPTED.format(hhmm="23:52")
    buttons = [c for c in kwargs["view"].children if isinstance(c, discord.ui.Button)]
    assert buttons and all(b.disabled for b in buttons)
    assert 20 not in partials


@pytest.mark.asyncio
async def test_cleanup_skips_sessions_without_message_ids(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot, channel, _partials = _bot_with_channel(conn, registry, [])
    await bot._cleanup_crashed_sessions(
        [
            _crashed("active", timer_message_id=None),
            _crashed("pending", welcome_message_id=None),
            _crashed("active", duration_minutes=None),
        ]
    )
    channel.get_partial_message.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_tolerates_missing_channel_and_discord_errors(
    conn: sqlite3.Connection,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot, _channel, partials = _bot_with_channel(conn, registry, [])
    partials[20] = AsyncMock()
    partials[20].edit.side_effect = discord.NotFound(MagicMock(status=404), "gone")

    with (
        caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"),
        patch("app.discord_bot.lifecycle.asyncio.sleep", new=AsyncMock()),
    ):
        await bot._cleanup_crashed_sessions(
            [
                _crashed("active", session_id=1, text_channel_id="999"),  # gone
                _crashed("active", session_id=2, text_channel_id="tc"),  # bad id
                _crashed("active", session_id=3),  # message deleted
                _crashed("pending", session_id=4),  # still processed
            ]
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any("crashed session 1" in m for m in messages)
    assert any("non-numeric channel id" in m for m in messages)
    assert any(
        "Failed to clean up message 20 for crashed session 3" in m for m in messages
    )
    partials[10].edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_paces_edits(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot, _channel, _partials = _bot_with_channel(conn, registry, [])
    sleep = AsyncMock()
    with patch("app.discord_bot.lifecycle.asyncio.sleep", new=sleep):
        await bot._cleanup_crashed_sessions(
            [_crashed("active", session_id=n) for n in (1, 2, 3)]
        )
    assert sleep.await_count == 2  # between edits, not before the first


@pytest.mark.asyncio
async def test_on_ready_runs_cleanup_once(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    """Reconnects re-fire on_ready; the cleanup is handed off only the first time."""
    bot, _channel, _partials = _bot_with_channel(conn, registry, [_crashed("active")])
    cleanup = AsyncMock()

    def _close(coro: object, **_kwargs: object) -> None:
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]

    with (
        patch.object(bot, "_cleanup_crashed_sessions", cleanup),
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close),
    ):
        await bot.on_ready()
        await bot.on_ready()

    cleanup.assert_called_once()
    assert cleanup.call_args.args[0][0].session_id == 155


@pytest.mark.asyncio
async def test_on_ready_without_crashed_sessions_spawns_nothing(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    bot, _channel, _partials = _bot_with_channel(conn, registry, [])
    with patch("app.discord_bot.tasks.asyncio.create_task") as create_task:
        await bot.on_ready()
    create_task.assert_not_called()
