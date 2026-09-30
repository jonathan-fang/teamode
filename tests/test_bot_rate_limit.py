"""Tests for /teamode rate-limit refusals (per-user and per-guild)."""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.constants import GUILD_DAILY_CAP, MSG_RATE_LIMIT_GUILD, MSG_RATE_LIMIT_USER
from app.db import init_db
from app.discord_bot import TeaModeBot
from app.session import SessionRegistry


@pytest.fixture()
def conn() -> sqlite3.Connection:
    return init_db(":memory:")


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    return SessionRegistry(conn)


@pytest.fixture()
def bot(conn: sqlite3.Connection, registry: SessionRegistry) -> TeaModeBot:
    return TeaModeBot(conn=conn, registry=registry)


def _make_voice_interaction(
    channel_id: int,
    guild_id: int,
    user_id: int,
) -> Any:
    """Minimal FakeInteraction that clears all invocation guards.

    Mirrors tests/test_bot_invocation.py's helper of the same purpose.
    """
    inter = AsyncMock()

    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    inter.channel = channel
    inter.channel_id = channel_id
    inter.guild_id = guild_id

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    voice_channel = MagicMock()
    voice_channel.id = channel_id
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.bot = False
    member.mention = f"<@{user_id}>"
    voice_channel.members = [member]
    voice_state = MagicMock()
    voice_state.channel = voice_channel
    user.voice = voice_state
    inter.user = user

    inter.response = AsyncMock()
    return inter


def _row_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM sessions")
    return cur.fetchone()[0]


@pytest.mark.asyncio
async def test_teamode_routes_through_shared_start_session(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    """The /teamode handler delegates to _start_session."""
    inter = _make_voice_interaction(channel_id=1, guild_id=100, user_id=1)

    with (
        patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()),
        patch.object(bot, "_start_session", new=AsyncMock()) as mock_start_session,
    ):
        await bot._handle_teamode(inter)

    mock_start_session.assert_awaited_once_with(inter)


@pytest.mark.asyncio
async def test_fourth_call_in_window_gets_user_rate_limit_refusal(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    """A 4th /teamode by the same user within the window is refused; no row created."""
    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        for i in range(3):
            inter = _make_voice_interaction(channel_id=1 + i, guild_id=100, user_id=1)
            await bot._start_session(inter)

        refused_inter = _make_voice_interaction(channel_id=999, guild_id=100, user_id=1)
        await bot._start_session(refused_inter)

    refused_inter.response.send_message.assert_called_once()
    call_kwargs = refused_inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    # Canonical text with the seconds placeholder filled in with an integer.
    prefix, _, suffix = MSG_RATE_LIMIT_USER.partition("{seconds}")
    assert embed.description is not None
    assert embed.description.startswith(prefix)
    assert embed.description.endswith(suffix)


@pytest.mark.asyncio
async def test_guild_cap_refusal_has_canonical_text_and_creates_no_row(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    """The 51st distinct-user session in a guild is refused with the guild-cap text."""
    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        for i in range(GUILD_DAILY_CAP):
            inter = _make_voice_interaction(
                channel_id=1000 + i, guild_id=200, user_id=1000 + i
            )
            await bot._start_session(inter)

        rows_before = _row_count(conn)

        refused_inter = _make_voice_interaction(
            channel_id=9999, guild_id=200, user_id=9999
        )
        await bot._start_session(refused_inter)

    refused_inter.response.send_message.assert_called_once()
    call_kwargs = refused_inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description == MSG_RATE_LIMIT_GUILD.format(cap=GUILD_DAILY_CAP)

    # Refused call created no additional session row.
    assert _row_count(conn) == rows_before


@pytest.mark.asyncio
async def test_guard_refused_invocation_does_not_count_toward_user_limit(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    """A wrong-channel invocation (fails guard 1) never reaches the rate limiter."""
    text_channel_inter = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 1
    text_channel_inter.channel = channel
    text_channel_inter.guild_id = 100
    user = MagicMock(spec=discord.Member)
    user.id = 1
    user.voice = None
    text_channel_inter.user = user
    text_channel_inter.response = AsyncMock()

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        # Three guard-failing invocations — must not consume any of the
        # user's 3-call allowance.
        for _ in range(3):
            await bot._start_session(text_channel_inter)

        # A real, guard-passing invocation from the same user should still
        # succeed (allowance untouched by the guard failures above).
        good_inter = _make_voice_interaction(channel_id=2, guild_id=100, user_id=1)
        await bot._start_session(good_inter)

    call_kwargs = good_inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is not True
    assert _row_count(conn) == 1
