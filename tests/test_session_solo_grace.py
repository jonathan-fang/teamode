"""Tests for the 5-minute solo-facilitator grace watchdog.

Covers: watchdog timeout (session cancelled, voice disconnected, timer message
rewritten), watchdog cancellation on facilitator rejoin, listener-side arming
and cancellation detection.

All Discord gateway calls are mocked. SQLite uses an in-memory connection
backed by the real schema.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot import TeaModeBot, _EditState
from app.db import init_db
from app.session import SessionRegistry, SessionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory DB with schema applied."""
    return init_db(":memory:")


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    """SessionRegistry backed by a fresh in-memory DB."""
    return SessionRegistry(conn)


@pytest.fixture()
def bot(conn: sqlite3.Connection, registry: SessionRegistry) -> TeaModeBot:
    """TeaModeBot with real registry and in-memory DB.

    The discord.Client inside is never started; handlers are called directly.
    """
    return TeaModeBot(conn=conn, registry=registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_active_session(
    registry: SessionRegistry,
    *,
    guild_id: str = "222",
    text_channel_id: str = "333",
    voice_channel_id: str = "444",
    facilitator_id: str = "111",
) -> int:
    """Create a session in ACTIVE state; return session_id."""
    session = registry.create_pending_session(
        guild_id=guild_id,
        text_channel_id=text_channel_id,
        voice_channel_id=voice_channel_id,
        facilitator_id=facilitator_id,
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="test intention")
    registry.mark_active(session_id=sid)
    return sid


def _make_member(
    user_id: int,
    *,
    is_bot: bool = False,
) -> MagicMock:
    """Build a fake discord.Member."""
    m = MagicMock(spec=discord.Member)
    m.id = user_id
    m.bot = is_bot
    m.mention = f"<@{user_id}>"
    return m


def _install_fake_client_user(bot: TeaModeBot, user_id: int) -> MagicMock:
    """Replace bot.client with a MagicMock that has .user.id == user_id."""
    fake_client = MagicMock(spec=discord.Client)
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_client.user = fake_user
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


def _make_voice_state(channel: Any) -> MagicMock:
    """Build a fake discord.VoiceState whose .channel is *channel*."""
    vs = MagicMock(spec=discord.VoiceState)
    vs.channel = channel
    return vs


def _make_voice_channel(channel_id: int, members: list[Any]) -> MagicMock:
    """Build a fake discord.VoiceChannel with the given id and members list."""
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = channel_id
    vc.members = members
    return vc


def _make_fake_voice_client() -> MagicMock:
    """Build a minimal fake discord.VoiceClient."""
    vc = MagicMock(spec=discord.VoiceClient)
    return vc


def _make_edit_state(message: Any | None = None) -> _EditState:
    """Build a fake _EditState with an AsyncMock message."""
    msg = message or AsyncMock(spec=discord.Message)
    msg.edit = AsyncMock()
    return _EditState(message=msg)


# ---------------------------------------------------------------------------
# Watchdog timeout tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solo_grace_timeout_cancels_session(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Watchdog timeout: countdown cancelled, voice disconnected, message rewritten,
    session marked cancelled in both memory and SQLite.
    """
    sid = _seed_active_session(registry)

    # Set up pre-populated per-session state (as if a session is running).
    countdown_coro_task = asyncio.create_task(asyncio.sleep(60))
    fake_vc = _make_fake_voice_client()
    edit_state = _make_edit_state()

    bot._countdown_tasks[sid] = countdown_coro_task
    bot._voice_clients[sid] = fake_vc  # type: ignore[assignment]
    bot._edit_states[sid] = edit_state

    with patch("app.bot.voice.disconnect", new_callable=AsyncMock) as mock_disconnect:
        await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    # Countdown task was cancelled.
    assert countdown_coro_task.cancelled()

    # voice.disconnect was called with the fake voice client.
    mock_disconnect.assert_awaited_once_with(fake_vc)

    # Timer message was rewritten.
    edit_state.message.edit.assert_awaited_once_with(  # type: ignore[union-attr]
        content="Session ended — facilitator did not return."
    )

    # Session state in memory is CANCELLED.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED

    # SQLite row reflects cancellation.
    row = registry._conn.execute(
        "SELECT status FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == "cancelled"

    # All three per-session dicts no longer contain the session_id.
    assert sid not in bot._edit_states
    assert sid not in bot._voice_clients
    assert sid not in bot._countdown_tasks
    assert sid not in bot._solo_grace_tasks


@pytest.mark.asyncio
async def test_solo_grace_handles_missing_state_gracefully(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Watchdog timeout with no pre-populated dicts: no exception, mark_cancelled still called."""
    sid = _seed_active_session(registry)

    # No pre-populated state in any of the dicts.
    with patch("app.bot.voice.disconnect", new_callable=AsyncMock) as mock_disconnect:
        await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    # voice.disconnect was NOT called (no voice client).
    mock_disconnect.assert_not_awaited()

    # mark_cancelled was still called.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED


@pytest.mark.asyncio
async def test_solo_grace_edit_failure_does_not_block_cancellation(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """When the timer message edit raises HTTPException, cleanup still runs."""
    sid = _seed_active_session(registry)

    fake_vc = _make_fake_voice_client()
    edit_state = _make_edit_state()
    # Make message.edit raise HTTPException.
    edit_state.message.edit = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "rate limited")
    )

    bot._voice_clients[sid] = fake_vc  # type: ignore[assignment]
    bot._edit_states[sid] = edit_state

    with patch("app.bot.voice.disconnect", new_callable=AsyncMock) as mock_disconnect:
        # Should not raise despite the edit failure.
        await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    # voice.disconnect still called.
    mock_disconnect.assert_awaited_once_with(fake_vc)

    # mark_cancelled still called.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED


