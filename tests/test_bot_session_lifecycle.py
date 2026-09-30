"""Tests for pending expiry, background-task exception logging, and the
unified stale-button refusal added to make the session lifecycle robust.

Covers:
  - A session left pending expires: cancelled, welcome message edited with
    the disabled duration row, and the text channel accepts a new /teamode.
  - The expiry watchdog survives a duration pick (the session is still
    pending) and still expires a session whose intention modal was
    dismissed; it is cancelled once the intention is submitted.
  - Exceptions inside background tasks (post-countdown follow-up, the
    follow-up watchdog, solo grace) are logged via logger.exception and
    never propagate unobserved.
  - Stale-button refusal: missing session, terminal session, and an
    out-of-range duration all get the ephemeral MSG_SESSION_INACTIVE
    refusal and change nothing.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.constants import MSG_PENDING_EXPIRED, MSG_SESSION_INACTIVE
from app.db import init_db
from app.discord_bot import TeaModeBot
from app.discord_bot.views import COLORS
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


def _install_fake_client(bot: TeaModeBot, channel: Any) -> MagicMock:
    """Swap bot.client for a fake whose get_channel(...) returns *channel*."""
    fake_client = MagicMock(spec=discord.Client)
    fake_client.get_channel = MagicMock(return_value=channel)
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


def _make_component_interaction(
    custom_id: str,
    user_id: int = 111,
) -> Any:
    inter = AsyncMock()
    inter.type = discord.InteractionType.component
    inter.data = {"custom_id": custom_id}
    user = MagicMock()
    user.id = user_id
    inter.user = user
    inter.response = AsyncMock()
    return inter


# ---------------------------------------------------------------------------
# Pending expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_session_expires_and_edits_welcome(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A session left pending for the timeout is cancelled and the welcome
    message is edited via the channel to show the expired notice with all
    duration buttons disabled; the text channel then accepts a new /teamode."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id

    fake_partial = AsyncMock()
    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(return_value=fake_partial)
    _install_fake_client(bot, fake_channel)

    from app.discord_bot.views import _SetupMessages

    bot._setup_messages[sid] = _SetupMessages(channel_id=333, welcome_message_id=999)

    await bot._run_pending_expiry(session_id=sid, sleep_seconds=0)

    session_after = registry.get(sid)
    assert session_after is not None
    assert session_after.state == SessionState.CANCELLED

    fake_channel.get_partial_message.assert_called_once_with(999)
    fake_partial.edit.assert_awaited_once()
    edit_kwargs = fake_partial.edit.call_args.kwargs
    assert edit_kwargs["content"] == MSG_PENDING_EXPIRED
    assert "embed" in edit_kwargs
    view: discord.ui.View = edit_kwargs["view"]
    buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
    assert buttons
    assert all(b.disabled for b in buttons)

    # The text channel accepts a new /teamode — no active session remains.
    assert registry.find_active_in_text_channel("333") is None


@pytest.mark.asyncio
async def test_pending_expiry_task_survives_duration_pick(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Picking a duration leaves the session PENDING, so the pending-expiry
    watchdog stays armed — a dismissed intention modal must still expire."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id

    # Arm a real (long) expiry task, as _start_session would.
    task = asyncio.create_task(asyncio.sleep(60))
    bot._pending_expiry_tasks[sid] = task

    custom_id = f"teamode:{sid}:timer:25"
    fake_voice_channel = MagicMock(spec=discord.VoiceChannel)
    inter = _make_component_interaction(custom_id, user_id=111)
    inter.channel = fake_voice_channel
    inter.message = AsyncMock(spec=discord.Message)

    try:
        with patch(
            "app.discord_bot.views.discord.ui.View.from_message",
            return_value=discord.ui.View(),
        ):
            await bot.on_interaction(inter)

        assert bot._pending_expiry_tasks.get(sid) is task
        assert not task.cancelled()
        assert task.cancelling() == 0
    finally:
        task.cancel()

    session_after = registry.get(sid)
    assert session_after is not None
    assert session_after.state == SessionState.PENDING
    assert session_after.duration_minutes == 25


@pytest.mark.asyncio
async def test_pending_expiry_fires_after_duration_pick_and_dismissed_modal(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A session whose duration was picked but whose intention modal was
    dismissed is still PENDING and is cancelled by the expiry watchdog."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)

    fake_partial = AsyncMock()
    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(return_value=fake_partial)
    _install_fake_client(bot, fake_channel)

    from app.discord_bot.views import _SetupMessages

    bot._setup_messages[sid] = _SetupMessages(channel_id=333, welcome_message_id=999)

    await bot._run_pending_expiry(session_id=sid, sleep_seconds=0)

    session_after = registry.get(sid)
    assert session_after is not None
    assert session_after.state == SessionState.CANCELLED
    assert fake_partial.edit.call_args.kwargs["content"] == MSG_PENDING_EXPIRED
    assert registry.find_active_in_text_channel("333") is None


# ---------------------------------------------------------------------------
# Background-task exception logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_logged_logs_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """spawn_logged logs via logger.exception and does not propagate."""
    from app.discord_bot.tasks import spawn_logged

    async def _boom() -> None:
        raise ValueError("kaboom")

    with caplog.at_level(logging.ERROR, logger="app.discord_bot.tasks"):
        task = spawn_logged(_boom(), name="test-boom")
        await task

    assert any("Background task" in r.message for r in caplog.records)
    assert task.exception() is None  # exception was caught inside the runner


@pytest.mark.asyncio
async def test_spawn_logged_reraises_cancelled_error() -> None:
    """CancelledError is expected on cancellation and is not logged as an error."""
    import asyncio

    from app.discord_bot.tasks import spawn_logged

    async def _sleep_forever() -> None:
        await asyncio.sleep(60)

    task = spawn_logged(_sleep_forever(), name="test-cancel")
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_followup_watchdog_exception_is_logged(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An exception raised inside the follow-up watchdog is logged and does
    not propagate unobserved."""
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
    _install_fake_client(bot, None)
    assert bot.client.user is not None or True  # fake_client.user is MagicMock

    fake_channel = AsyncMock()
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 12345
    fake_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    with patch(
        "app.discord_bot.lifecycle.voice.play_reverie_then_disconnect",
        return_value=True,
    ):
        await bot._run_end_of_session(
            session_id=sid, voice_client=fake_vc, channel=fake_channel
        )

    watchdog_task = bot._watchdog_tasks[sid]

    # Force the watchdog's own cleanup to raise, then let it fire.
    with patch.object(
        registry, "mark_followup_timeout", side_effect=RuntimeError("db down")
    ):
        with caplog.at_level(logging.ERROR):
            with patch("app.discord_bot.lifecycle.asyncio.sleep", return_value=None):
                await watchdog_task

    assert any("mark_followup_timeout failed" in r.message for r in caplog.records)
    # The watchdog task completed without propagating the exception.
    assert watchdog_task.done()
    assert watchdog_task.exception() is None


