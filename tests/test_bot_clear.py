"""Tests for the /teamode-clear command.

Covers: permission refusal, wrong-channel refusal, scan depth
(``CLEAR_SCAN_LIMIT``), non-bot messages kept, every kind of protected
"live" message kept (active-session timer/welcome/Set-Intention/nudge/
Reflect, each chain-prompt kind, an in-progress break), eligible past
messages deleted, ephemeral defer, ``CLEAR_DONE``/``CLEAR_NOTHING``
replies, an individual delete failure logged and skipped without
stopping the rest, and ``_channel_cleanup`` fields cleared for deleted ids.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.constants import (
    BREAK_STARTED,
    CHAIN_PROMPT,
    CLEAR_DONE,
    CLEAR_NO_PERMISSION,
    CLEAR_NOTHING,
    CLEAR_SCAN_LIMIT,
    END_EMBED_TITLE,
    FOLLOWUP_PROMPT,
    HANDOFF_ANNOUNCE,
    MSG_WRONG_CHANNEL,
    TIMER_EMBED_TITLE,
    WELCOME_EMBED_TITLE,
)
from app.db import init_db
from app.discord_bot import TeaModeBot
from app.discord_bot.breaks import _BreakState, _ChainState
from app.discord_bot.views import _ChannelCleanup, _EditState, _SetupMessages
from app.session import SessionRegistry

# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------

BOT_USER_ID = 999
OTHER_BOT_USER_ID = 888
HUMAN_USER_ID = 777


@pytest.fixture()
def conn() -> sqlite3.Connection:
    return init_db(":memory:")


@pytest.fixture()
def registry(conn: sqlite3.Connection) -> SessionRegistry:
    return SessionRegistry(conn)


@pytest.fixture()
def bot(conn: sqlite3.Connection, registry: SessionRegistry) -> TeaModeBot:
    bot = TeaModeBot(conn=conn, registry=registry)
    # discord.Client.user is a read-only property; swap the client for a
    # fake whose .user.id identifies Ocha's own messages.
    fake_client = MagicMock(spec=discord.Client)
    fake_client.user = MagicMock()
    fake_client.user.id = BOT_USER_ID
    bot.client = fake_client
    return bot


class _FakeEmbed:
    def __init__(self, title: str | None) -> None:
        self.title = title


class FakeMessage:
    """Minimal stand-in for discord.Message — only what /teamode-clear reads."""

    def __init__(
        self,
        message_id: int,
        *,
        content: str = "",
        embed_titles: list[str] | None = None,
        author_bot: bool = True,
        author_id: int | None = None,
        delete: AsyncMock | None = None,
    ) -> None:
        self.id = message_id
        self.content = content
        self.embeds = [_FakeEmbed(t) for t in (embed_titles or [])]
        author = MagicMock()
        author.bot = author_bot
        if author_id is None:
            author_id = BOT_USER_ID if author_bot else HUMAN_USER_ID
        author.id = author_id
        self.author = author
        self.delete = delete if delete is not None else AsyncMock()


class _FakeHistory:
    """A minimal async-iterable stand-in for ``channel.history(...)``."""

    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = messages

    def __aiter__(self) -> Any:
        return self._gen()

    async def _gen(self) -> Any:
        for message in self._messages:
            yield message


def _make_channel(messages: list[FakeMessage], *, channel_id: int = 333) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    channel.history = MagicMock(return_value=_FakeHistory(messages))
    return channel


def _make_clear_interaction(channel: Any, *, manage_messages: bool = True) -> AsyncMock:
    inter = AsyncMock()
    inter.channel = channel
    permissions = MagicMock(spec=discord.Permissions)
    permissions.manage_messages = manage_messages
    inter.permissions = permissions
    inter.response = AsyncMock()
    inter.followup = AsyncMock()
    return inter


def _seed_active_session(
    bot: TeaModeBot,
    registry: SessionRegistry,
    *,
    channel_id: int,
    timer_message_id: int,
    welcome_id: int,
    intention_id: int,
    nudge_id: int,
) -> int:
    """Seed a live ACTIVE session with a timer + full setup-message set."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id=str(channel_id),
        voice_channel_id=str(channel_id),
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="write tests")
    registry.mark_active(session_id=sid)

    timer_message = MagicMock()
    timer_message.id = timer_message_id
    bot._edit_states[sid] = _EditState(message=timer_message)
    bot._setup_messages[sid] = _SetupMessages(
        channel_id=channel_id,
        welcome_message_id=welcome_id,
        intention_message_id=intention_id,
        nudge_message_id=nudge_id,
    )
    return sid


