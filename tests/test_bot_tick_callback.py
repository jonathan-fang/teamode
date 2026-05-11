"""Tests for the TeaModeBot._on_countdown_tick callback.

Covers:
  - Edit-skip when the per-session lock is held (in-flight guard).
  - 429 backoff: floor doubles on rate-limit hit, decays back on success.
  - Non-edit-eligible ticks are no-ops (no message.edit call).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.bot import TeaModeBot, _EditState, _BACKOFF_FLOOR_DEFAULT, _BACKOFF_FLOOR_CAP
from app.db import init_db
from app.session import SessionRegistry


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


def _seed_active_session(
    registry: SessionRegistry, bot: TeaModeBot
) -> tuple[int, MagicMock]:
    """Create an ACTIVE session and stash a fake message in bot._edit_states.

    Returns (session_id, fake_message).
    """
    session = registry.create_pending_session(
        guild_id="100",
        text_channel_id="200",
        voice_channel_id="300",
        facilitator_id="111",
    )
    session_id = session.session_id
    registry.set_duration(session_id=session_id, duration_minutes=1)
    registry.set_intention(session_id=session_id, intention="test intention")
    registry.mark_active(session_id=session_id)

    fake_msg = AsyncMock(spec=discord.Message)
    bot._edit_states[session_id] = _EditState(message=fake_msg)

    return session_id, fake_msg


# ---------------------------------------------------------------------------
# Non-edit-eligible tick (mid-interval)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_edit_tick_is_noop(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A tick at a non-multiple-of-10 and non-zero value does nothing."""
    session_id, fake_msg = _seed_active_session(registry, bot)

    await bot._on_countdown_tick(session_id, seconds_remaining=55)

    fake_msg.edit.assert_not_called()


# ---------------------------------------------------------------------------
# Edit-skip: lock already held
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_skip_when_lock_held(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """When the per-session lock is held, the edit is skipped (no message.edit call)."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    edit_state = bot._edit_states[session_id]

    # Acquire the lock to simulate an in-flight edit.
    async with edit_state.lock:
        # Now fire a tick that would normally trigger an edit.
        await bot._on_countdown_tick(session_id, seconds_remaining=30)

    # message.edit must not have been called.
    fake_msg.edit.assert_not_called()


# ---------------------------------------------------------------------------
# 429 backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_doubles_backoff_floor(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A 429 response doubles the backoff floor (up to the cap)."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    edit_state = bot._edit_states[session_id]

    assert edit_state.backoff_floor == _BACKOFF_FLOOR_DEFAULT

    # Simulate a 429 HTTPException from message.edit.
    rate_limit_exc = discord.HTTPException(MagicMock(status=429), "rate limited")
    rate_limit_exc.status = 429
    fake_msg.edit.side_effect = rate_limit_exc

    await bot._on_countdown_tick(session_id, seconds_remaining=30)

    # Backoff floor must have doubled.
    assert edit_state.backoff_floor == _BACKOFF_FLOOR_DEFAULT * 2


@pytest.mark.asyncio
async def test_429_backoff_decays_on_success(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """After a 429 hit, a successful edit decays the backoff floor back to default."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    edit_state = bot._edit_states[session_id]

    # First tick: 429 → doubles floor.
    rate_limit_exc = discord.HTTPException(MagicMock(status=429), "rate limited")
    rate_limit_exc.status = 429
    fake_msg.edit.side_effect = rate_limit_exc
    await bot._on_countdown_tick(session_id, seconds_remaining=30)
    assert edit_state.backoff_floor == _BACKOFF_FLOOR_DEFAULT * 2

    # Second tick: success → floor back to default.
    fake_msg.edit.side_effect = None
    await bot._on_countdown_tick(session_id, seconds_remaining=20)
    assert edit_state.backoff_floor == _BACKOFF_FLOOR_DEFAULT


@pytest.mark.asyncio
async def test_429_backoff_capped_at_maximum(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Repeated 429s do not push the backoff floor above _BACKOFF_FLOOR_CAP."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    edit_state = bot._edit_states[session_id]

    rate_limit_exc = discord.HTTPException(MagicMock(status=429), "rate limited")
    rate_limit_exc.status = 429
    fake_msg.edit.side_effect = rate_limit_exc

    # Fire enough 429s to saturate the cap.
    for _ in range(10):
        await bot._on_countdown_tick(session_id, seconds_remaining=30)

    assert edit_state.backoff_floor == _BACKOFF_FLOOR_CAP


# ---------------------------------------------------------------------------
# Successful edit writes the correct content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_content_format(bot: TeaModeBot, registry: SessionRegistry) -> None:
    """A successful edit sends the exact formatted timer string."""
    session_id, fake_msg = _seed_active_session(registry, bot)

    await bot._on_countdown_tick(session_id, seconds_remaining=30)

    fake_msg.edit.assert_called_once_with(
        content="🍵 Intention: test intention  ⏳ 00:30"
    )


@pytest.mark.asyncio
async def test_edit_at_zero_sends_final_format(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """The final tick at 0 edits the message to 00:00."""
    session_id, fake_msg = _seed_active_session(registry, bot)

    await bot._on_countdown_tick(session_id, seconds_remaining=0)

    fake_msg.edit.assert_called_once_with(
        content="🍵 Intention: test intention  ⏳ 00:00"
    )