@pytest.mark.asyncio
async def test_solo_grace_cancelled_before_timeout(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """When the watchdog is cancelled (facilitator rejoined), the session is left intact."""
    sid = _seed_active_session(registry)

    # Schedule the watchdog with a real sleep so we can cancel it externally.
    task = asyncio.create_task(bot._run_solo_grace(session_id=sid, sleep_seconds=60))
    # Cancel immediately to simulate facilitator rejoining.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Session should remain ACTIVE — no cancellation happened.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.ACTIVE


# ---------------------------------------------------------------------------
# Listener-side arming tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solo_leave_arms_watchdog(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator leaves with only the bot remaining → watchdog armed."""
    sid = _seed_active_session(registry, voice_channel_id="444", facilitator_id="111")

    facilitator = _make_member(111)
    bot_member = _make_member(999, is_bot=True)

    voice_channel = _make_voice_channel(444, [facilitator, bot_member])
    before = _make_voice_state(voice_channel)
    after = _make_voice_state(None)

    _install_fake_client_user(bot, user_id=999)

    with patch("app.bot.asyncio.create_task", wraps=asyncio.create_task) as mock_create:
        await bot.on_voice_state_update(facilitator, before, after)

    # Watchdog was armed.
    assert sid in bot._solo_grace_tasks

    # Clean up: cancel the armed task.
    bot._solo_grace_tasks[sid].cancel()
    try:
        await bot._solo_grace_tasks.pop(sid)
    except (asyncio.CancelledError, Exception):
        pass

    mock_create.assert_called()


@pytest.mark.asyncio
async def test_facilitator_rejoins_cancels_watchdog(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator rejoins the same channel → pending watchdog is cancelled and removed."""
    sid = _seed_active_session(registry, voice_channel_id="444", facilitator_id="111")

    # Manually arm a watchdog with a real (long) sleep task.
    grace_task = asyncio.create_task(asyncio.sleep(60))
    bot._solo_grace_tasks[sid] = grace_task

    _install_fake_client_user(bot, user_id=999)

    # Simulate facilitator rejoining channel 444.
    voice_channel = _make_voice_channel(444, [_make_member(111)])
    before = _make_voice_state(None)  # was not in any channel
    after = _make_voice_state(voice_channel)

    await bot.on_voice_state_update(_make_member(111), before, after)

    # Give the event loop a tick to propagate the cancellation.
    await asyncio.sleep(0)

    # Watchdog task was cancelled.
    assert grace_task.cancelled()

    # Watchdog removed from the dict.
    assert sid not in bot._solo_grace_tasks


@pytest.mark.asyncio
async def test_different_user_rejoins_does_not_cancel_watchdog(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """A non-facilitator joins the same voice channel → watchdog remains."""
    sid = _seed_active_session(registry, voice_channel_id="444", facilitator_id="111")

    grace_task = asyncio.create_task(asyncio.sleep(60))
    bot._solo_grace_tasks[sid] = grace_task

    _install_fake_client_user(bot, user_id=999)

    # A different user (222) joins channel 444.
    voice_channel = _make_voice_channel(444, [_make_member(222)])
    before = _make_voice_state(None)
    after = _make_voice_state(voice_channel)

    await bot.on_voice_state_update(_make_member(222), before, after)

    # Watchdog still in place and not cancelled.
    assert sid in bot._solo_grace_tasks
    assert not grace_task.cancelled()

    # Teardown.
    grace_task.cancel()
    try:
        await grace_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_facilitator_rejoins_different_channel_does_not_cancel_watchdog(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator joins a different voice channel (no active session) → watchdog remains."""
    sid = _seed_active_session(registry, voice_channel_id="444", facilitator_id="111")

    grace_task = asyncio.create_task(asyncio.sleep(60))
    bot._solo_grace_tasks[sid] = grace_task

    _install_fake_client_user(bot, user_id=999)

    # Facilitator joins channel 555 — no active session there.
    other_channel = _make_voice_channel(555, [_make_member(111)])
    before = _make_voice_state(None)
    after = _make_voice_state(other_channel)

    await bot.on_voice_state_update(_make_member(111), before, after)

    # Watchdog for channel 444's session is untouched.
    assert sid in bot._solo_grace_tasks
    assert not grace_task.cancelled()

    # Teardown.
    grace_task.cancel()
    try:
        await grace_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_solo_leave_with_only_bot_remaining_arms_watchdog(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Voice channel had facilitator + bot only; facilitator leaves → watchdog arms."""
    sid = _seed_active_session(registry, voice_channel_id="444", facilitator_id="111")

    facilitator = _make_member(111)
    bot_member = _make_member(999, is_bot=True)

    # Channel members includes both facilitator and bot.
    voice_channel = _make_voice_channel(444, [facilitator, bot_member])
    before = _make_voice_state(voice_channel)
    after = _make_voice_state(None)

    _install_fake_client_user(bot, user_id=999)

    await bot.on_voice_state_update(facilitator, before, after)

    # Bot was correctly filtered out of remaining → watchdog armed.
    assert sid in bot._solo_grace_tasks

    # Teardown.
    bot._solo_grace_tasks[sid].cancel()
    try:
        await bot._solo_grace_tasks.pop(sid)
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_double_arm_protection(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """If a watchdog is already pending, a second voice event does not create another task."""
    sid = _seed_active_session(registry, voice_channel_id="444", facilitator_id="111")

    # Pre-arm a watchdog.
    existing_task = asyncio.create_task(asyncio.sleep(60))
    bot._solo_grace_tasks[sid] = existing_task

    facilitator = _make_member(111)
    bot_member = _make_member(999, is_bot=True)

    voice_channel = _make_voice_channel(444, [facilitator, bot_member])
    before = _make_voice_state(voice_channel)
    after = _make_voice_state(None)

    _install_fake_client_user(bot, user_id=999)

    # Fire the voice_state_update again.
    await bot.on_voice_state_update(facilitator, before, after)

    # Existing task is still the one in the dict — not replaced.
    assert bot._solo_grace_tasks[sid] is existing_task

    # Teardown.
    existing_task.cancel()
    try:
        await existing_task
    except asyncio.CancelledError:
        pass
