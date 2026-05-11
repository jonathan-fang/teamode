"""Tests for the reactions-authoritative end-of-session flow.

Covers: post-zero sequence (Session-complete + Reflect embeds, reverie,
add_reaction), on_raw_reaction_add (facilitator ✅/⛔, non-facilitator,
bot-own, unrelated emoji, unrelated message), 3-minute watchdog, and
timer-pick auto-disable.

All Discord gateway calls are mocked via AsyncMock / MagicMock; no live
gateway is touched.  SQLite uses an in-memory connection backed by the real
schema (no mocking of the persistence layer).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot import (
    COLORS,
    TeaModeBot,
    _END_EMBED_BODY,
    _END_EMBED_TITLE,
)
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
# Helpers / fake objects
# ---------------------------------------------------------------------------


def _seed_followup_session(registry: SessionRegistry, facilitator_id: int = 111) -> int:
    """Create a session advanced to FOLLOWUP state; return session_id."""
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


def _make_member(user_id: int = 999, *, is_bot: bool = False) -> MagicMock:
    """Build a fake discord.Member."""
    m = MagicMock(spec=discord.Member)
    m.id = user_id
    m.bot = is_bot
    m.mention = f"<@{user_id}>"
    return m


def _make_voice_client(members: list[Any] | None = None) -> MagicMock:
    """Build a fake discord.VoiceClient whose .channel.members is *members*."""
    vc = MagicMock(spec=discord.VoiceClient)
    fake_channel = MagicMock(spec=discord.VoiceChannel)
    fake_channel.members = members or []
    vc.channel = fake_channel
    return vc


@dataclass
class FakeRawReactionActionEvent:
    """Minimal stand-in for discord.RawReactionActionEvent."""

    user_id: int
    message_id: int
    emoji: Any
    channel_id: int = 333
    guild_id: int = 222


def _make_emoji(text: str) -> MagicMock:
    """Build a fake emoji whose str() returns *text*."""
    e = MagicMock()
    e.__str__ = MagicMock(return_value=text)
    return e


def _install_fake_client_user(bot: TeaModeBot, user_id: int) -> MagicMock:
    """Replace bot.client with a MagicMock that has .user.id == user_id.

    discord.Client.user is a read-only property so we cannot assign it directly
    in tests.  Swapping out the whole client object is simpler than patching the
    property descriptor on the class (which would affect all Client instances in
    the same process).

    Returns the fake client so callers can further configure get_channel etc.
    """
    fake_client = MagicMock(spec=discord.Client)
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_client.user = fake_user
    bot.client = fake_client  # type: ignore[assignment]
    return fake_client


# ---------------------------------------------------------------------------
# End-of-session sequence — happy path (non-bot voice member present)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_of_session_sequence_happy_path(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Post-zero sequence: two sends (Session-complete then Reflect), reverie,
    add_reaction ✅ then ⛔, reflect-message-id stored, watchdog created."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    human_member = _make_member(user_id=500, is_bot=False)
    bot_member = _make_member(user_id=1, is_bot=True)
    fake_vc = _make_voice_client(members=[human_member, bot_member])

    # Swap out bot.client with a fake so .user.id is settable.
    _install_fake_client_user(bot, user_id=1)

    fake_channel = AsyncMock()
    fake_session_complete_msg = AsyncMock(spec=discord.Message)
    fake_session_complete_msg.id = 11111
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 22222
    fake_channel.send = AsyncMock(
        side_effect=[fake_session_complete_msg, fake_reflect_msg]
    )

    captured_coros: list[Any] = []

    def _capture_and_discard(coro: Any) -> MagicMock:
        captured_coros.append(coro)
        t = MagicMock()
        t.cancel = MagicMock()
        return t

    with patch(
        "app.bot.voice.play_reverie_then_disconnect", return_value=True
    ) as mock_play:
        with patch(
            "app.bot.asyncio.create_task", side_effect=_capture_and_discard
        ) as mock_create_task:
            await bot._run_end_of_session(
                session_id=sid,
                voice_client=fake_vc,
                channel=fake_channel,
            )

    for coro in captured_coros:
        coro.close()

    # Exactly two channel.send calls.
    assert fake_channel.send.call_count == 2

    call_args = fake_channel.send.call_args_list

    # Call 0: Session-complete embed with @-mention content.
    first_kwargs = call_args[0].kwargs
    assert "content" in first_kwargs
    assert "<@500>" in first_kwargs["content"]
    assert "<@1>" not in first_kwargs["content"]
    assert "Time's up," in first_kwargs["content"]
    assert "embed" in first_kwargs
    embed: discord.Embed = first_kwargs["embed"]
    assert embed.title == _END_EMBED_TITLE
    assert embed.description == f"## {_END_EMBED_BODY}"
    assert embed.color == COLORS["end_of_session"]

    # Call 1: Reflect embed with facilitator prompt.
    second_kwargs = call_args[1].kwargs
    assert "content" in second_kwargs
    reflect_content: str = second_kwargs["content"]
    assert reflect_content == "[Follow-up] React ✅ if you finished, ⛔ if not."
    assert "embed" in second_kwargs
    reflect_embed: discord.Embed = second_kwargs["embed"]
    assert reflect_embed.title == "🌿 [Reflect]"
    assert reflect_embed.color == COLORS["end_of_session"]

    # Reverie was awaited between the two sends.
    mock_play.assert_called_once_with(fake_vc)

    # add_reaction called twice: ✅ then ⛔.
    assert fake_reflect_msg.add_reaction.call_count == 2
    add_calls = fake_reflect_msg.add_reaction.call_args_list
    assert add_calls[0].args[0] == "✅"
    assert add_calls[1].args[0] == "⛔"

    # Reflect message id stored.
    assert bot._reflect_message_ids[sid] == 22222

    # Watchdog created.
    mock_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# End-of-session sequence — empty voice channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_of_session_empty_voice_channel(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """When no humans are in voice, first send content is exactly 'Time's up!'."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    bot_member = _make_member(user_id=1, is_bot=True)
    fake_vc = _make_voice_client(members=[bot_member])
    _install_fake_client_user(bot, user_id=1)

    fake_channel = AsyncMock()
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 33333
    fake_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    captured_coros: list[Any] = []

    def _cap(coro: Any) -> MagicMock:
        captured_coros.append(coro)
        return MagicMock()

    with patch("app.bot.voice.play_reverie_then_disconnect", return_value=True):
        with patch("app.bot.asyncio.create_task", side_effect=_cap):
            await bot._run_end_of_session(
                session_id=sid,
                voice_client=fake_vc,
                channel=fake_channel,
            )

    for coro in captured_coros:
        coro.close()

    first_content = fake_channel.send.call_args_list[0].kwargs["content"]
    assert first_content == "Time's up!"