def _seed_followup_session(
    bot: TeaModeBot,
    registry: SessionRegistry,
    *,
    channel_id: int,
    reflect_message_id: int,
) -> int:
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id=str(channel_id),
        voice_channel_id=str(channel_id),
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="write tests")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)
    bot._reflect_message_ids[sid] = reflect_message_id
    return sid


# ---------------------------------------------------------------------------
# Permission and channel-type guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_permission_refuses_and_skips_scan(bot: TeaModeBot) -> None:
    channel = _make_channel([])
    interaction = _make_clear_interaction(channel, manage_messages=False)

    await bot._handle_clear(interaction)

    interaction.response.send_message.assert_awaited_once_with(
        CLEAR_NO_PERMISSION, ephemeral=True
    )
    channel.history.assert_not_called()
    interaction.response.defer.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_channel_type_refuses(bot: TeaModeBot) -> None:
    channel = MagicMock(spec=discord.DMChannel)
    interaction = _make_clear_interaction(channel, manage_messages=True)

    await bot._handle_clear(interaction)

    interaction.response.send_message.assert_awaited_once_with(
        MSG_WRONG_CHANNEL, ephemeral=True
    )


# ---------------------------------------------------------------------------
# Scan depth and ephemeral defer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_called_with_scan_limit(bot: TeaModeBot) -> None:
    channel = _make_channel([])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    channel.history.assert_called_once_with(limit=CLEAR_SCAN_LIMIT)


@pytest.mark.asyncio
async def test_defer_is_ephemeral_thinking(bot: TeaModeBot) -> None:
    channel = _make_channel([])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)


# ---------------------------------------------------------------------------
# Kept messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_bot_messages_are_kept(bot: TeaModeBot) -> None:
    human_message = FakeMessage(1, content=CHAIN_PROMPT, author_bot=False)
    channel = _make_channel([human_message])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    human_message.delete.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(CLEAR_NOTHING, ephemeral=True)


@pytest.mark.asyncio
async def test_other_bots_messages_are_kept(bot: TeaModeBot) -> None:
    # Another bot (e.g. a second TeaMode instance) posting identical copy is
    # not Ocha — only messages authored by this bot's own user are deleted.
    other_bot_message = FakeMessage(
        1, content=CHAIN_PROMPT, author_id=OTHER_BOT_USER_ID
    )
    channel = _make_channel([other_bot_message])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    other_bot_message.delete.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(CLEAR_NOTHING, ephemeral=True)


