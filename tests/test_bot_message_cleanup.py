"""Tests for setup-message deletion at terminal states, previous "Time's up"
deletion on the next session, and @-mentions on the initial timer message.

Covers:
  - completed (checkmark/no-entry), followup_timeout, solo-grace cancelled,
    and voice-connect-failure cancelled all delete the welcome and
    Set-Intention messages via the channel's partial message.
  - Pending expiry does NOT delete them.
  - NotFound/Forbidden/HTTPException on delete is logged at WARNING and the
    flow continues.
  - The previous session's "Time's up" message is deleted when the next
    /teamode starts in the same channel.
  - The initial timer send includes non-bot voice member mentions; tick
    edits reuse the mention line with AllowedMentions.none().
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.db import init_db
from app.discord_bot import TeaModeBot
from app.discord_bot.views import (
    IntentionModal,
    _ChannelCleanup,
    _EditState,
    _SetupMessages,
)
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


def _install_fake_client(bot: TeaModeBot, channel: Any, user_id: int = 1) -> MagicMock:
    fake_client = MagicMock(spec=discord.Client)
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_client.user = fake_user
    fake_client.get_channel = MagicMock(return_value=channel)
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


def _make_fake_channel() -> tuple[MagicMock, AsyncMock]:
    """A fake VoiceChannel whose get_partial_message(...) returns one shared
    AsyncMock partial message (good enough — tests only check call args)."""
    fake_partial = AsyncMock()
    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(return_value=fake_partial)
    return fake_channel, fake_partial


def _seed_with_setup_messages(
    bot: TeaModeBot,
    registry: SessionRegistry,
    *,
    channel_id: int = 333,
    welcome_id: int = 100,
    intention_id: int = 200,
    nudge_id: int | None = None,
) -> int:
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id=str(channel_id),
        voice_channel_id=str(channel_id),
        facilitator_id="111",
    )
    sid = session.session_id
    bot._setup_messages[sid] = _SetupMessages(
        channel_id=channel_id,
        welcome_message_id=welcome_id,
        intention_message_id=intention_id,
        nudge_message_id=nudge_id,
    )
    return sid


@dataclass
class FakeRawReactionActionEvent:
    user_id: int
    message_id: int
    emoji: Any
    channel_id: int = 333
    guild_id: int = 222


def _make_emoji(text: str) -> MagicMock:
    e = MagicMock()
    e.__str__ = MagicMock(return_value=text)
    return e


# ---------------------------------------------------------------------------
# Deletion at terminal states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_checkmark_deletes_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    bot._reflect_message_ids[sid] = 999
    fake_channel, fake_partial = _make_fake_channel()
    _install_fake_client(bot, fake_channel)

    payload = FakeRawReactionActionEvent(
        user_id=111, message_id=999, emoji=_make_emoji("✅")
    )
    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    assert fake_channel.get_partial_message.call_args_list == [
        ((100,),),
        ((200,),),
    ]
    assert fake_partial.delete.await_count == 2
    assert sid not in bot._setup_messages


@pytest.mark.asyncio
async def test_completed_checkmark_deletes_nudge_message_when_it_fired(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """When a wrap-up nudge fired earlier in the session, terminal cleanup
    also deletes it, via the channel, alongside the welcome and
    Set-Intention messages."""
    sid = _seed_with_setup_messages(bot, registry, nudge_id=300)
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    bot._reflect_message_ids[sid] = 999
    fake_channel, fake_partial = _make_fake_channel()
    _install_fake_client(bot, fake_channel)

    payload = FakeRawReactionActionEvent(
        user_id=111, message_id=999, emoji=_make_emoji("✅")
    )
    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    assert fake_channel.get_partial_message.call_args_list == [
        ((100,),),
        ((200,),),
        ((300,),),
    ]
    assert fake_partial.delete.await_count == 3
    assert sid not in bot._setup_messages


@pytest.mark.asyncio
async def test_completed_no_entry_deletes_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    bot._reflect_message_ids[sid] = 999
    fake_channel, fake_partial = _make_fake_channel()
    fake_client = _install_fake_client(bot, fake_channel)
    # get_channel is used both for _on_session_terminal and the "why" prompt.
    fake_client.get_channel = MagicMock(return_value=fake_channel)

    payload = FakeRawReactionActionEvent(
        user_id=111, message_id=999, emoji=_make_emoji("⛔")
    )
    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    assert fake_partial.delete.await_count == 2
    assert sid not in bot._setup_messages


@pytest.mark.asyncio
async def test_followup_timeout_deletes_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)

    fake_channel, fake_partial = _make_fake_channel()
    _install_fake_client(bot, fake_channel)

    fake_send_channel = AsyncMock()
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 12345
    fake_send_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    with patch(
        "app.discord_bot.lifecycle.voice.play_reverie_then_disconnect",
        return_value=True,
    ):
        await bot._run_end_of_session(
            session_id=sid,
            voice_client=MagicMock(spec=discord.VoiceClient, channel=None),
            channel=fake_send_channel,
        )

    watchdog_task = bot._watchdog_tasks[sid]
    with patch("app.discord_bot.lifecycle.asyncio.sleep", return_value=None):
        await watchdog_task

    assert fake_partial.delete.await_count == 2
    assert sid not in bot._setup_messages


@pytest.mark.asyncio
async def test_solo_grace_timeout_deletes_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)

    fake_channel, fake_partial = _make_fake_channel()
    _install_fake_client(bot, fake_channel)

    bot._edit_states[sid] = _EditState(message=AsyncMock(spec=discord.Message))

    await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED
    assert fake_partial.delete.await_count == 2
    assert sid not in bot._setup_messages


@pytest.mark.asyncio
async def test_voice_connect_failure_deletes_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    registry.set_duration(session_id=sid, duration_minutes=10)

    fake_channel, fake_partial = _make_fake_channel()
    _install_fake_client(bot, fake_channel)

    fake_voice_channel = MagicMock(spec=discord.VoiceChannel)
    fake_voice_channel.get_partial_message = MagicMock(return_value=AsyncMock())
    modal = IntentionModal(bot=bot, session_id=sid, voice_channel=fake_voice_channel)
    text_input = modal.intention_field.component
    assert isinstance(text_input, discord.ui.TextInput)
    text_input._value = "will be cancelled"
    inter = AsyncMock()
    inter.response = AsyncMock()
    inter.followup = AsyncMock()

    with patch(
        "app.discord_bot.views.voice.connect", side_effect=Exception("no voice")
    ):
        await modal.on_submit(inter)

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED
    assert fake_partial.delete.await_count == 2
    assert sid not in bot._setup_messages


# ---------------------------------------------------------------------------
# Pending expiry must NOT delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_expiry_does_not_delete_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    fake_channel, fake_partial = _make_fake_channel()
    _install_fake_client(bot, fake_channel)

    await bot._run_pending_expiry(session_id=sid, sleep_seconds=0)

    # get_partial_message was used once, to *edit* the welcome — never to
    # delete either message.
    assert fake_channel.get_partial_message.call_count == 1
    fake_partial.delete.assert_not_awaited()
    assert sid in bot._setup_messages


# ---------------------------------------------------------------------------
# Delete failure is logged at WARNING, flow continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_failure_logged_as_warning(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sid = _seed_with_setup_messages(bot, registry)
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)

    fake_channel, fake_partial = _make_fake_channel()
    fake_partial.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    _install_fake_client(bot, fake_channel)
    bot._edit_states[sid] = _EditState(message=AsyncMock(spec=discord.Message))

    with caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"):
        await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    assert any("Failed to delete setup message" in r.message for r in caplog.records)
    # Cleanup still completed despite the delete failures.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED


@pytest.mark.asyncio
async def test_nudge_delete_failure_logged_as_warning_and_flow_continues(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failure deleting the nudge message specifically (welcome/intention
    delete fine) is logged at WARNING and the rest of cleanup completes."""
    sid = _seed_with_setup_messages(bot, registry, nudge_id=300)
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="x")
    registry.mark_active(session_id=sid)

    partials: dict[int, AsyncMock] = {}

    def _get_partial(message_id: int) -> AsyncMock:
        partial = partials.setdefault(message_id, AsyncMock())
        if message_id == 300:
            partial.delete = AsyncMock(
                side_effect=discord.NotFound(MagicMock(), "gone")
            )
        return partial

    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(side_effect=_get_partial)
    _install_fake_client(bot, fake_channel)
    bot._edit_states[sid] = _EditState(message=AsyncMock(spec=discord.Message))

    with caplog.at_level(logging.WARNING, logger="app.discord_bot.lifecycle"):
        await bot._run_solo_grace(session_id=sid, sleep_seconds=0)

    assert any(
        "Failed to delete setup message 300" in r.message for r in caplog.records
    )
    assert partials[100].delete.await_count == 1
    assert partials[200].delete.await_count == 1
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.CANCELLED
    assert sid not in bot._setup_messages


