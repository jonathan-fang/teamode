"""Tests for the end-of-session sequence: follow-up buttons, WhyModal, watchdog,
and reaction listener.

All Discord gateway calls are mocked via AsyncMock / MagicMock; no live
gateway is touched.  SQLite uses an in-memory connection backed by the real
schema (no mocking of the persistence layer).
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot import (
    COLORS,
    TeaModeBot,
    WhyModal,
    _END_EMBED_BODY,
    _END_EMBED_TITLE,
    _MSG_NOT_FACILITATOR,
    _MSG_REFLECT_PROMPT,
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
# Helpers
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


def _make_component_interaction(
    custom_id: str,
    user_id: int = 111,
) -> Any:
    """Build a fake component interaction for button clicks."""
    inter = AsyncMock()
    inter.type = discord.InteractionType.component
    inter.data = {"custom_id": custom_id}

    user = MagicMock()
    user.id = user_id
    inter.user = user

    inter.response = AsyncMock()
    return inter


# ---------------------------------------------------------------------------
# End-of-session sequence — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_of_session_sequence_order_and_content(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """_run_end_of_session posts embed, reflect prompt, plays reverie, @-mentions,
    posts follow-up buttons — in that exact order."""
    sid = _seed_followup_session(registry)

    human_member = _make_member(user_id=500, is_bot=False)
    bot_member = _make_member(user_id=1, is_bot=True)
    fake_vc = _make_voice_client(members=[human_member, bot_member])

    fake_channel = AsyncMock()
    fake_followup_msg = AsyncMock(spec=discord.Message)
    fake_followup_msg.id = 99999
    send_results = [AsyncMock(), AsyncMock(), AsyncMock(), fake_followup_msg]
    fake_channel.send = AsyncMock(side_effect=send_results)

    # Capture the coroutine passed to create_task and close it to avoid
    # ResourceWarning about unawaited coroutines.
    captured_coros: list[Any] = []

    def _capture_and_discard(coro: Any) -> MagicMock:
        captured_coros.append(coro)
        return MagicMock()

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

    # Close captured coroutines to suppress ResourceWarning.
    for coro in captured_coros:
        coro.close()

    # send() was called 4 times: embed, reflect prompt, @-mention, follow-up row.
    assert fake_channel.send.call_count == 4

    call_args = fake_channel.send.call_args_list

    # Call 0: end-of-session embed.
    embed_kwargs = call_args[0].kwargs
    assert "embed" in embed_kwargs
    embed: discord.Embed = embed_kwargs["embed"]
    assert embed.title == _END_EMBED_TITLE
    assert embed.description == _END_EMBED_BODY
    assert embed.color == COLORS["end_of_session"]

    # Call 1: reflect prompt (plain text, verbatim).
    reflect_args = call_args[1]
    assert reflect_args.args[0] == _MSG_REFLECT_PROMPT

    # Call 2: @-mention — bot member filtered out.
    mention_args = call_args[2]
    mention_text = mention_args.args[0]
    assert "<@500>" in mention_text
    assert "<@1>" not in mention_text  # bot filtered

    # Call 3: follow-up button row (has view= kwarg).
    followup_kwargs = call_args[3].kwargs
    assert "view" in followup_kwargs
    view: discord.ui.View = followup_kwargs["view"]
    custom_ids = {item.custom_id for item in view.children}  # type: ignore[attr-defined]
    assert f"teamode:{sid}:followup:yes" in custom_ids
    assert f"teamode:{sid}:followup:no" in custom_ids
    assert f"teamode:{sid}:followup:end" in custom_ids

    # Reverie playback must have been called.
    mock_play.assert_called_once_with(fake_vc)

    # Watchdog task scheduled.
    mock_create_task.assert_called_once()

    # Follow-up message stashed.
    assert bot._followup_messages[sid] is fake_followup_msg
    assert fake_followup_msg.id in bot._followup_message_ids


# ---------------------------------------------------------------------------
# @-mention with empty voice channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_of_session_empty_voice_channel(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """When no humans are in the voice channel, the @-mention is 'Time's up!'."""
    sid = _seed_followup_session(registry)

    bot_member = _make_member(user_id=1, is_bot=True)
    fake_vc = _make_voice_client(members=[bot_member])

    fake_channel = AsyncMock()
    fake_followup_msg = AsyncMock(spec=discord.Message)
    fake_followup_msg.id = 88888
    fake_channel.send = AsyncMock(
        side_effect=[AsyncMock(), AsyncMock(), AsyncMock(), fake_followup_msg]
    )

    captured_coros2: list[Any] = []

    def _capture2(coro: Any) -> MagicMock:
        captured_coros2.append(coro)
        return MagicMock()

    with patch("app.bot.voice.play_reverie_then_disconnect", return_value=True):
        with patch("app.bot.asyncio.create_task", side_effect=_capture2):
            await bot._run_end_of_session(
                session_id=sid,
                voice_client=fake_vc,
                channel=fake_channel,
            )

    for coro in captured_coros2:
        coro.close()

    # The @-mention call (index 2) should be the plain "Time's up!" message.
    mention_call = fake_channel.send.call_args_list[2]
    assert mention_call.args[0] == "Time's up!"


