"""Tests for the TeaModeBot._on_countdown_tick callback.

Covers:
  - Edit-skip when the per-session lock is held (in-flight guard).
  - 429 backoff: floor doubles on rate-limit hit, decays back on success.
  - Non-edit-eligible ticks are no-ops (no message.edit call).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.constants import (
    BACKOFF_FLOOR_CAP,
    BACKOFF_FLOOR_DEFAULT,
    MSG_WRAP_UP_NUDGE,
    MSG_WRAP_UP_NUDGE_ONE,
    PHASE_DEEP_FOCUS,
    TIMER_CONTENT,
    WRAP_UP_MINUTES,
)
from app.discord_bot import TeaModeBot
from app.discord_bot.views import COLORS, _EditState, _SetupMessages
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
    registry.set_duration(session_id=session_id, duration_minutes=25)
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

    assert edit_state.backoff_floor == BACKOFF_FLOOR_DEFAULT

    # Simulate a 429 HTTPException from message.edit.
    rate_limit_exc = discord.HTTPException(MagicMock(status=429), "rate limited")
    rate_limit_exc.status = 429
    fake_msg.edit.side_effect = rate_limit_exc

    await bot._on_countdown_tick(session_id, seconds_remaining=30)

    # Backoff floor must have doubled.
    assert edit_state.backoff_floor == BACKOFF_FLOOR_DEFAULT * 2


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
    assert edit_state.backoff_floor == BACKOFF_FLOOR_DEFAULT * 2

    # Second tick, past the (doubled) backoff floor: success → floor back to
    # default. seconds_remaining=0 (the final tick, always edit-eligible)
    # is 30s past the 429, well past the 20s floor, so the gate has cleared.
    fake_msg.edit.side_effect = None
    await bot._on_countdown_tick(session_id, seconds_remaining=0)
    assert edit_state.backoff_floor == BACKOFF_FLOOR_DEFAULT


@pytest.mark.asyncio
async def test_429_backoff_capped_at_maximum(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Repeated 429s do not push the backoff floor above BACKOFF_FLOOR_CAP."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    edit_state = bot._edit_states[session_id]

    rate_limit_exc = discord.HTTPException(MagicMock(status=429), "rate limited")
    rate_limit_exc.status = 429
    fake_msg.edit.side_effect = rate_limit_exc

    # Fire enough 429s to saturate the cap. Each call's seconds_remaining
    # drops well past the current floor so the backoff gate never skips
    # the attempt (skipped attempts wouldn't double the floor).
    for i in range(10):
        await bot._on_countdown_tick(session_id, seconds_remaining=1000 - i * 100)

    assert edit_state.backoff_floor == BACKOFF_FLOOR_CAP


# ---------------------------------------------------------------------------
# Successful edit writes the correct content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_content_format(bot: TeaModeBot, registry: SessionRegistry) -> None:
    """A successful edit sends the exact formatted timer content and embed."""
    session_id, fake_msg = _seed_active_session(registry, bot)

    # 1200s remaining of a 25-min (1500s) session — well inside Deep focus
    # (the 180s Wrap-up window starts at 180s remaining).
    await bot._on_countdown_tick(session_id, seconds_remaining=1200)

    fake_msg.edit.assert_called_once()
    call_kwargs = fake_msg.edit.call_args.kwargs
    assert call_kwargs["content"] == TIMER_CONTENT.format(mmss="20:00")
    embed = call_kwargs["embed"]
    assert embed.color == COLORS["active"]
    field_values = {f.name: f.value for f in embed.fields}
    assert field_values["Intention"] == "test intention"
    assert PHASE_DEEP_FOCUS in embed.description
    # AllowedMentions has no __eq__, so compare the flag that matters.
    assert call_kwargs["allowed_mentions"].users is False


@pytest.mark.asyncio
async def test_edit_at_zero_sends_final_format(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """The final tick at 0 edits the message to 00:00, still in Wrap up."""
    session_id, fake_msg = _seed_active_session(registry, bot)

    await bot._on_countdown_tick(session_id, seconds_remaining=0)

    fake_msg.edit.assert_called_once()
    call_kwargs = fake_msg.edit.call_args.kwargs
    assert call_kwargs["content"] == TIMER_CONTENT.format(mmss="00:00")
    embed = call_kwargs["embed"]
    assert embed.color == COLORS["wrap_up"]
    assert call_kwargs["allowed_mentions"].users is False


# ---------------------------------------------------------------------------
# Wrap-up nudge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nudge_fires_once_at_trigger_for_long_session(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A 25-min session posts the nudge exactly once, at the trigger second."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel
    trigger = WRAP_UP_MINUTES * 60

    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_channel.send.assert_awaited_once_with(
        MSG_WRAP_UP_NUDGE.format(minutes=WRAP_UP_MINUTES)
    )

    # A later tick (still ACTIVE) must not send it again.
    fake_channel.send.reset_mock()
    await bot._on_countdown_tick(session_id, seconds_remaining=trigger - 10)
    fake_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_nudge_never_fires_for_short_session(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A 5-min session (below NUDGE_MIN_DURATION_MINUTES) never nudges."""
    session = registry.create_pending_session(
        guild_id="100",
        text_channel_id="200",
        voice_channel_id="300",
        facilitator_id="111",
    )
    session_id = session.session_id
    registry.set_duration(session_id=session_id, duration_minutes=5)
    registry.set_intention(session_id=session_id, intention="x")
    registry.mark_active(session_id=session_id)

    fake_msg = AsyncMock(spec=discord.Message)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel
    bot._edit_states[session_id] = _EditState(message=fake_msg)

    trigger = WRAP_UP_MINUTES * 60
    for seconds_remaining in range(trigger + 20, -1, -1):
        await bot._on_countdown_tick(session_id, seconds_remaining=seconds_remaining)

    fake_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_nudge_uses_singular_copy_when_wrap_up_minutes_is_one(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """With WRAP_UP_MINUTES patched to 1, the nudge text is the singular
    copy, not the plural template formatted with 1."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel

    with (
        patch("app.discord_bot.timer.WRAP_UP_MINUTES", 1),
        patch("app.timer_format.WRAP_UP_MINUTES", 1),
    ):
        await bot._on_countdown_tick(session_id, seconds_remaining=60)

    fake_channel.send.assert_awaited_once_with(MSG_WRAP_UP_NUDGE_ONE)


@pytest.mark.asyncio
async def test_nudge_uses_plural_copy_at_default_wrap_up_minutes(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """At the default WRAP_UP_MINUTES (3, i.e. >= 2), the nudge text is the
    plural template."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel
    trigger = WRAP_UP_MINUTES * 60

    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_channel.send.assert_awaited_once_with(
        MSG_WRAP_UP_NUDGE.format(minutes=WRAP_UP_MINUTES)
    )


@pytest.mark.asyncio
async def test_nudge_plays_wind_chime_on_voice_client(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """At the nudge tick, the wind chime plays exactly once on the
    session's voice client, and the client is never disconnected."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel

    fake_voice_client = MagicMock(spec=discord.VoiceClient)
    fake_voice_client.is_connected.return_value = True
    fake_voice_client.is_playing.return_value = False
    bot._voice_clients[session_id] = fake_voice_client

    trigger = WRAP_UP_MINUTES * 60
    with patch("app.discord_bot.timer.voice.discord.FFmpegPCMAudio"):
        await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_voice_client.play.assert_called_once()
    fake_voice_client.disconnect.assert_not_called()


@pytest.mark.asyncio
async def test_no_chime_on_tick_without_nudge(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A tick that isn't the nudge trigger never touches the voice client."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel

    fake_voice_client = MagicMock(spec=discord.VoiceClient)
    bot._voice_clients[session_id] = fake_voice_client

    await bot._on_countdown_tick(session_id, seconds_remaining=1200)

    fake_voice_client.play.assert_not_called()


@pytest.mark.asyncio
async def test_no_chime_for_session_below_nudge_min_duration(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A short session (below NUDGE_MIN_DURATION_MINUTES) never nudges and
    never touches the voice client, even at what would be the trigger
    second for a longer session."""
    session = registry.create_pending_session(
        guild_id="100",
        text_channel_id="200",
        voice_channel_id="300",
        facilitator_id="111",
    )
    session_id = session.session_id
    registry.set_duration(session_id=session_id, duration_minutes=5)
    registry.set_intention(session_id=session_id, intention="x")
    registry.mark_active(session_id=session_id)

    fake_msg = AsyncMock(spec=discord.Message)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel
    bot._edit_states[session_id] = _EditState(message=fake_msg)

    fake_voice_client = MagicMock(spec=discord.VoiceClient)
    bot._voice_clients[session_id] = fake_voice_client

    trigger = WRAP_UP_MINUTES * 60
    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_voice_client.play.assert_not_called()


@pytest.mark.asyncio
async def test_nudge_chime_failure_does_not_raise_and_session_continues(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """A not-connected voice client at nudge time logs a WARNING and does
    not raise; the session (and the nudge message) proceeds normally."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel

    fake_voice_client = MagicMock(spec=discord.VoiceClient)
    fake_voice_client.is_connected.return_value = False
    bot._voice_clients[session_id] = fake_voice_client

    trigger = WRAP_UP_MINUTES * 60
    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_voice_client.play.assert_not_called()
    fake_channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_nudge_still_posted_when_voice_client_missing(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """No voice client stashed for the session (e.g. cleaned up already) —
    the nudge message still posts; only the chime is skipped."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel

    trigger = WRAP_UP_MINUTES * 60
    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_nudge_message_id_stored_on_setup_messages(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """The nudge message's id is stashed on the session's _SetupMessages so
    terminal cleanup can delete it."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_nudge_msg = AsyncMock(spec=discord.Message)
    fake_nudge_msg.id = 9999
    fake_channel.send = AsyncMock(return_value=fake_nudge_msg)
    fake_msg.channel = fake_channel
    bot._setup_messages[session_id] = _SetupMessages(
        channel_id=333, welcome_message_id=100, intention_message_id=200
    )

    trigger = WRAP_UP_MINUTES * 60
    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    assert bot._setup_messages[session_id].nudge_message_id == 9999


@pytest.mark.asyncio
async def test_nudge_does_not_fire_when_session_no_longer_active(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """The nudge is skipped if the session has left ACTIVE by fire time
    (e.g. cancelled via solo grace) even though the edit state lingers."""
    session_id, fake_msg = _seed_active_session(registry, bot)
    fake_channel = AsyncMock(spec=discord.TextChannel)
    fake_msg.channel = fake_channel

    registry.mark_cancelled(session_id=session_id)

    trigger = WRAP_UP_MINUTES * 60
    await bot._on_countdown_tick(session_id, seconds_remaining=trigger)

    fake_channel.send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Facilitator field reflects handoff; intention truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facilitator_field_shows_handoff_facilitator(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    session_id, fake_msg = _seed_active_session(registry, bot)
    registry.mark_handoff(session_id=session_id, handoff_facilitator_id="222")

    await bot._on_countdown_tick(session_id, seconds_remaining=1200)

    embed = fake_msg.edit.call_args.kwargs["embed"]
    field_values = {f.name: f.value for f in embed.fields}
    assert field_values["Facilitator"] == "<@222>"


@pytest.mark.asyncio
async def test_long_intention_truncated_in_field(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    session = registry.create_pending_session(
        guild_id="100",
        text_channel_id="200",
        voice_channel_id="300",
        facilitator_id="111",
    )
    session_id = session.session_id
    registry.set_duration(session_id=session_id, duration_minutes=25)
    registry.set_intention(session_id=session_id, intention="x" * 3000)
    registry.mark_active(session_id=session_id)

    fake_msg = AsyncMock(spec=discord.Message)
    bot._edit_states[session_id] = _EditState(message=fake_msg)

    await bot._on_countdown_tick(session_id, seconds_remaining=1200)

    embed = fake_msg.edit.call_args.kwargs["embed"]
    field_values = {f.name: f.value for f in embed.fields}
    assert len(field_values["Intention"]) <= 1024
    assert field_values["Intention"].endswith("…")


def test_started_at_field_shows_start_to_end_range() -> None:
    """The Range field shows the local start and end time as a range."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from app.discord_bot.views import _build_timer_message

    with patch(
        "app.discord_bot.views.TEAMODE_TIMEZONE", ZoneInfo("America/Los_Angeles")
    ):
        _content, embed = _build_timer_message(
            intention="x",
            duration_minutes=25,
            facilitator_id="111",
            started_at=datetime(2026, 1, 15, 23, 50, tzinfo=timezone.utc),
            seconds_remaining=1500,
            mention_line="",
        )

    field_values = {f.name: f.value for f in embed.fields}
    assert field_values["Range"] == "15:50 to 16:15"