# ---------------------------------------------------------------------------
# Previous "Time's up" deletion on next session start
# ---------------------------------------------------------------------------


def _make_voice_interaction(channel_id: int = 333) -> Any:
    inter = AsyncMock()
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    inter.channel = channel
    inter.guild_id = 222

    user = MagicMock(spec=discord.Member)
    user.id = 111
    voice_channel = MagicMock()
    voice_channel.id = channel_id
    voice_channel.members = []
    voice_state = MagicMock()
    voice_state.channel = voice_channel
    user.voice = voice_state
    inter.user = user

    inter.response = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_previous_times_up_deleted_on_next_session_start(
    bot: TeaModeBot,
) -> None:
    fake_partial = AsyncMock()
    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(return_value=fake_partial)

    inter = _make_voice_interaction(channel_id=333)
    inter.channel = fake_channel
    inter.channel.id = 333

    bot._channel_cleanup[333] = _ChannelCleanup(times_up_id=5555)

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._handle_teamode(inter)

    fake_channel.get_partial_message.assert_any_call(5555)
    fake_partial.delete.assert_awaited_once()
    assert 333 not in bot._channel_cleanup


@pytest.mark.asyncio
async def test_previous_why_and_reflect_cleaned_up_on_next_session_start(
    bot: TeaModeBot,
) -> None:
    """At the next session start: the previous ⛔ line is deleted and the
    previous Reflect message is edited with its embed removed (content
    untouched)."""
    fake_partials: dict[int, AsyncMock] = {}

    def _get_partial(message_id: int) -> AsyncMock:
        return fake_partials.setdefault(message_id, AsyncMock())

    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(side_effect=_get_partial)

    inter = _make_voice_interaction(channel_id=333)
    inter.channel = fake_channel
    inter.channel.id = 333

    bot._channel_cleanup[333] = _ChannelCleanup(
        times_up_id=5555, reflect_id=6666, why_id=7777
    )

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._handle_teamode(inter)

    fake_partials[5555].delete.assert_awaited_once()
    fake_partials[7777].delete.assert_awaited_once()
    fake_partials[6666].edit.assert_awaited_once_with(embed=None)
    assert 333 not in bot._channel_cleanup