@pytest.mark.asyncio
async def test_active_session_messages_are_kept(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    channel_id = 333
    _seed_active_session(
        bot,
        registry,
        channel_id=channel_id,
        timer_message_id=10,
        welcome_id=11,
        intention_id=12,
        nudge_id=13,
    )
    timer_msg = FakeMessage(10, embed_titles=[TIMER_EMBED_TITLE.format(duration=25)])
    welcome_msg = FakeMessage(11, embed_titles=[WELCOME_EMBED_TITLE])
    intention_msg = FakeMessage(12, content="🥅 **[Set Intention]** please share")
    nudge_msg = FakeMessage(13, content="⏰ Wrap-up nudge — 3 minutes left.")
    channel = _make_channel(
        [timer_msg, welcome_msg, intention_msg, nudge_msg], channel_id=channel_id
    )
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    for msg in (timer_msg, welcome_msg, intention_msg, nudge_msg):
        msg.delete.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(CLEAR_NOTHING, ephemeral=True)


@pytest.mark.asyncio
async def test_live_followup_reflect_message_is_kept(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    channel_id = 333
    _seed_followup_session(bot, registry, channel_id=channel_id, reflect_message_id=99)
    reflect_msg = FakeMessage(
        99, content=FOLLOWUP_PROMPT, embed_titles=["🌿 [Reflect]"]
    )
    channel = _make_channel([reflect_msg], channel_id=channel_id)
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    reflect_msg.delete.assert_not_awaited()


@pytest.mark.parametrize("kind", ["chain", "chain_streak", "post_break"])
@pytest.mark.asyncio
async def test_live_chain_prompt_is_kept_for_every_kind(
    bot: TeaModeBot, kind: str
) -> None:
    channel_id = 333
    bot._chain_states[channel_id] = _ChainState(
        session_id=1,
        channel_id=channel_id,
        message_id=55,
        kind=kind,  # type: ignore[arg-type]
    )
    chain_msg = FakeMessage(55, content=CHAIN_PROMPT)
    channel = _make_channel([chain_msg], channel_id=channel_id)
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    chain_msg.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_break_message_is_kept(bot: TeaModeBot) -> None:
    channel_id = 333
    from datetime import datetime, timezone

    task = MagicMock()
    bot._break_states[channel_id] = _BreakState(
        task=task,
        message_id=77,
        end_time=datetime.now(timezone.utc),
        session_id=1,
    )
    break_msg = FakeMessage(77, content=BREAK_STARTED.format(hhmm="3:45 PM"))
    channel = _make_channel([break_msg], channel_id=channel_id)
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    break_msg.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_handoff_notice_is_kept(bot: TeaModeBot) -> None:
    content = HANDOFF_ANNOUNCE.format(
        old_facilitator_id="111", new_facilitator_id="222"
    )
    handoff_msg = FakeMessage(88, content=content)
    channel = _make_channel([handoff_msg])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    handoff_msg.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Deleted messages and reply counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eligible_past_messages_are_deleted_and_counted(
    bot: TeaModeBot,
) -> None:
    welcome_msg = FakeMessage(1, embed_titles=[WELCOME_EMBED_TITLE])
    times_up_msg = FakeMessage(2, content="Time's up!", embed_titles=[END_EMBED_TITLE])
    channel = _make_channel([welcome_msg, times_up_msg])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    welcome_msg.delete.assert_awaited_once()
    times_up_msg.delete.assert_awaited_once()
    interaction.followup.send.assert_awaited_once_with(
        CLEAR_DONE.format(n=2), ephemeral=True
    )


@pytest.mark.asyncio
async def test_nothing_to_clear_reply(bot: TeaModeBot) -> None:
    channel = _make_channel([])
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    interaction.followup.send.assert_awaited_once_with(CLEAR_NOTHING, ephemeral=True)


@pytest.mark.asyncio
async def test_delete_failure_is_logged_and_others_still_deleted(
    bot: TeaModeBot, caplog: pytest.LogCaptureFixture
) -> None:
    failing_delete = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
    welcome_msg = FakeMessage(
        1, embed_titles=[WELCOME_EMBED_TITLE], delete=failing_delete
    )
    times_up_msg = FakeMessage(2, content="Time's up!", embed_titles=[END_EMBED_TITLE])
    channel = _make_channel([welcome_msg, times_up_msg])
    interaction = _make_clear_interaction(channel)

    with caplog.at_level(logging.WARNING):
        await bot._handle_clear(interaction)

    welcome_msg.delete.assert_awaited_once()
    times_up_msg.delete.assert_awaited_once()
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    interaction.followup.send.assert_awaited_once_with(
        CLEAR_DONE.format(n=1), ephemeral=True
    )


@pytest.mark.asyncio
async def test_channel_cleanup_fields_cleared_for_deleted_ids(
    bot: TeaModeBot,
) -> None:
    channel_id = 333
    bot._channel_cleanup[channel_id] = _ChannelCleanup(
        times_up_id=2, reflect_id=3, why_id=None
    )
    times_up_msg = FakeMessage(2, content="Time's up!", embed_titles=[END_EMBED_TITLE])
    reflect_msg = FakeMessage(3, content=FOLLOWUP_PROMPT)
    channel = _make_channel([times_up_msg, reflect_msg], channel_id=channel_id)
    interaction = _make_clear_interaction(channel)

    await bot._handle_clear(interaction)

    cleanup = bot._channel_cleanup[channel_id]
    assert cleanup.times_up_id is None
    assert cleanup.reflect_id is None