# ---------------------------------------------------------------------------
# followup:yes — facilitator click
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_yes_facilitator_marks_completed(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator 'Yes' click marks session completed(1), cancels watchdog, disables buttons."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    # Stash a fake follow-up message and watchdog.
    fake_msg = AsyncMock(spec=discord.Message)
    fake_msg.id = 12345
    bot._followup_messages[sid] = fake_msg
    bot._followup_message_ids.add(12345)

    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    inter = _make_component_interaction(f"teamode:{sid}:followup:yes", user_id=111)

    await bot.on_interaction(inter)

    # mark_completed called with yes.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.COMPLETED

    # Check SQLite.
    row = registry._conn.execute(
        "SELECT completed_intention, followup_note FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == 1
    assert row[1] is None

    # Watchdog cancelled.
    watchdog.cancel.assert_called_once()

    # Ephemeral confirmation sent.
    inter.response.send_message.assert_called_once()
    assert inter.response.send_message.call_args.kwargs.get("ephemeral") is True

    # Buttons disabled (message.edit called with empty view).
    fake_msg.edit.assert_called_once()
    edit_kwargs = fake_msg.edit.call_args.kwargs
    assert "view" in edit_kwargs


# ---------------------------------------------------------------------------
# followup:yes — non-facilitator click
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_yes_non_facilitator_sends_refusal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """A 'Yes' click from a non-facilitator sends the verbatim refusal; no transition."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    inter = _make_component_interaction(
        f"teamode:{sid}:followup:yes",
        user_id=999,  # different user
    )

    await bot.on_interaction(inter)

    # Ephemeral refusal with verbatim text.
    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    embed: discord.Embed = kwargs["embed"]
    assert embed.description == _MSG_NOT_FACILITATOR

    # Session still in FOLLOWUP — no transition.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP


# ---------------------------------------------------------------------------
# followup:no — facilitator click → opens WhyModal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_no_facilitator_opens_why_modal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator 'No' click opens WhyModal; mark_completed NOT called yet."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_msg = AsyncMock(spec=discord.Message)
    fake_msg.id = 12345
    bot._followup_messages[sid] = fake_msg

    fake_watchdog = MagicMock()
    fake_watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = fake_watchdog  # type: ignore[assignment]

    inter = _make_component_interaction(f"teamode:{sid}:followup:no", user_id=111)

    await bot.on_interaction(inter)

    # send_modal called with a WhyModal instance.
    inter.response.send_modal.assert_called_once()
    modal_arg = inter.response.send_modal.call_args.args[0]
    assert isinstance(modal_arg, WhyModal)

    # No transition yet.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP


# ---------------------------------------------------------------------------
# WhyModal.on_submit — with text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_why_modal_submit_with_text(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """WhyModal.on_submit with non-empty text marks completed(0, note=text)."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_msg = AsyncMock(spec=discord.Message)
    # Use a MagicMock for the watchdog; cancel() is synchronous on asyncio.Task.
    fake_watchdog = MagicMock()
    fake_watchdog.cancel = MagicMock()

    modal = WhyModal(
        bot=bot,
        session_id=sid,
        followup_message=fake_msg,
        watchdog_task=fake_watchdog,  # type: ignore[arg-type]
    )

    # Simulate TextInput value.
    text_input = discord.ui.TextInput[discord.ui.Modal](label="What got in the way?")
    text_input._value = "Got distracted by Slack"
    modal.why_field = discord.ui.Label(  # type: ignore[assignment]
        text="What got in the way?",
        component=text_input,
    )

    inter = AsyncMock()
    inter.response = AsyncMock()

    await modal.on_submit(inter)

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.COMPLETED

    row = registry._conn.execute(
        "SELECT completed_intention, followup_note FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == 0
    assert row[1] == "Got distracted by Slack"

    # Watchdog cancel() was called.
    fake_watchdog.cancel.assert_called_once()

    # Ephemeral confirmation.
    inter.response.send_message.assert_called_once()
    assert inter.response.send_message.call_args.kwargs.get("ephemeral") is True

    # Buttons disabled.
    fake_msg.edit.assert_called_once()


# ---------------------------------------------------------------------------
# WhyModal.on_submit — with empty text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_why_modal_submit_with_empty_text(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """WhyModal.on_submit with empty text passes followup_note=None."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_msg = AsyncMock(spec=discord.Message)
    # Use a MagicMock for the watchdog so cancel() doesn't create awaitable tasks.
    fake_watchdog = MagicMock()
    fake_watchdog.cancel = MagicMock()

    modal = WhyModal(
        bot=bot,
        session_id=sid,
        followup_message=fake_msg,
        watchdog_task=fake_watchdog,  # type: ignore[arg-type]
    )

    # Simulate empty TextInput.
    text_input = discord.ui.TextInput[discord.ui.Modal](label="What got in the way?")
    text_input._value = ""
    modal.why_field = discord.ui.Label(  # type: ignore[assignment]
        text="What got in the way?",
        component=text_input,
    )

    inter = AsyncMock()
    inter.response = AsyncMock()

    await modal.on_submit(inter)

    row = registry._conn.execute(
        "SELECT completed_intention, followup_note FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == 0
    assert row[1] is None  # empty string → None


# ---------------------------------------------------------------------------
# followup:end — facilitator click
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_end_facilitator_marks_completed_no_answer(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator 'End early' click marks completed with completed_intention=None."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_msg = AsyncMock(spec=discord.Message)
    fake_msg.id = 55555
    bot._followup_messages[sid] = fake_msg
    bot._followup_message_ids.add(55555)

    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    bot._watchdog_tasks[sid] = watchdog  # type: ignore[assignment]

    inter = _make_component_interaction(f"teamode:{sid}:followup:end", user_id=111)

    await bot.on_interaction(inter)

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.COMPLETED

    row = registry._conn.execute(
        "SELECT completed_intention, followup_note FROM sessions WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] is None  # "ended without recording an answer"
    assert row[1] is None

    watchdog.cancel.assert_called_once()
    inter.response.send_message.assert_called_once()
    assert inter.response.send_message.call_args.kwargs.get("ephemeral") is True
    fake_msg.edit.assert_called_once()


# ---------------------------------------------------------------------------
# 3-minute watchdog fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchdog_fires_marks_followup_timeout(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """When the watchdog fires, mark_followup_timeout is called and buttons disabled.

    Strategy: run _run_end_of_session with asyncio.create_task replaced by
    a synchronous collector, then invoke the watchdog coroutine directly with
    asyncio.sleep patched to return immediately.
    """
    sid = _seed_followup_session(registry, facilitator_id=111)

    fake_channel = AsyncMock()
    fake_vc = _make_voice_client(members=[])
    fake_followup_return = AsyncMock(spec=discord.Message)
    fake_followup_return.id = 77777
    fake_channel.send = AsyncMock(
        side_effect=[AsyncMock(), AsyncMock(), AsyncMock(), fake_followup_return]
    )

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

    # Now run the watchdog coroutine with sleep patched to return immediately.
    with patch("app.bot.asyncio.sleep", return_value=None):
        await captured_coro[0]

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP_TIMEOUT


# ---------------------------------------------------------------------------
# Reaction listener — 👍 on follow-up message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_thumbsup_logged_no_state_change(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 👍 reaction on a follow-up message is logged; no SQLite write, no state change."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    # Register a fake follow-up message id.
    bot._followup_message_ids.add(42000)

    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.message_id = 42000
    payload.user_id = 500
    payload.emoji = MagicMock()
    payload.emoji.__str__ = lambda self: "👍"

    import logging

    with caplog.at_level(logging.INFO, logger="app.bot"):
        await bot.on_raw_reaction_add(payload)

    # Logged at INFO level.
    assert any("👍" in record.message for record in caplog.records)

    # No state transition.
    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP


# ---------------------------------------------------------------------------
# Reaction listener — 👎 on follow-up message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_thumbsdown_logged_no_state_change(
    bot: TeaModeBot,
    registry: SessionRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 👎 reaction on a follow-up message is logged; no state change."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    bot._followup_message_ids.add(43000)

    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.message_id = 43000
    payload.user_id = 600
    payload.emoji = MagicMock()
    payload.emoji.__str__ = lambda self: "👎"

    import logging

    with caplog.at_level(logging.INFO, logger="app.bot"):
        await bot.on_raw_reaction_add(payload)

    assert any("👎" in record.message for record in caplog.records)

    session = registry.get(sid)
    assert session is not None
    assert session.state == SessionState.FOLLOWUP


# ---------------------------------------------------------------------------
# Reaction listener — unrelated emoji ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_other_emoji_ignored(
    bot: TeaModeBot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reactions with emoji other than 👍/👎 produce no log output."""
    bot._followup_message_ids.add(44000)

    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.message_id = 44000
    payload.user_id = 700
    payload.emoji = MagicMock()
    payload.emoji.__str__ = lambda self: "🍵"

    import logging

    with caplog.at_level(logging.INFO, logger="app.bot"):
        await bot.on_raw_reaction_add(payload)

    # Should not have logged anything reaction-related.
    assert not any("Reaction" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Reaction listener — non-follow-up message ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_on_non_followup_message_ignored(
    bot: TeaModeBot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reaction on a message id not in _followup_message_ids is ignored entirely."""
    # No message ids registered.
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.message_id = 99999
    payload.user_id = 800
    payload.emoji = MagicMock()
    payload.emoji.__str__ = lambda self: "👍"

    import logging

    with caplog.at_level(logging.INFO, logger="app.bot"):
        await bot.on_raw_reaction_add(payload)

    assert not any("Reaction" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Watchdog cancellation race: facilitator clicks after watchdog fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_yes_after_watchdog_fires_no_exception(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """If facilitator clicks Yes after the watchdog has already fired (session
    already in FOLLOWUP_TIMEOUT), the handler responds with a graceful ephemeral
    message and no exception escapes."""
    sid = _seed_followup_session(registry, facilitator_id=111)

    # Simulate watchdog having already fired — advance to terminal state.
    registry.mark_followup_timeout(session_id=sid)

    # Also simulate no stash in bot (watchdog cleaned it up).
    # Session is now FOLLOWUP_TIMEOUT; no watchdog task or followup message in bot.

    inter = _make_component_interaction(f"teamode:{sid}:followup:yes", user_id=111)

    # Must not raise.
    await bot.on_interaction(inter)

    # A graceful ephemeral response must have been sent.
    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    # The message is not the facilitator-auth refusal.
    if "embed" in kwargs:
        embed_desc = kwargs["embed"].description
        assert embed_desc != _MSG_NOT_FACILITATOR
