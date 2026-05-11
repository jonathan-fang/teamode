"""Tests for automatic RNG handoff (on_voice_state_update) and /handoff command.

Both features share the same mark_handoff registry call and public announcement
pattern. The automatic path is driven by the voice state listener; the manual
path is driven by the /handoff slash command callback.

All Discord gateway calls are mocked. SQLite uses an in-memory connection backed
by the real schema.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot import COLORS, TeaModeBot
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
    """TeaModeBot with real registry and in-memory DB."""
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
    """Create a session advanced to ACTIVE state; return session_id."""
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
    mention: str | None = None,
) -> MagicMock:
    """Build a fake discord.Member with the given id."""
    m = MagicMock(spec=discord.Member)
    m.id = user_id
    m.bot = is_bot
    m.mention = mention or f"<@{user_id}>"
    return m


def _install_fake_client_user(bot: TeaModeBot, user_id: int) -> MagicMock:
    """Replace bot.client with a MagicMock that has .user.id == user_id.

    discord.Client.user is a read-only property — swapping the whole client
    object is the simplest approach without patching the property descriptor.
    Returns the fake client so callers can further configure get_channel etc.
    """
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


# ---------------------------------------------------------------------------
# Automatic handoff — on_voice_state_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facilitator_leaves_with_others_triggers_rng_handoff(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator leaves with ≥1 human remaining → RNG handoff fires."""
    sid = _seed_active_session(
        registry, voice_channel_id="444", text_channel_id="333", facilitator_id="111"
    )

    facilitator = _make_member(111)
    other_member = _make_member(222)
    bot_member = _make_member(999, is_bot=True)

    # Before: facilitator was in channel 444 with other members.
    voice_channel = _make_voice_channel(444, [facilitator, other_member, bot_member])
    before = _make_voice_state(voice_channel)
    # After: facilitator disconnected (channel is None).
    after = _make_voice_state(None)

    fake_client = _install_fake_client_user(bot, user_id=999)
    fake_text_channel = AsyncMock()
    fake_client.get_channel = MagicMock(return_value=fake_text_channel)

    with patch("app.bot.random.choice", return_value=other_member):
        await bot.on_voice_state_update(facilitator, before, after)

    # Registry updated — new facilitator.
    session = registry.get(sid)
    assert session is not None
    assert session.facilitator_id == "222"

    # Announcement sent to text channel.
    fake_text_channel.send.assert_awaited_once()
    announcement: str = fake_text_channel.send.call_args.args[0]
    assert "<@111>" in announcement  # old facilitator
    assert "<@222>" in announcement  # new facilitator
    assert "left" in announcement