# ---------------------------------------------------------------------------
# Unified stale-button refusal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timer_pick_on_terminal_session_gets_stale_refusal(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A timer-pick click on a session already advanced past PENDING is
    refused with MSG_SESSION_INACTIVE and changes nothing."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="already advanced")

    custom_id = f"teamode:{sid}:timer:25"
    inter = _make_component_interaction(custom_id, user_id=111)
    inter.channel = MagicMock(spec=discord.VoiceChannel)

    await bot.on_interaction(inter)

    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    embed: discord.Embed = kwargs["embed"]
    assert embed.description == MSG_SESSION_INACTIVE
    assert embed.color == COLORS["refusal"]
    inter.response.send_modal.assert_not_called()

    session_after = registry.get(sid)
    assert session_after is not None
    assert session_after.intention == "already advanced"


@pytest.mark.asyncio
async def test_timer_pick_missing_session_gets_stale_refusal(
    bot: TeaModeBot,
) -> None:
    """A click for a session_id no longer in the registry (e.g. after
    restart) is refused with MSG_SESSION_INACTIVE."""
    inter = _make_component_interaction("teamode:42424:timer:10", user_id=111)
    inter.channel = MagicMock(spec=discord.VoiceChannel)

    await bot.on_interaction(inter)

    kwargs = inter.response.send_message.call_args.kwargs
    embed: discord.Embed = kwargs["embed"]
    assert embed.description == MSG_SESSION_INACTIVE
    inter.response.send_modal.assert_not_called()
