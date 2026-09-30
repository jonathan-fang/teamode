"""Tests for the post-follow-up chaining prompt (Go again / break offer) and
the five-minute break lifecycle.

Covers: chaining prompt posted after ✅ and after ⛔ (never after a
follow-up timeout), Go again delegating to the shared session start with
chain-validity guarding, break start/cancellation/completion, the
post-break Go again button and its expiry, and stale-button refusals.

All Discord gateway calls are mocked via AsyncMock / MagicMock; no live
gateway, real sleep, or ffmpeg is touched.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app import timer_format
from app.config import TEAMODE_TIMEZONE
from app.constants import (
    BREAK_CANCELLED,
    BREAK_MINUTES,
    BREAK_OVER,
    BREAK_STARTED,
    BUTTON_BREAK,
    BUTTON_GO_AGAIN,
    CHAIN_PROMPT,
    MSG_NOT_IN_VOICE,
    MSG_RATE_LIMIT_USER,
    MSG_SESSION_ACTIVE,
    MSG_SESSION_INACTIVE,
)
from app.db import init_db
from app.discord_bot import TeaModeBot
from app.discord_bot.breaks import _BreakState, _ChainState
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_followup_session(registry: SessionRegistry, facilitator_id: int = 111) -> int:
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id=str(facilitator_id),
    )
    sid = session.session_id
    registry.set_duration(session_id=sid, duration_minutes=1)
    registry.set_intention(session_id=sid, intention="test intention")
    registry.mark_active(session_id=sid)
    registry.mark_followup(session_id=sid)
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


def _make_fake_voice_channel(channel_id: int = 333) -> MagicMock:
    """A VoiceChannel mock with async send/get_partial_message wired up."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    channel.send = AsyncMock()
    fake_partial = AsyncMock()
    channel.get_partial_message = MagicMock(return_value=fake_partial)
    return channel


def _install_fake_client(bot: TeaModeBot, channel: Any, user_id: int = 1) -> MagicMock:
    fake_client = MagicMock(spec=discord.Client)
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_client.user = fake_user
    fake_client.get_channel = MagicMock(return_value=channel)
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


def _make_voice_interaction(
    channel_id: int = 333,
    guild_id: int = 222,
    user_id: int = 111,
    channel: Any | None = None,
) -> Any:
    """FakeInteraction that clears all of _start_session's invocation guards."""
    inter = AsyncMock()
    if channel is None:
        channel = MagicMock(spec=discord.VoiceChannel)
        channel.id = channel_id
    inter.channel = channel
    inter.guild_id = guild_id

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    voice_channel = MagicMock()
    voice_channel.id = channel.id
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


def _make_button_interaction(
    session_id: int,
    purpose: str,
    *,
    channel_id: int = 333,
    guild_id: int = 222,
    user_id: int = 111,
    user_voice_channel_id: int | None = 333,
    channel: Any | None = None,
) -> Any:
    """FakeInteraction for a `teamode:<session_id>:<purpose>` button click."""
    inter = AsyncMock()
    inter.type = discord.InteractionType.component
    inter.data = {"custom_id": f"teamode:{session_id}:{purpose}"}

    if channel is None:
        channel = MagicMock(spec=discord.VoiceChannel)
        channel.id = channel_id
    inter.channel = channel
    inter.channel_id = channel.id
    inter.guild_id = guild_id

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    if user_voice_channel_id is not None:
        voice_channel = MagicMock()
        voice_channel.id = user_voice_channel_id
        member = MagicMock(spec=discord.Member)
        member.id = user_id
        member.bot = False
        member.mention = f"<@{user_id}>"
        voice_channel.members = [member]
        voice_state = MagicMock()
        voice_state.channel = voice_channel
        user.voice = voice_state
    else:
        user.voice = None
    inter.user = user

    inter.response = AsyncMock()
    return inter


def _button_map(view: discord.ui.View) -> dict[str, discord.ui.Button[Any]]:
    return {
        b.custom_id: b
        for b in view.children
        if isinstance(b, discord.ui.Button) and b.custom_id is not None
    }


def _capture_and_discard() -> tuple[list[Any], Any]:
    """Same create_task-capturing pattern used in tests/test_bot_followup.py —
    avoids letting a real background task (break sleep, watchdog) run."""
    captured: list[Any] = []

    def _side_effect(coro: Any, **_kwargs: Any) -> MagicMock:
        captured.append(coro)
        t = MagicMock()
        t.cancel = MagicMock()
        t.done = MagicMock(return_value=False)
        return t

    return captured, _side_effect