# ---------------------------------------------------------------------------
# Reverie failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_of_session_reverie_failure_logs_warning(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When reverie returns False, a WARNING is logged and Reflect is still sent."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_vc = _make_voice_client(members=[])
    _install_fake_client_user(bot, user_id=99)

    fake_channel = AsyncMock()
    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 44444
    fake_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    captured_coros: list[Any] = []

    def _cap(coro: Any) -> MagicMock:
        captured_coros.append(coro)
        return MagicMock()

    with caplog.at_level(logging.WARNING, logger="app.bot"):
        with patch("app.bot.voice.play_reverie_then_disconnect", return_value=False):
            with patch("app.bot.asyncio.create_task", side_effect=_cap):
                await bot._run_end_of_session(
                    session_id=sid,
                    voice_client=fake_vc,
                    channel=fake_channel,
                )

    for coro in captured_coros:
        coro.close()

    # WARNING logged.
    assert any("Reverie playback failed" in r.message for r in caplog.records)

    # Reflect message was still sent (second send).
    assert fake_channel.send.call_count == 2
    second_kwargs = fake_channel.send.call_args_list[1].kwargs
    assert "embed" in second_kwargs
    assert second_kwargs["embed"].title == "🌿 [Reflect]"


# ---------------------------------------------------------------------------
# Facilitator ✅ reaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facilitator_checkmark_marks_completed_1(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator ✅ reaction: mark_completed(1), watchdog cancelled, id popped."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    # Set up state as if post-zero sequence ran.
    bot._reflect_message_ids[sid] = 55555
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    _install_fake_client_user(bot, user_id=9)

    payload = FakeRawReactionActionEvent(
        user_id=111,
        message_id=55555,
        emoji=_make_emoji("✅"),
    )

    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.COMPLETED

    row = registry._conn.execute(
        "SELECT completed_intention, followup_note FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == 1
    assert row[1] is None

    # Watchdog cancelled.
    watchdog.cancel.assert_called_once()

    # Reflect-message id popped.
    assert sid not in bot._reflect_message_ids


# ---------------------------------------------------------------------------
# Facilitator ⛔ reaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facilitator_no_entry_marks_completed_0_and_posts_why(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator ⛔: mark_completed(0), watchdog cancelled, 'why' prompt sent."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    bot._reflect_message_ids[sid] = 66666
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    fake_client = _install_fake_client_user(bot, user_id=9)

    fake_channel = AsyncMock()
    fake_client.get_channel = MagicMock(return_value=fake_channel)

    payload = FakeRawReactionActionEvent(
        user_id=111,
        message_id=66666,
        emoji=_make_emoji("⛔"),
    )

    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.COMPLETED

    row = registry._conn.execute(
        "SELECT completed_intention, followup_note FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == 0
    assert row[1] is None

    watchdog.cancel.assert_called_once()
    assert sid not in bot._reflect_message_ids

    # "Why" prompt was sent.
    fake_channel.send.assert_awaited_once()
    why_text: str = fake_channel.send.call_args.args[0]
    assert "<@111>" in why_text
    assert "share what got in the way" in why_text


# ---------------------------------------------------------------------------
# Non-facilitator reaction — logged only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_facilitator_reaction_logged_only(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-facilitator ✅: no mark_completed, watchdog untouched, id still present."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    bot._reflect_message_ids[sid] = 77777
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    _install_fake_client_user(bot, user_id=9)

    payload = FakeRawReactionActionEvent(
        user_id=999,  # not the facilitator
        message_id=77777,
        emoji=_make_emoji("✅"),
    )

    with caplog.at_level(logging.INFO, logger="app.bot"):
        await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    # No state transition.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP

    # Watchdog not cancelled.
    watchdog.cancel.assert_not_called()

    # Reflect-message id still present.
    assert sid in bot._reflect_message_ids

    # INFO log emitted.
    assert any("Non-facilitator reaction" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Bot's own pre-populated reactions are ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_own_reaction_ignored(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Reactions from the bot itself are silently ignored."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    bot._reflect_message_ids[sid] = 88888
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    _install_fake_client_user(bot, user_id=42)  # bot's own id

    payload = FakeRawReactionActionEvent(
        user_id=42,  # same as bot
        message_id=88888,
        emoji=_make_emoji("✅"),
    )

    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    # No state change.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP

    watchdog.cancel.assert_not_called()
    assert sid in bot._reflect_message_ids


# ---------------------------------------------------------------------------
# Unrelated emoji on the Reflect message is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_emoji_on_reflect_message_ignored(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """An emoji like 🎉 from any participant on the Reflect message is ignored."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    bot._reflect_message_ids[sid] = 99990
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    _install_fake_client_user(bot, user_id=9)

    payload = FakeRawReactionActionEvent(
        user_id=111,
        message_id=99990,
        emoji=_make_emoji("🎉"),
    )

    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP

    watchdog.cancel.assert_not_called()
    assert sid in bot._reflect_message_ids


# ---------------------------------------------------------------------------
# Reaction on a non-session message is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_on_non_session_message_ignored(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """A reaction on a message id not in _reflect_message_ids returns immediately."""
    # No reflect message ids registered.
    _install_fake_client_user(bot, user_id=9)

    payload = FakeRawReactionActionEvent(
        user_id=111,
        message_id=12345,  # unknown
        emoji=_make_emoji("✅"),
    )

    # Should return without raising.
    await bot.on_raw_reaction_add(payload)  # type: ignore[arg-type]

    # Nothing in registry since we never seeded.
    assert len(bot._reflect_message_ids) == 0


# ---------------------------------------------------------------------------
# 3-minute watchdog fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchdog_fires_marks_followup_timeout(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """When the watchdog fires, mark_followup_timeout is called and id is popped."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_channel = AsyncMock()
    fake_vc = _make_voice_client(members=[])
    _install_fake_client_user(bot, user_id=9)

    fake_reflect_msg = AsyncMock(spec=discord.Message)
    fake_reflect_msg.id = 10001
    fake_channel.send = AsyncMock(side_effect=[AsyncMock(), fake_reflect_msg])

    captured_coro: list[Any] = []

    def _capture_task(coro: Any) -> MagicMock:
        captured_coro.append(coro)
        t = MagicMock()
        t.cancel = MagicMock()
        return t

    with patch("app.bot.voice.play_reverie_then_disconnect", return_value=True):
        with patch("app.bot.asyncio.create_task", side_effect=_capture_task):
            await bot._run_end_of_session(
                session_id=sid,
                voice_client=fake_vc,
                channel=fake_channel,
            )

    assert len(captured_coro) == 1

    # Run the watchdog coroutine with sleep patched to return immediately.
    with patch("app.bot.asyncio.sleep", return_value=None):
        await captured_coro[0]

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP_TIMEOUT

    # Reflect-message id popped.
    assert sid not in bot._reflect_message_ids


# ---------------------------------------------------------------------------
# Timer-pick auto-disable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timer_pick_disables_buttons(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """After a timer-pick click, the three timer buttons are disabled."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="444",
        facilitator_id="111",
    )
    sid = session.session_id

    # Build three enabled Button objects for the fake view.
    btn_10: discord.ui.Button[discord.ui.View] = discord.ui.Button(
        label="10 min",
        custom_id=f"teamode:{sid}:timer:10",
        style=discord.ButtonStyle.secondary,
    )
    btn_25: discord.ui.Button[discord.ui.View] = discord.ui.Button(
        label="25 min",
        custom_id=f"teamode:{sid}:timer:25",
        style=discord.ButtonStyle.secondary,
    )
    btn_50: discord.ui.Button[discord.ui.View] = discord.ui.Button(
        label="50 min",
        custom_id=f"teamode:{sid}:timer:50",
        style=discord.ButtonStyle.secondary,
    )

    fake_view = discord.ui.View()
    fake_view.add_item(btn_10)
    fake_view.add_item(btn_25)
    fake_view.add_item(btn_50)

    fake_message = AsyncMock(spec=discord.Message)
    fake_message.edit = AsyncMock()

    inter = AsyncMock()
    inter.type = discord.InteractionType.component
    inter.data = {"custom_id": f"teamode:{sid}:timer:25"}

    user = MagicMock()
    user.id = 111
    inter.user = user

    voice_channel = MagicMock(spec=discord.VoiceChannel)
    inter.channel = voice_channel
    inter.message = fake_message

    inter.response = AsyncMock()

    with patch("app.bot.discord.ui.View.from_message", return_value=fake_view):
        await bot.on_interaction(inter)

    # All buttons are now disabled.
    for child in fake_view.children:
        assert isinstance(child, discord.ui.Button)
        assert child.disabled is True

    # message.edit was awaited.
    fake_message.edit.assert_awaited_once()
