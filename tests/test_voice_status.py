"""Tests for voice channel status updates at each session moment.

Covers:
  - ``LifecycleMixin._set_voice_status``: resolves a VoiceChannel or channel
    id, edits the status, and swallows Forbidden/HTTPException with a
    WARNING (never raises).
  - Activation sets Timer with the end HH:MM; follow-up reached sets
    Finished with the current HH:MM (before reverie/disconnect);
    solo-grace timeout sets Cancelled (before disconnecting).
  - Completed and followup_timeout do not touch the voice status (Finished
    stays).
  - Voice status is set only while the bot is connected to the voice
    channel: launch, pending expiry, voice-connect failure, and startup
    reconciliation never call ``VoiceChannel.edit`` (Discord requires
    Manage Channels to set a status while disconnected, which this project
    does not request).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import discord
import pytest

from app.constants import (
    VOICE_STATUS_CANCELLED,
    VOICE_STATUS_FINISHED,
    VOICE_STATUS_TIMER,
)
from app.db import init_db
from app.discord_bot import TeaModeBot
from app.discord_bot.views import IntentionModal
from app.session import SessionRegistry, SessionState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn() -> sqlite3.Connection:
    return init_db(":memory:")


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    return SessionRegistry(conn)


@pytest.fixture()
def bot(conn: sqlite3.Connection, registry: SessionRegistry) -> TeaModeBot:
    return TeaModeBot(conn=conn, registry=registry)


def _install_fake_client(bot: TeaModeBot, get_channel: Any) -> MagicMock:
    """Swap bot.client for a fake whose get_channel(...) is *get_channel*
    (a callable or a MagicMock configured with return_value/side_effect)."""
    fake_client = MagicMock(spec=discord.Client)
    fake_user = MagicMock()
    fake_user.id = 1
    fake_client.user = fake_user
    fake_client.get_channel = get_channel
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


def _fake_voice_channel(channel_id: int) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    channel.edit = AsyncMock()
    return channel


# ---------------------------------------------------------------------------
# _set_voice_status — the shared helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_voice_status_edits_channel_and_logs_info(
    bot: TeaModeBot, caplog: pytest.LogCaptureFixture
) -> None:
    """A VoiceChannel passed directly is edited with the status, logged INFO."""
    channel = _fake_voice_channel(123)

    with caplog.at_level(logging.INFO, logger="app.discord_bot.lifecycle"):
        await bot._set_voice_status(channel, "🍵 Timer set")

    channel.edit.assert_awaited_once_with(status="🍵 Timer set")
    assert any("Set voice status" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_set_voice_status_resolves_channel_id_via_client(bot: TeaModeBot) -> None:
    """An int channel id is resolved via client.get_channel and narrowed."""
    channel = _fake_voice_channel(456)
    _install_fake_client(bot, MagicMock(return_value=channel))

    await bot._set_voice_status(456, "status text")

    channel.edit.assert_awaited_once_with(status="status text")


@pytest.mark.asyncio
async def test_set_voice_status_missing_channel_logs_warning(
    bot: TeaModeBot, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing channel (get_channel returns None) logs WARNING and does not raise."""
    _install_fake_client(bot, MagicMock(return_value=None))

    with caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"):
        await bot._set_voice_status(789, "status text")

    assert any("is not a VoiceChannel" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_set_voice_status_non_voice_channel_logs_warning(
    bot: TeaModeBot, caplog: pytest.LogCaptureFixture
) -> None:
    """A resolved non-VoiceChannel logs WARNING and does not raise."""
    text_channel = MagicMock(spec=discord.TextChannel)
    _install_fake_client(bot, MagicMock(return_value=text_channel))

    with caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"):
        await bot._set_voice_status(789, "status text")

    assert any("is not a VoiceChannel" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_set_voice_status_forbidden_logs_warning_missing_permission(
    bot: TeaModeBot, caplog: pytest.LogCaptureFixture
) -> None:
    """discord.Forbidden is logged at WARNING (flagged as a permission issue) and swallowed."""
    channel = _fake_voice_channel(1)
    channel.edit = AsyncMock(
        side_effect=discord.Forbidden(MagicMock(), "missing perms")
    )

    with caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"):
        await bot._set_voice_status(channel, "status text")

    assert any(
        "permission" in r.message.lower() and r.levelno == logging.WARNING
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_set_voice_status_http_exception_logs_warning(
    bot: TeaModeBot, caplog: pytest.LogCaptureFixture
) -> None:
    """A generic discord.HTTPException is logged at WARNING and swallowed."""
    channel = _fake_voice_channel(1)
    channel.edit = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))

    with caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"):
        await bot._set_voice_status(channel, "status text")

    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# Launch — no voice status (bot is not connected yet)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_does_not_set_voice_status(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """/teamode invocation never calls VoiceChannel.edit — the bot has not
    connected to voice yet at this point."""
    channel = _fake_voice_channel(333)

    inter = AsyncMock()
    inter.channel = channel
    inter.guild_id = 222

    user = MagicMock(spec=discord.Member)
    user.id = 111
    voice_channel = MagicMock()
    voice_channel.id = 333
    member = MagicMock(spec=discord.Member)
    member.id = 111
    member.bot = False
    member.mention = "<@111>"
    voice_channel.members = [member]
    voice_state = MagicMock()
    voice_state.channel = voice_channel
    user.voice = voice_state
    inter.user = user

    inter.response = AsyncMock()

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._handle_teamode(inter)

    channel.edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Activation — Timer with end HH:MM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activation_sets_timer_status_with_end_hhmm(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Submitting the intention modal sets VOICE_STATUS_TIMER with the end
    time, formatted in TEAMODE_TIMEZONE (a fixed, non-UTC zone here)."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)

    fake_voice_channel = _fake_voice_channel(333)
    fake_voice_channel.send = AsyncMock(return_value=AsyncMock())
    modal = IntentionModal(bot=bot, session_id=sid, voice_channel=fake_voice_channel)
    text_input = cast(
        discord.ui.TextInput[discord.ui.Modal], modal.intention_field.component
    )
    text_input._value = "focus"

    inter = AsyncMock()
    inter.response = AsyncMock()
    inter.channel = fake_voice_channel

    # started_at = 2026-01-01T00:00:00 UTC -> +25min = 00:25 UTC.
    # TEAMODE_TIMEZONE fixed to UTC+2 -> end displays as 02:25.
    fixed_started_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fixed_tz = ZoneInfo("Etc/GMT-2")  # UTC+2

    def _close_coro(coro: object, **_kwargs: object) -> None:
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]

    with (
        patch("app.discord_bot.views.voice.connect", return_value=AsyncMock()),
        patch("app.discord_bot.views._now", return_value=fixed_started_at),
        patch("app.discord_bot.views.TEAMODE_TIMEZONE", fixed_tz),
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close_coro),
    ):
        await modal.on_submit(inter)

    fake_voice_channel.edit.assert_any_await(
        status=VOICE_STATUS_TIMER.format(hhmm="02:25")
    )


# ---------------------------------------------------------------------------
# Voice-connect failure — no voice status (bot never connected)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_connect_failure_does_not_set_voice_status(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A voice-connect failure never calls VoiceChannel.edit — the bot
    never connected to the channel."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=10)

    fake_voice_channel = _fake_voice_channel(333)
    _install_fake_client(bot, MagicMock(return_value=fake_voice_channel))
    modal = IntentionModal(bot=bot, session_id=sid, voice_channel=fake_voice_channel)
    text_input = cast(
        discord.ui.TextInput[discord.ui.Modal], modal.intention_field.component
    )
    text_input._value = "will fail"

    inter = AsyncMock()
    inter.response = AsyncMock()
    inter.followup = AsyncMock()

    with (
        patch("app.discord_bot.views.voice.connect", side_effect=Exception("no voice")),
        patch("app.discord_bot.tasks.asyncio.create_task"),
    ):
        await modal.on_submit(inter)

    session_after = registry.get(sid)
    assert session_after is not None
    assert session_after.state == SessionState.CANCELLED
    fake_voice_channel.edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Follow-up reached — Finished with current HH:MM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_sets_finished_status_with_current_hhmm(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """After Time's up posts, VOICE_STATUS_FINISHED is set with the current
    HH:MM — before reverie playback and disconnect."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    fake_vc = MagicMock(spec=discord.VoiceClient)
    fake_channel_for_vc = MagicMock(spec=discord.VoiceChannel)
    fake_channel_for_vc.members = []
    fake_vc.channel = fake_channel_for_vc

    fake_voice_channel = _fake_voice_channel(444)
    _install_fake_client(bot, MagicMock(return_value=fake_voice_channel))

    fake_channel = AsyncMock()
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 1
    fake_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    fixed_now = datetime(2026, 1, 1, 3, 45, 0, tzinfo=timezone.utc)
    fixed_tz = timezone.utc

    call_order: list[str] = []

    async def _record_reverie(_voice_client: object) -> bool:
        call_order.append("reverie")
        return True

    async def _record_edit(**kwargs: object) -> None:
        call_order.append("edit")

    fake_voice_channel.edit.side_effect = _record_edit

    with (
        patch(
            "app.discord_bot.lifecycle.voice.play_reverie_then_disconnect",
            side_effect=_record_reverie,
        ),
        patch("app.discord_bot.lifecycle._now", return_value=fixed_now),
        patch("app.discord_bot.lifecycle.TEAMODE_TIMEZONE", fixed_tz),
    ):
        await bot._run_end_of_session(
            session_id=sid, voice_client=fake_vc, channel=fake_channel
        )

    fake_voice_channel.edit.assert_any_await(
        status=VOICE_STATUS_FINISHED.format(hhmm="03:45")
    )
    # The status edit happens before reverie playback/disconnect.
    assert call_order == ["edit", "reverie"]


@pytest.mark.asyncio
async def test_completed_reaction_does_not_change_voice_status(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Facilitator ✅ answering follow-up does not call _set_voice_status —
    the Finished status set earlier stays in place."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    bot._reflect_message_ids[sid] = 55555
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    fake_client = MagicMock(spec=discord.Client)
    fake_user = MagicMock()
    fake_user.id = 9
    fake_client.user = fake_user
    bot.client = fake_client  # type: ignore[assignment]

    from dataclasses import dataclass

    @dataclass
    class _FakePayload:
        user_id: int
        message_id: int
        emoji: Any
        channel_id: int = 333
        guild_id: int = 222

    emoji = MagicMock()
    emoji.__str__ = MagicMock(return_value="✅")

    with patch.object(bot, "_set_voice_status", new=AsyncMock()) as mock_set_status:
        await bot.on_raw_reaction_add(
            _FakePayload(user_id=111, message_id=55555, emoji=emoji)  # type: ignore[arg-type]
        )

    mock_set_status.assert_not_called()
    session_after = registry.get(sid)
    assert session_after is not None
    assert session_after.state == SessionState.COMPLETED


# ---------------------------------------------------------------------------
# Solo grace — Cancelled (set before disconnect)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solo_grace_timeout_sets_cancelled_status_before_disconnect(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Solo-grace timeout sets VOICE_STATUS_CANCELLED while still connected,
    before disconnecting voice."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)

    fake_voice_channel = _fake_voice_channel(444)
    fake_voice_client = MagicMock(spec=discord.VoiceClient)
    fake_voice_client.channel = fake_voice_channel
    bot._voice_clients[sid] = fake_voice_client

    call_order: list[str] = []

    async def _record_edit(**kwargs: object) -> None:
        call_order.append("edit")

    fake_voice_channel.edit.side_effect = _record_edit

    async def _record_disconnect(_voice_client: object) -> None:
        call_order.append("disconnect")

    with patch(
        "app.discord_bot.lifecycle.voice.disconnect", side_effect=_record_disconnect
    ):
        await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    fake_voice_channel.edit.assert_any_await(status=VOICE_STATUS_CANCELLED)
    assert call_order == ["edit", "disconnect"]


# ---------------------------------------------------------------------------
# Pending expiry — no voice status (bot never connected)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_expiry_does_not_set_voice_status(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Pending-session expiry never calls VoiceChannel.edit — the bot never
    connected to the voice channel for a session still in PENDING."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id

    fake_voice_channel = _fake_voice_channel(333)
    fake_voice_channel.get_partial_message = MagicMock(return_value=AsyncMock())
    _install_fake_client(bot, MagicMock(return_value=fake_voice_channel))

    from app.discord_bot.views import _SetupMessages

    bot._setup_messages[sid] = _SetupMessages(channel_id=333, welcome_message_id=999)

    await bot._run_pending_expiry(session_id=sid, sleep_seconds=0)

    fake_voice_channel.edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Startup reconciliation — no voice status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_ready_does_not_set_voice_status(
    conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    """on_ready never touches voice status — reconciliation only writes the
    'crashed' status to SQLite (app.db.reconcile_crashed_sessions), it does
    not resolve or edit any voice channel."""
    voice_channel = _fake_voice_channel(10)

    def _get_channel(channel_id: int) -> Any:
        return {10: voice_channel}.get(channel_id)

    bot = TeaModeBot(conn=conn, registry=registry)
    _install_fake_client(bot, MagicMock(side_effect=_get_channel))

    await bot.on_ready()

    voice_channel.edit.assert_not_awaited()