# ---------------------------------------------------------------------------
# Chaining prompt — posted after ✅ / ⛔, never after follow-up timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_prompt_posted_after_checkmark(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_followup_session(registry, facilitator_id=111)
    bot._reflect_message_ids[sid] = 55555

    channel = _make_fake_voice_channel(channel_id=333)
    prompt_msg = AsyncMock(spec=discord.Message)
    prompt_msg.id = 77777
    channel.send.return_value = prompt_msg
    _install_fake_client(bot, channel, user_id=9)

    payload = FakeRawReactionActionEvent(
        user_id=111, message_id=55555, emoji=_make_emoji("✅")
    )
    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    channel.send.assert_awaited_once()
    args, kwargs = channel.send.call_args
    assert args[0] == CHAIN_PROMPT
    buttons = _button_map(kwargs["view"])
    assert set(buttons) == {f"teamode:{sid}:again", f"teamode:{sid}:break"}
    assert buttons[f"teamode:{sid}:again"].label == BUTTON_GO_AGAIN
    assert buttons[f"teamode:{sid}:break"].label == BUTTON_BREAK

    chain = bot._chain_states[333]
    assert chain.session_id == sid
    assert chain.message_id == 77777
    assert chain.kind == "chain"


@pytest.mark.asyncio
async def test_chain_prompt_posted_after_no_entry_following_why_line(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_followup_session(registry, facilitator_id=111)
    bot._reflect_message_ids[sid] = 66666

    channel = _make_fake_voice_channel(channel_id=333)
    why_msg = AsyncMock(spec=discord.Message)
    why_msg.id = 88888
    prompt_msg = AsyncMock(spec=discord.Message)
    prompt_msg.id = 99999
    channel.send = AsyncMock(side_effect=[why_msg, prompt_msg])
    _install_fake_client(bot, channel, user_id=9)

    payload = FakeRawReactionActionEvent(
        user_id=111, message_id=66666, emoji=_make_emoji("⛔")
    )
    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    assert channel.send.await_count == 2
    second_args = channel.send.call_args_list[1].args
    assert second_args[0] == CHAIN_PROMPT

    chain = bot._chain_states[333]
    assert chain.session_id == sid
    assert chain.message_id == 99999


@pytest.mark.asyncio
async def test_chain_prompt_not_posted_after_followup_timeout(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_followup_session(registry, facilitator_id=111)
    _install_fake_client(bot, _make_fake_voice_channel(channel_id=333), user_id=9)

    fake_vc = MagicMock(spec=discord.VoiceClient)
    fake_vc.channel = MagicMock(spec=discord.VoiceChannel)
    fake_vc.channel.members = []

    end_channel = AsyncMock()
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 10001
    end_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    captured, side_effect = _capture_and_discard()
    with patch(
        "app.discord_bot.lifecycle.voice.play_reverie_then_disconnect",
        return_value=True,
    ):
        with patch(
            "app.discord_bot.tasks.asyncio.create_task", side_effect=side_effect
        ):
            await bot._run_end_of_session(
                session_id=sid, voice_client=fake_vc, channel=end_channel
            )

    with patch("app.discord_bot.lifecycle.asyncio.sleep", return_value=None):
        await captured[0]

    assert bot._chain_states == {}


# ---------------------------------------------------------------------------
# Go again
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_go_again_routes_through_shared_start_session(bot: TeaModeBot) -> None:
    bot._chain_states[333] = _ChainState(session_id=42, channel_id=333, message_id=1)
    inter = _make_button_interaction(42, "again", channel_id=333, user_id=999)

    with patch.object(bot, "_start_session", new=AsyncMock()) as mock_start:
        await bot.on_interaction(inter)

    mock_start.assert_awaited_once_with(inter)


@pytest.mark.asyncio
async def test_go_again_non_facilitator_voice_member_becomes_facilitator(
    bot: TeaModeBot, conn: sqlite3.Connection, registry: SessionRegistry
) -> None:
    """Any voice-channel member may click Go again — the clicker becomes
    facilitator of the new session, regardless of who ran the old one."""
    old_sid = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    ).session_id
    registry.mark_cancelled(session_id=old_sid)  # terminal — clears guard 3

    bot._chain_states[333] = _ChainState(
        session_id=old_sid, channel_id=333, message_id=1
    )
    inter = _make_button_interaction(old_sid, "again", channel_id=333, user_id=999)

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot.on_interaction(inter)

    cur = conn.execute("SELECT facilitator_id FROM sessions ORDER BY id DESC LIMIT 1")
    assert cur.fetchone()[0] == "999"
    inter.response.send_message.assert_called_once()
    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is not True


@pytest.mark.asyncio
async def test_go_again_rate_limited_gets_refusal_and_creates_no_session(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        for i in range(3):
            inter = _make_voice_interaction(channel_id=1000 + i, user_id=555)
            await bot._start_session(inter)

    rows_before = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    bot._chain_states[999] = _ChainState(session_id=42, channel_id=999, message_id=1)
    go_inter = _make_button_interaction(
        42, "again", channel_id=999, user_id=555, user_voice_channel_id=999
    )

    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot.on_interaction(go_inter)

    go_inter.response.send_message.assert_called_once()
    call_kwargs = go_inter.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    embed: discord.Embed = call_kwargs["embed"]
    prefix, _, _ = MSG_RATE_LIMIT_USER.partition("{seconds}")
    assert embed.description is not None
    assert embed.description.startswith(prefix)

    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == rows_before


@pytest.mark.asyncio
async def test_go_again_with_session_active_in_channel_gets_refusal(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id="111",
    )
    bot._chain_states[333] = _ChainState(session_id=999, channel_id=333, message_id=1)
    inter = _make_button_interaction(999, "again", channel_id=333, user_id=222)

    await bot.on_interaction(inter)

    call_kwargs = inter.response.send_message.call_args.kwargs
    embed: discord.Embed = call_kwargs["embed"]
    assert embed.description == MSG_SESSION_ACTIVE


@pytest.mark.asyncio
async def test_go_again_no_chain_state_is_refused_as_stale(bot: TeaModeBot) -> None:
    inter = _make_button_interaction(42, "again", channel_id=333)
    await bot.on_interaction(inter)

    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs["embed"].description == MSG_SESSION_INACTIVE


@pytest.mark.asyncio
async def test_go_again_mismatched_session_id_is_refused_as_stale(
    bot: TeaModeBot,
) -> None:
    bot._chain_states[333] = _ChainState(session_id=1, channel_id=333, message_id=1)
    inter = _make_button_interaction(2, "again", channel_id=333)

    await bot.on_interaction(inter)

    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs["embed"].description == MSG_SESSION_INACTIVE
    # Untouched — a stale click changes nothing.
    assert 333 in bot._chain_states


# ---------------------------------------------------------------------------
# Break — start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_break_posts_started_message_and_clears_chain(
    bot: TeaModeBot,
) -> None:
    channel = _make_fake_voice_channel(channel_id=333)
    _install_fake_client(bot, channel, user_id=9)
    bot._chain_states[333] = _ChainState(
        session_id=42, channel_id=333, message_id=555, kind="chain"
    )

    started_msg = AsyncMock(spec=discord.Message)
    started_msg.id = 8000
    channel.send.return_value = started_msg

    fixed_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    inter = _make_button_interaction(
        42, "break", channel_id=333, user_id=555, channel=channel
    )

    captured, side_effect = _capture_and_discard()
    with patch("app.discord_bot.breaks._now", return_value=fixed_now):
        with patch(
            "app.discord_bot.tasks.asyncio.create_task", side_effect=side_effect
        ):
            await bot.on_interaction(inter)

    inter.response.defer.assert_awaited_once()

    channel.send.assert_awaited_once()
    text = channel.send.call_args.args[0]
    expected_hhmm = timer_format.format_hhmm(
        fixed_now + timedelta(minutes=BREAK_MINUTES), TEAMODE_TIMEZONE
    )
    assert text == BREAK_STARTED.format(hhmm=expected_hhmm)

    # Chain state cleared and its buttons disabled via a channel edit.
    assert 333 not in bot._chain_states
    channel.get_partial_message.assert_called_once_with(555)
    fake_partial = channel.get_partial_message.return_value
    fake_partial.edit.assert_awaited_once()
    disabled_view = fake_partial.edit.call_args.kwargs["view"]
    assert all(b.disabled for b in disabled_view.children)

    # Break state recorded.
    assert bot._break_states[333].session_id == 42
    assert bot._break_states[333].message_id == 8000

    # No voice status set for a break.
    channel.edit.assert_not_called()

    for coro in captured:
        coro.close()


@pytest.mark.asyncio
async def test_break_click_not_in_voice_is_refused(bot: TeaModeBot) -> None:
    bot._chain_states[333] = _ChainState(session_id=42, channel_id=333, message_id=1)
    inter = _make_button_interaction(
        42, "break", channel_id=333, user_voice_channel_id=None
    )

    await bot.on_interaction(inter)

    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs["embed"].description == MSG_NOT_IN_VOICE
    # A refused break click leaves a still-valid chain state untouched.
    assert 333 in bot._chain_states


@pytest.mark.asyncio
async def test_break_click_no_chain_state_is_refused_as_stale(bot: TeaModeBot) -> None:
    inter = _make_button_interaction(42, "break", channel_id=333)
    await bot.on_interaction(inter)

    call_kwargs = inter.response.send_message.call_args.kwargs
    assert call_kwargs["embed"].description == MSG_SESSION_INACTIVE


# ---------------------------------------------------------------------------
# Break — cancellation by a new session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teamode_during_break_cancels_it(bot: TeaModeBot) -> None:
    channel = _make_fake_voice_channel(channel_id=333)
    _install_fake_client(bot, channel, user_id=9)

    task = MagicMock()
    task.done = MagicMock(return_value=False)
    task.cancel = MagicMock()
    bot._break_states[333] = _BreakState(
        task=task,
        message_id=444,
        end_time=datetime.now(timezone.utc),
        session_id=1,
    )

    inter = _make_voice_interaction(channel_id=333, user_id=111, channel=channel)
    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._start_session(inter)

    task.cancel.assert_called_once()
    channel.get_partial_message.assert_called_once_with(444)
    fake_partial = channel.get_partial_message.return_value
    fake_partial.edit.assert_awaited_once_with(content=BREAK_CANCELLED)
    assert 333 not in bot._break_states


@pytest.mark.asyncio
async def test_teamode_new_session_clears_stale_chain_prompt(bot: TeaModeBot) -> None:
    channel = _make_fake_voice_channel(channel_id=333)
    _install_fake_client(bot, channel, user_id=9)
    bot._chain_states[333] = _ChainState(session_id=1, channel_id=333, message_id=555)

    inter = _make_voice_interaction(channel_id=333, user_id=111, channel=channel)
    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot._start_session(inter)

    assert 333 not in bot._chain_states
    channel.get_partial_message.assert_called_once_with(555)
    channel.get_partial_message.return_value.edit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Break — completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_break_completion_plays_reverie_and_posts_go_again(
    bot: TeaModeBot,
) -> None:
    channel = _make_fake_voice_channel(channel_id=333)
    _install_fake_client(bot, channel, user_id=9)

    over_msg = AsyncMock(spec=discord.Message)
    over_msg.id = 9999
    channel.send.return_value = over_msg

    fake_voice_client = MagicMock(spec=discord.VoiceClient)

    captured, side_effect = _capture_and_discard()
    with patch("app.discord_bot.breaks.asyncio.sleep", new=AsyncMock()):
        with patch(
            "app.discord_bot.breaks.voice.connect",
            new=AsyncMock(return_value=fake_voice_client),
        ) as mock_connect:
            with patch(
                "app.discord_bot.breaks.voice.play_reverie_then_disconnect",
                new=AsyncMock(return_value=True),
            ) as mock_play:
                with patch(
                    "app.discord_bot.tasks.asyncio.create_task", side_effect=side_effect
                ):
                    await bot._run_break(
                        channel_id=333, session_id=42, voice_channel=channel
                    )

    mock_connect.assert_awaited_once_with(channel)
    mock_play.assert_awaited_once_with(fake_voice_client)

    channel.send.assert_awaited_once()
    args, kwargs = channel.send.call_args
    assert args[0] == BREAK_OVER
    buttons = _button_map(kwargs["view"])
    assert set(buttons) == {"teamode:42:again"}
    assert buttons["teamode:42:again"].label == BUTTON_GO_AGAIN

    chain = bot._chain_states[333]
    assert chain.kind == "post_break"
    assert chain.session_id == 42
    assert chain.message_id == 9999
    assert chain.timeout_task is not None

    for coro in captured:
        coro.close()


@pytest.mark.asyncio
async def test_go_again_timeout_disables_post_break_button(bot: TeaModeBot) -> None:
    channel = _make_fake_voice_channel(channel_id=333)
    _install_fake_client(bot, channel, user_id=9)
    bot._chain_states[333] = _ChainState(
        session_id=42, channel_id=333, message_id=9999, kind="post_break"
    )

    with patch("app.discord_bot.breaks.asyncio.sleep", new=AsyncMock()):
        await bot._run_go_again_timeout(channel_id=333)

    assert 333 not in bot._chain_states
    channel.get_partial_message.assert_called_once_with(9999)
    disabled_view = channel.get_partial_message.return_value.edit.call_args.kwargs[
        "view"
    ]
    assert disabled_view.children[0].disabled is True


@pytest.mark.asyncio
async def test_go_again_click_before_timeout_starts_session(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    timeout_task = MagicMock()
    timeout_task.done = MagicMock(return_value=False)
    timeout_task.cancel = MagicMock()
    bot._chain_states[333] = _ChainState(
        session_id=42,
        channel_id=333,
        message_id=9999,
        kind="post_break",
        timeout_task=timeout_task,
    )

    inter = _make_button_interaction(42, "again", channel_id=333, user_id=777)
    with patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()):
        await bot.on_interaction(inter)

    # The pending timeout is cancelled once the new session clears the chain.
    timeout_task.cancel.assert_called_once()

    cur = conn.execute("SELECT facilitator_id FROM sessions ORDER BY id DESC LIMIT 1")
    assert cur.fetchone()[0] == "777"