@pytest.mark.asyncio
async def test_no_why_line_only_times_up_and_reflect_handled(
    bot: TeaModeBot,
) -> None:
    """When the facilitator answered ✅ (no ⛔ line recorded), only Time's up
    and Reflect are handled at the next session start."""
    fake_partials: dict[int, AsyncMock] = {}

    def _get_partial(message_id: int) -> AsyncMock:
        return fake_partials.setdefault(message_id, AsyncMock())

    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(side_effect=_get_partial)

    inter = _make_voice_interaction(channel_id=333)
    inter.channel = fake_channel
    inter.channel.id = 333

    bot._channel_cleanup[333] = _ChannelCleanup(times_up_id=5555, reflect_id=6666)

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._handle_teamode(inter)

    fake_partials[5555].delete.assert_awaited_once()
    fake_partials[6666].edit.assert_awaited_once_with(embed=None)
    assert 7777 not in fake_partials
    assert 333 not in bot._channel_cleanup


@pytest.mark.asyncio
async def test_channel_cleanup_failures_logged_as_warning_and_flow_continues(
    bot: TeaModeBot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each cleanup step is independent: a failure on one (Time's up delete,
    ⛔ delete, or Reflect embed-strip) is logged at WARNING and does not
    block the others or the new session from starting."""
    fake_times_up = AsyncMock()
    fake_times_up.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    fake_why = AsyncMock()
    fake_why.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    fake_reflect = AsyncMock()
    fake_reflect.edit = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))

    partials = {5555: fake_times_up, 6666: fake_reflect, 7777: fake_why}
    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.get_partial_message = MagicMock(side_effect=lambda mid: partials[mid])

    inter = _make_voice_interaction(channel_id=333)
    inter.channel = fake_channel
    inter.channel.id = 333

    bot._channel_cleanup[333] = _ChannelCleanup(
        times_up_id=5555, reflect_id=6666, why_id=7777
    )

    with (
        patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()),
        caplog.at_level(logging.WARNING, logger="app.discord_bot.commands"),
    ):
        await bot._handle_teamode(inter)

    assert any(
        "Failed to delete previous Time's up message" in r.message
        for r in caplog.records
    )
    assert any(
        "Failed to delete previous follow-up why message" in r.message
        for r in caplog.records
    )
    assert any(
        "Failed to strip embed from previous Reflect message" in r.message
        for r in caplog.records
    )
    # The new session still started (cleanup entry cleared regardless).
    assert 333 not in bot._channel_cleanup


# ---------------------------------------------------------------------------
# Mentions on the initial timer message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_timer_send_includes_non_bot_mentions(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=25)

    human = MagicMock(spec=discord.Member)
    human.id = 501
    human.bot = False
    human.mention = "<@501>"
    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 1
    bot_member.bot = True
    bot_member.mention = "<@1>"

    fake_voice_channel = MagicMock(spec=discord.VoiceChannel)
    fake_voice_channel.members = [human, bot_member]
    fake_timer_msg = AsyncMock()
    fake_voice_channel.send = AsyncMock(return_value=fake_timer_msg)

    _install_fake_client(bot, None, user_id=1)

    modal = IntentionModal(bot=bot, session_id=sid, voice_channel=fake_voice_channel)
    text_input = modal.intention_field.component
    assert isinstance(text_input, discord.ui.TextInput)
    text_input._value = "focus"

    inter = AsyncMock()
    inter.response = AsyncMock()

    with (
        patch("app.discord_bot.views.voice.connect", return_value=AsyncMock()),
        patch(
            "app.discord_bot.views.asyncio.create_task",
            side_effect=lambda c, **_: c.close(),
        ),
    ):
        await modal.on_submit(inter)

    fake_voice_channel.send.assert_called_once()
    sent_content: str = fake_voice_channel.send.call_args.kwargs["content"]
    assert "<@501>" in sent_content
    assert "<@1>" not in sent_content

    edit_state = bot._edit_states[sid]
    assert edit_state.mention_line == "<@501>"


@pytest.mark.asyncio
async def test_tick_edit_reuses_mention_line_without_reping(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
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

    fake_msg = AsyncMock(spec=discord.Message)
    bot._edit_states[sid] = _EditState(message=fake_msg, mention_line="<@501>")

    await bot._on_countdown_tick(sid, seconds_remaining=30)

    fake_msg.edit.assert_called_once()
    call_kwargs = fake_msg.edit.call_args.kwargs
    assert "<@501>" in call_kwargs["content"]
    assert call_kwargs["allowed_mentions"].users is False


@pytest.mark.asyncio
async def test_participant_prompt_message_id_captured(bot: TeaModeBot) -> None:
    """The Set-Intention prompt's WebhookMessage id is stored alongside the
    welcome message id, via followup.send(..., wait=True)."""
    inter = AsyncMock()
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 333
    inter.channel = channel
    inter.guild_id = 222

    user = MagicMock(spec=discord.Member)
    user.id = 111
    voice_channel = MagicMock()
    voice_channel.id = 333
    voice_channel.members = []
    voice_state = MagicMock()
    voice_state.channel = voice_channel
    user.voice = voice_state
    inter.user = user
    inter.response = AsyncMock()

    fake_intention_msg = AsyncMock()
    fake_intention_msg.id = 7777
    inter.followup.send = AsyncMock(return_value=fake_intention_msg)

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._handle_teamode(inter)

    inter.followup.send.assert_called_once()
    assert inter.followup.send.call_args.kwargs.get("wait") is True

    cur = None
    for sid, setup in bot._setup_messages.items():
        cur = setup
    assert cur is not None
    assert cur.intention_message_id == 7777
