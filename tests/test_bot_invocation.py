"""Tests for the /teamode slash command invocation guard and welcome embed."""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.bot import (
    TeaModeBot,
    _MSG_NOT_IN_VOICE,
    _MSG_SESSION_ACTIVE,
    _MSG_WRONG_CHANNEL,
)
from app.db import init_db
from app.session import SessionRegistry


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

    The discord.Client inside is never started — we only call the handler
    directly.
    """
    return TeaModeBot(conn=conn, registry=registry)


def _make_voice_interaction(
    channel_id: int = 333,
    guild_id: int = 222,
    user_id: int = 111,
    user_voice_channel_id: int | None = 333,
) -> Any:
    """Build a FakeInteraction that looks like it came from a VoiceChannel.

    By default the user is in the same voice channel as the text chat.
    Pass ``user_voice_channel_id=None`` to simulate the user not being in voice.
    """
    inter = AsyncMock()

    # Channel — a real VoiceChannel instance for isinstance checks.
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    inter.channel = channel

    inter.guild_id = guild_id

    # User — discord.Member (has .voice attribute).
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    if user_voice_channel_id is not None:
        voice_channel = MagicMock()
        voice_channel.id = user_voice_channel_id
        voice_state = MagicMock()
        voice_state.channel = voice_channel
        user.voice = voice_state
    else:
        user.voice = None
    inter.user = user

    # response — mock send_message as an AsyncMock so it can be awaited.
    inter.response = AsyncMock()

    return inter


def _make_text_channel_interaction(
    channel_id: int = 444,
    user_id: int = 111,
    guild_id: int = 222,
) -> Any:
    """Build a FakeInteraction that came from a plain TextChannel (not voice)."""
    inter = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    inter.channel = channel

    inter.guild_id = guild_id

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    # User has voice attribute but pointing at a different channel to be safe.
    voice_channel = MagicMock()
    voice_channel.id = 999
    voice_state = MagicMock()
    voice_state.channel = voice_channel
    user.voice = voice_state
    inter.user = user

    inter.response = AsyncMock()
    return inter


def _row_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM sessions")
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Guard branch: wrong channel type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_wrong_channel_sends_ephemeral_refusal(
    bot: TeaModeBot,
    conn: sqlite3.Connection,
) -> None:
    """Invocation from a TextChannel sends an ephemeral refusal and inserts no row."""
    inter = _make_text_channel_interaction()

    await bot._handle_teamode(inter)

    inter.response.send_message.assert_called_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description == _MSG_WRONG_CHANNEL
    assert _row_count(conn) == 0


# ---------------------------------------------------------------------------
# Guard branch: invoker not in voice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_not_in_voice_sends_ephemeral_refusal(
    bot: TeaModeBot,
    conn: sqlite3.Connection,
) -> None:
    """Invocation when user is not in voice sends the not-in-voice refusal."""
    inter = _make_voice_interaction(user_voice_channel_id=None)

    await bot._handle_teamode(inter)

    inter.response.send_message.assert_called_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description == _MSG_NOT_IN_VOICE
    assert _row_count(conn) == 0


@pytest.mark.asyncio
async def test_guard_in_different_voice_channel_sends_ephemeral_refusal(
    bot: TeaModeBot,
    conn: sqlite3.Connection,
) -> None:
    """Invocation when user is in a *different* voice channel triggers the not-in-voice guard."""
    # channel_id=333 (the text chat) but user_voice_channel_id=999 (different channel)
    inter = _make_voice_interaction(channel_id=333, user_voice_channel_id=999)

    await bot._handle_teamode(inter)

    inter.response.send_message.assert_called_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description == _MSG_NOT_IN_VOICE
    assert _row_count(conn) == 0


# ---------------------------------------------------------------------------
# Guard branch: session already active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_session_already_active_sends_ephemeral_refusal(
    bot: TeaModeBot,
    conn: sqlite3.Connection,
    registry: SessionRegistry,
) -> None:
    """A second /teamode in a channel with an active session gets the session-active refusal."""
    # Seed an existing session in channel 333.
    registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )

    inter = _make_voice_interaction(channel_id=333, user_id=999)

    await bot._handle_teamode(inter)

    inter.response.send_message.assert_called_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description == _MSG_SESSION_ACTIVE
    # Only the seeded row, no new row inserted.
    assert _row_count(conn) == 1


# ---------------------------------------------------------------------------
# Guard pass: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_pass_creates_session_and_posts_welcome(
    bot: TeaModeBot,
    conn: sqlite3.Connection,
    registry: SessionRegistry,
) -> None:
    """When all guards pass, create_pending_session is called and welcome is posted non-ephemerally."""
    inter = _make_voice_interaction(
        channel_id=333,
        guild_id=222,
        user_id=111,
        user_voice_channel_id=333,
    )

    await bot._handle_teamode(inter)

    # send_message called once, not ephemeral, with an embed and a view.
    inter.response.send_message.assert_called_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is not True
    assert "embed" in call_kwargs
    assert "view" in call_kwargs

    # Embed uses matcha-sage color.
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.color == discord.Color.from_str("#7B9D6F")

    # Row inserted with status='pending'.
    assert _row_count(conn) == 1
    cur = conn.execute(
        "SELECT status, guild_id, text_channel_id, voice_channel_id, facilitator_id FROM sessions"
    )
    row = cur.fetchone()
    assert row[0] == "pending"
    assert row[1] == "222"
    assert row[2] == "333"
    assert row[3] == "333"
    assert row[4] == "111"


@pytest.mark.asyncio
async def test_guard_pass_timer_button_custom_ids(
    bot: TeaModeBot,
    conn: sqlite3.Connection,
) -> None:
    """Timer-pick button custom_ids follow teamode:<session_id>:timer:<minutes>."""
    inter = _make_voice_interaction(channel_id=333, guild_id=222, user_id=111)

    await bot._handle_teamode(inter)

    call_kwargs = inter.response.send_message.call_args.kwargs
    view: discord.ui.View = call_kwargs["view"]
    custom_ids = [
        item.custom_id for item in view.children if isinstance(item, discord.ui.Button)
    ]  # type: ignore[attr-defined]

    # Fetch the session_id that was created.
    cur = conn.execute("SELECT id FROM sessions")
    session_id = cur.fetchone()[0]

    assert f"teamode:{session_id}:timer:10" in custom_ids
    assert f"teamode:{session_id}:timer:25" in custom_ids
    assert f"teamode:{session_id}:timer:50" in custom_ids
