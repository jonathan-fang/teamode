"""Tests for app/discord_bot/runtime.py and for dropping a session's runtime.

Unit tests cover RuntimeStore / SessionRuntime / ChannelRuntime. The bot
tests check that every terminal path removes the session's whole runtime
(the old per-dict layout leaked the Go-again flag and the setup message ids
on some of them), and that the Go-again flag still reaches the chain prompt.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.discord_bot import TeaModeBot
from app.discord_bot.runtime import ChannelRuntime, RuntimeStore, SessionRuntime
from app.discord_bot.views import _SetupMessages
from app.session import SessionRegistry, SessionState

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    return SessionRegistry(conn)


@pytest.fixture()
def bot(conn: sqlite3.Connection, registry: SessionRegistry) -> TeaModeBot:
    return TeaModeBot(conn=conn, registry=registry)


def _install_fake_client(bot: TeaModeBot, user_id: int = 9) -> MagicMock:
    """Swap in a client whose get_channel finds nothing."""
    fake_client = MagicMock(spec=discord.Client)
    fake_client.user = MagicMock(id=user_id)
    fake_client.get_channel = MagicMock(return_value=None)
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


def _seed(registry: SessionRegistry, state: SessionState) -> int:
    """Create a session advanced to *state* (PENDING, ACTIVE or FOLLOWUP)."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    sid = session.session_id
    if state is SessionState.PENDING:
        return sid
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="write")
    registry.mark_active(session_id=sid)
    if state is SessionState.FOLLOWUP:
        registry.mark_followup(session_id=sid)
    return sid


async def _sleep_forever() -> None:
    await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# RuntimeStore / SessionRuntime / ChannelRuntime
# ---------------------------------------------------------------------------


def test_session_creates_once_and_peek_never_creates() -> None:
    store = RuntimeStore()
    assert store.peek_session(1) is None
    assert store.sessions == {}

    runtime = store.session(1)
    assert store.session(1) is runtime
    assert store.peek_session(1) is runtime

    assert store.pop_session(1) is runtime
    assert store.pop_session(1) is None
    assert store.sessions == {}


def test_session_for_reflect_finds_the_matching_session() -> None:
    store = RuntimeStore()
    store.session(1).reflect_message_id = 100
    store.session(2).reflect_message_id = 200
    store.session(3)

    assert store.session_for_reflect(200) == 2
    assert store.session_for_reflect(999) is None


def test_channel_runtimes_do_not_share_defaults() -> None:
    store = RuntimeStore()
    assert store.peek_channel(5) is None
    store.channel(5).streak.append(25)
    store.channel(5).cleanup.times_up_id = 1

    assert store.channel(6).streak == []
    assert store.channel(6).cleanup.times_up_id is None
    assert ChannelRuntime().streak == []


@pytest.mark.asyncio
async def test_cancel_tasks_skips_kept_and_finished_tasks() -> None:
    done = asyncio.ensure_future(asyncio.sleep(0))
    await done
    pending = asyncio.ensure_future(_sleep_forever())
    kept = asyncio.ensure_future(_sleep_forever())
    runtime = SessionRuntime(
        pending_expiry_task=done,
        countdown_task=pending,
        watchdog_task=kept,
    )

    runtime.cancel_tasks(keep=kept)
    await asyncio.sleep(0)

    assert pending.cancelled()
    assert not kept.done()
    kept.cancel()


# ---------------------------------------------------------------------------
# Terminal paths drop the whole runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_session_terminal_drops_runtime_and_cancels_tasks(
    bot: TeaModeBot,
) -> None:
    task = asyncio.ensure_future(_sleep_forever())
    runtime = bot._rt.session(7)
    runtime.watchdog_task = task
    runtime.reflect_message_id = 70
    runtime.chained_via_go_again = True

    await bot._on_session_terminal(7, delete_setup_messages=False)
    await asyncio.sleep(0)

    assert 7 not in bot._rt.sessions
    assert task.cancelled()
    # Idempotent: a second call finds nothing to do.
    await bot._on_session_terminal(7)


@pytest.mark.asyncio
async def test_on_session_terminal_does_not_cancel_the_calling_task(
    bot: TeaModeBot,
) -> None:
    finished_after_terminal = asyncio.Event()

    async def _own_task() -> None:
        await bot._on_session_terminal(8, delete_setup_messages=False)
        await asyncio.sleep(0)
        finished_after_terminal.set()

    task = asyncio.ensure_future(_own_task())
    bot._rt.session(8).countdown_task = task
    await task

    assert finished_after_terminal.is_set()
    assert 8 not in bot._rt.sessions


@pytest.mark.asyncio
async def test_pending_expiry_drops_runtime(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed(registry, SessionState.PENDING)
    _install_fake_client(bot)
    runtime = bot._rt.session(sid)
    runtime.setup = _SetupMessages(channel_id=333, welcome_message_id=999)
    runtime.chained_via_go_again = True

    await bot._run_pending_expiry(session_id=sid, sleep_seconds=0)

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED
    assert sid not in bot._rt.sessions


@pytest.mark.asyncio
async def test_solo_grace_timeout_drops_runtime(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed(registry, SessionState.ACTIVE)
    _install_fake_client(bot)
    runtime = bot._rt.session(sid)
    runtime.chained_via_go_again = True
    runtime.setup = _SetupMessages(channel_id=333, welcome_message_id=999)

    await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    assert sid not in bot._rt.sessions


@pytest.mark.parametrize("emoji", ["✅", "⛔"])
@pytest.mark.parametrize("chained", [True, False])
@pytest.mark.asyncio
async def test_facilitator_reaction_passes_chained_flag_and_drops_runtime(
    bot: TeaModeBot, registry: SessionRegistry, emoji: str, chained: bool
) -> None:
    sid = _seed(registry, SessionState.FOLLOWUP)
    _install_fake_client(bot)
    runtime = bot._rt.session(sid)
    runtime.reflect_message_id = 555
    runtime.chained_via_go_again = chained
    post_chain: Any = AsyncMock()
    bot._post_chain_prompt = post_chain  # type: ignore[method-assign]

    emoji_obj = MagicMock()
    emoji_obj.__str__ = MagicMock(return_value=emoji)
    payload = MagicMock(user_id=111, message_id=555, emoji=emoji_obj)

    await bot.on_raw_reaction_add(payload)

    post_chain.assert_awaited_once_with(sid, "333", chained=chained)
    assert sid not in bot._rt.sessions

    # A second reaction finds no session and is ignored.
    await bot.on_raw_reaction_add(payload)
    post_chain.assert_awaited_once()