@pytest.mark.asyncio
async def test_facilitator_leaves_alone_no_handoff(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator leaves with no humans remaining → handoff does not fire (T5.2 seam)."""
    sid = _seed_active_session(
        registry, voice_channel_id="444", text_channel_id="333", facilitator_id="111"
    )

    facilitator = _make_member(111)
    bot_member = _make_member(999, is_bot=True)

    voice_channel = _make_voice_channel(444, [facilitator, bot_member])
    before = _make_voice_state(voice_channel)
    after = _make_voice_state(None)

    fake_client = _install_fake_client_user(bot, user_id=999)
    fake_text_channel = AsyncMock()
    fake_client.get_channel = MagicMock(return_value=fake_text_channel)

    with patch("app.bot.random.choice") as mock_choice:
        await bot.on_voice_state_update(facilitator, before, after)

    # mark_handoff was NOT called — facilitator_id unchanged.
    session = registry.get(sid)
    assert session is not None
    assert session.facilitator_id == "111"

    # No announcement.
    fake_text_channel.send.assert_not_called()
    mock_choice.assert_not_called()


@pytest.mark.asyncio
async def test_non_facilitator_leaves_no_handoff(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """A non-facilitator voice member leaves → no handoff, no announcement."""
    sid = _seed_active_session(
        registry, voice_channel_id="444", text_channel_id="333", facilitator_id="111"
    )

    non_facilitator = _make_member(222)
    facilitator = _make_member(111)

    voice_channel = _make_voice_channel(444, [facilitator, non_facilitator])
    before = _make_voice_state(voice_channel)
    after = _make_voice_state(None)

    fake_client = _install_fake_client_user(bot, user_id=999)
    fake_text_channel = AsyncMock()
    fake_client.get_channel = MagicMock(return_value=fake_text_channel)

    with patch("app.bot.random.choice") as mock_choice:
        await bot.on_voice_state_update(non_facilitator, before, after)

    # Session unchanged.
    session = registry.get(sid)
    assert session is not None
    assert session.facilitator_id == "111"

    fake_text_channel.send.assert_not_called()
    mock_choice.assert_not_called()


@pytest.mark.asyncio
async def test_member_switches_channels_treated_as_leave_for_source_channel(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator moves to a different channel → handoff fires for the source channel."""
    sid = _seed_active_session(
        registry, voice_channel_id="444", text_channel_id="333", facilitator_id="111"
    )

    facilitator = _make_member(111)
    other_member = _make_member(222)

    source_channel = _make_voice_channel(444, [facilitator, other_member])
    dest_channel = _make_voice_channel(555, [])

    before = _make_voice_state(source_channel)
    after = _make_voice_state(dest_channel)

    fake_client = _install_fake_client_user(bot, user_id=999)
    fake_text_channel = AsyncMock()
    fake_client.get_channel = MagicMock(return_value=fake_text_channel)

    with patch("app.bot.random.choice", return_value=other_member):
        await bot.on_voice_state_update(facilitator, before, after)

    session = registry.get(sid)
    assert session is not None
    assert session.facilitator_id == "222"

    fake_text_channel.send.assert_awaited_once()
    announcement: str = fake_text_channel.send.call_args.args[0]
    assert "<@111>" in announcement
    assert "<@222>" in announcement


# ---------------------------------------------------------------------------
# Manual /handoff command
# ---------------------------------------------------------------------------


def _make_handoff_interaction(
    channel_id: int = 333,
    user_id: int = 111,
    guild_id: int = 222,
) -> Any:
    """Build a fake Interaction for the /handoff command."""
    inter = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    inter.channel = channel

    inter.guild_id = guild_id

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.bot = False
    inter.user = user

    inter.response = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_handoff_command_happy_path(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator invokes /handoff with a valid target → handoff recorded, public announcement."""
    sid = _seed_active_session(
        registry,
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )

    target = _make_member(222)
    voice_channel = _make_voice_channel(444, [_make_member(111), target])

    fake_client = _install_fake_client_user(bot, user_id=999)
    fake_client.get_channel = MagicMock(return_value=voice_channel)

    inter = _make_handoff_interaction(channel_id=333, user_id=111)

    await bot._handle_handoff(inter, target)

    # Registry updated.
    session = registry.get(sid)
    assert session is not None
    assert session.facilitator_id == "222"

    # Public announcement (not ephemeral).
    inter.response.send_message.assert_awaited_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is not True
    content: str = inter.response.send_message.call_args.args[0]
    assert "<@111>" in content  # old facilitator
    assert "<@222>" in content  # new facilitator
    assert "handed off" in content


@pytest.mark.asyncio
async def test_handoff_command_no_active_session(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """/handoff with no active session in the channel → ephemeral refusal."""
    target = _make_member(222)

    _install_fake_client_user(bot, user_id=999)

    inter = _make_handoff_interaction(channel_id=333, user_id=111)

    await bot._handle_handoff(inter, target)

    inter.response.send_message.assert_awaited_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description is not None
    assert "No active TeaMode session" in embed.description
    assert embed.color == COLORS["refusal"]


@pytest.mark.asyncio
async def test_handoff_command_non_facilitator_refusal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Non-facilitator invoker → ephemeral refusal."""
    _seed_active_session(
        registry,
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )

    target = _make_member(333)

    _install_fake_client_user(bot, user_id=999)

    # user_id=222 is not the facilitator (111).
    inter = _make_handoff_interaction(channel_id=333, user_id=222)

    await bot._handle_handoff(inter, target)

    inter.response.send_message.assert_awaited_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description is not None
    assert "Only the facilitator" in embed.description
    assert embed.color == COLORS["refusal"]


@pytest.mark.asyncio
async def test_handoff_command_target_is_invoker_refusal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator targets themselves → ephemeral refusal."""
    _seed_active_session(
        registry,
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )

    # Target same id as invoker.
    target = _make_member(111)

    _install_fake_client_user(bot, user_id=999)

    inter = _make_handoff_interaction(channel_id=333, user_id=111)

    await bot._handle_handoff(inter, target)

    inter.response.send_message.assert_awaited_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description is not None
    assert "already the facilitator" in embed.description
    assert embed.color == COLORS["refusal"]


@pytest.mark.asyncio
async def test_handoff_command_target_is_bot_refusal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Target is a bot → ephemeral refusal."""
    _seed_active_session(
        registry,
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )

    target = _make_member(998, is_bot=True)

    _install_fake_client_user(bot, user_id=999)

    inter = _make_handoff_interaction(channel_id=333, user_id=111)

    await bot._handle_handoff(inter, target)

    inter.response.send_message.assert_awaited_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description is not None
    assert "human" in embed.description
    assert embed.color == COLORS["refusal"]


@pytest.mark.asyncio
async def test_handoff_command_target_not_in_voice_refusal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Target not in the voice channel → ephemeral refusal."""
    _seed_active_session(
        registry,
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )

    # Voice channel has only the facilitator — target is absent.
    facilitator_member = _make_member(111)
    voice_channel = _make_voice_channel(444, [facilitator_member])

    target = _make_member(222)  # not in voice

    fake_client = _install_fake_client_user(bot, user_id=999)
    fake_client.get_channel = MagicMock(return_value=voice_channel)

    inter = _make_handoff_interaction(channel_id=333, user_id=111)

    await bot._handle_handoff(inter, target)

    inter.response.send_message.assert_awaited_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description is not None
    assert "voice channel" in embed.description
    assert embed.color == COLORS["refusal"]
