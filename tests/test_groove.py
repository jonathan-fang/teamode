"""Tests for Groove mode (/groove): text-channel sessions with host-machine chimes."""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app import local_audio, voice
from app.cleanup import is_delete_eligible
from app.config import _parse_flag
from app.constants import (
    END_OF_SESSION_NO_MENTION,
    GROOVE_END_PING,
    MSG_GROOVE_NO_HANDOFF,
    MSG_PARTICIPANT_PROMPT,
    MSG_WRONG_CHANNEL,
    STATS_SECTION_GROOVE,
    STATS_SECTION_SERVER,
    WRAP_UP_MINUTES,
)
from app.db import (
    fetch_guild_stats_rows,
    fetch_session_participants,
    fetch_user_stats_rows,
    init_db,
)
from app.discord_bot import TeaModeBot
from app.discord_bot.breaks import _ChainState
from app.discord_bot.views import IntentionModal, _EditState
from app.session import Session, SessionMode, SessionRegistry, SessionState

# ---------------------------------------------------------------------------
# Fixtures and helpers
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


def _close_coro(coro: Any, **_kwargs: Any) -> MagicMock:
    """create_task stand-in: close the coroutine so it never runs or warns."""
    coro.close()
    return MagicMock()


def _make_text_interaction(
    *, channel_id: int = 444, user_id: int = 111, in_voice: bool = False
) -> Any:
    """A FakeInteraction from a plain TextChannel; the user is not in voice
    unless *in_voice* (then in some other voice channel)."""
    inter = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    inter.channel = channel
    inter.guild_id = 222
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    if in_voice:
        user.voice = MagicMock()
        user.voice.channel = MagicMock()
        user.voice.channel.id = 999
    else:
        user.voice = None
    inter.user = user
    inter.response = AsyncMock()
    return inter


def _seed_groove(
    registry: SessionRegistry,
    *,
    channel_id: str = "444",
    state: SessionState = SessionState.PENDING,
) -> int:
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id=channel_id,
        voice_channel_id=channel_id,
        facilitator_id="111",
        mode=SessionMode.GROOVE,
    )
    sid = session.session_id
    if state == SessionState.PENDING:
        return sid
    registry.set_duration(session_id=sid, duration_minutes=25)
    registry.set_intention(session_id=sid, intention="write")
    if state == SessionState.INTENTION_SET:
        return sid
    registry.mark_active(session_id=sid)
    if state == SessionState.ACTIVE:
        return sid
    registry.mark_followup(session_id=sid)
    return sid


def _get(registry: SessionRegistry, sid: int) -> Session:
    session = registry.get(sid)
    assert session is not None
    return session


def _seed_row(
    conn: sqlite3.Connection, *, guild_id: str, mode: str, duration: int = 25
) -> None:
    conn.execute(
        "INSERT INTO sessions (guild_id, text_channel_id, voice_channel_id,"
        " facilitator_id, started_at, duration_minutes, status, mode)"
        " VALUES (?, '1', '1', '111', '2026-11-05T12:00:00+00:00', ?,"
        " 'completed', ?)",
        (guild_id, duration, mode),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# app.local_audio
# ---------------------------------------------------------------------------


def _fake_proc(returncode: int) -> Any:
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    return proc


@pytest.mark.asyncio
async def test_local_play_runs_ffplay_and_reports_success() -> None:
    spawn = AsyncMock(return_value=_fake_proc(0))
    with patch("app.local_audio.config.TEAMODE_GROOVE_LOCAL_AUDIO", True):
        ok = await local_audio.play(voice.REVERIE_PATH, spawn=spawn)
    assert ok is True
    args = spawn.call_args.args
    assert args == (*local_audio.FFPLAY_ARGS, str(voice.REVERIE_PATH))


@pytest.mark.asyncio
async def test_local_play_skipped_when_disabled() -> None:
    spawn = AsyncMock()
    with patch("app.local_audio.config.TEAMODE_GROOVE_LOCAL_AUDIO", False):
        ok = await local_audio.play(voice.REVERIE_PATH, spawn=spawn)
    assert ok is False
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_local_play_missing_ffplay_returns_false() -> None:
    spawn = AsyncMock(side_effect=FileNotFoundError("ffplay"))
    with patch("app.local_audio.config.TEAMODE_GROOVE_LOCAL_AUDIO", True):
        ok = await local_audio.play(voice.REVERIE_PATH, spawn=spawn)
    assert ok is False


@pytest.mark.asyncio
async def test_local_play_nonzero_exit_returns_false() -> None:
    spawn = AsyncMock(return_value=_fake_proc(1))
    with patch("app.local_audio.config.TEAMODE_GROOVE_LOCAL_AUDIO", True):
        ok = await local_audio.play(voice.WIND_CHIME_PATH, spawn=spawn)
    assert ok is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", True), ("  ", True), ("1", True), ("on", True), ("0", False), ("OFF", False)],
)
def test_parse_flag(raw: str, expected: bool) -> None:
    assert _parse_flag(raw, default=True) is expected


# ---------------------------------------------------------------------------
# DB and registry
# ---------------------------------------------------------------------------


def test_migration_adds_mode_to_old_schema_and_is_idempotent(tmp_path: Any) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(str(path))
    old.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " guild_id TEXT NOT NULL, text_channel_id TEXT NOT NULL,"
        " voice_channel_id TEXT NOT NULL, facilitator_id TEXT NOT NULL,"
        " started_at TEXT, duration_minutes INTEGER, intention TEXT,"
        " ended_at TEXT, completed_intention INTEGER, followup_note TEXT,"
        " status TEXT NOT NULL, handoff_facilitator_id TEXT)"
    )
    old.execute(
        "INSERT INTO sessions (guild_id, text_channel_id, voice_channel_id,"
        " facilitator_id, status) VALUES ('1', '1', '1', '1', 'completed')"
    )
    old.commit()
    old.close()

    init_db(path).close()
    conn = init_db(path)  # second run must not re-add the column
    assert conn.execute("SELECT mode FROM sessions").fetchall() == [("voice",)]


def test_groove_session_persists_mode(
    registry: SessionRegistry, conn: sqlite3.Connection
) -> None:
    sid = _seed_groove(registry)
    assert _get(registry, sid).mode == SessionMode.GROOVE
    row = conn.execute("SELECT mode FROM sessions WHERE id = ?", (sid,)).fetchone()
    assert row == ("groove",)


def test_find_active_in_voice_channel_ignores_groove(
    registry: SessionRegistry,
) -> None:
    _seed_groove(registry, state=SessionState.ACTIVE)
    assert registry.find_active_in_voice_channel("444") is None


def test_stats_helpers_filter_by_mode(conn: sqlite3.Connection) -> None:
    _seed_row(conn, guild_id="222", mode="voice")
    _seed_row(conn, guild_id="222", mode="groove")
    assert len(fetch_user_stats_rows(conn, user_id="111")) == 2
    assert len(fetch_user_stats_rows(conn, user_id="111", mode="groove")) == 1
    assert len(fetch_guild_stats_rows(conn, guild_id="222")) == 2
    assert len(fetch_guild_stats_rows(conn, guild_id="222", mode="voice")) == 1


# ---------------------------------------------------------------------------
# /groove invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groove_starts_in_text_channel_without_voice(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    inter = _make_text_interaction()
    with (
        patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()),
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close_coro),
    ):
        await bot._handle_groove(inter)

    session = registry.find_active_in_text_channel("444")
    assert session is not None
    assert session.mode == SessionMode.GROOVE
    assert session.voice_channel_id == "444"
    # Welcome posted (not an ephemeral refusal) and no voice members pinged.
    assert inter.response.send_message.call_args.kwargs.get("ephemeral") is None
    inter.followup.send.assert_awaited_once_with(
        MSG_PARTICIPANT_PROMPT.format(mentions=""), ephemeral=False, wait=True
    )


@pytest.mark.asyncio
async def test_groove_ignores_unrelated_voice_state(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    """Being in Groove's (or any other) voice channel doesn't matter."""
    inter = _make_text_interaction(in_voice=True)
    with (
        patch("app.discord_bot.commands.asyncio.sleep", new=AsyncMock()),
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close_coro),
    ):
        await bot._handle_groove(inter)
    assert registry.find_active_in_text_channel("444") is not None


@pytest.mark.asyncio
async def test_groove_refuses_non_text_channel(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    inter = _make_text_interaction()
    inter.channel = MagicMock(spec=discord.Thread)
    inter.channel.id = 444
    await bot._handle_groove(inter)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    assert embed.description == MSG_WRONG_CHANNEL
    assert registry.find_active_in_text_channel("444") is None


@pytest.mark.asyncio
async def test_teamode_still_refuses_text_channel(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    inter = _make_text_interaction()
    await bot._handle_teamode(inter)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    assert embed.description == MSG_WRONG_CHANNEL
    assert registry.find_active_in_text_channel("444") is None


@pytest.mark.asyncio
async def test_handoff_refused_in_groove_session(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_groove(registry, state=SessionState.ACTIVE)
    inter = _make_text_interaction()
    inter.channel_id = 444
    target = MagicMock(spec=discord.Member)
    target.id = 500
    target.bot = False
    await bot._handle_handoff(inter, target)
    embed = inter.response.send_message.call_args.kwargs["embed"]
    assert embed.description == MSG_GROOVE_NO_HANDOFF
    assert _get(registry, sid).handoff_facilitator_id is None


@pytest.mark.asyncio
async def test_go_again_keeps_groove_mode(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_groove(registry, state=SessionState.FOLLOWUP)
    bot._chain_states[444] = _ChainState(
        session_id=sid, channel_id=444, message_id=1, kind="chain"
    )
    inter = _make_text_interaction()
    inter.channel_id = 444
    with patch.object(bot, "_start_session", new=AsyncMock()) as mock_start:
        await bot._handle_go_again(inter, sid, ["teamode", str(sid), "again"])
    mock_start.assert_awaited_once_with(
        inter, via_go_again=True, mode=SessionMode.GROOVE
    )


# ---------------------------------------------------------------------------
# Intention submit, tick, and end of session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groove_modal_submit_skips_voice(
    bot: TeaModeBot, registry: SessionRegistry, conn: sqlite3.Connection
) -> None:
    sid = _seed_groove(registry)
    registry.set_duration(session_id=sid, duration_minutes=25)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 444
    channel.send = AsyncMock(return_value=AsyncMock())
    modal = IntentionModal(bot=bot, session_id=sid, channel=channel)
    inter = AsyncMock()
    inter.response = AsyncMock()

    with (
        patch("app.discord_bot.views.voice.connect") as mock_connect,
        patch.object(bot, "_set_voice_status", new=AsyncMock()) as mock_status,
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close_coro),
    ):
        await modal.on_submit(inter)

    mock_connect.assert_not_called()
    mock_status.assert_not_called()
    assert _get(registry, sid).state == SessionState.ACTIVE
    assert channel.send.call_count == 1  # the timer message
    assert sid not in bot._voice_clients
    assert fetch_session_participants(conn, session_id=sid) == [("111", False)]


@pytest.mark.asyncio
async def test_groove_nudge_plays_wind_chime_locally(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_groove(registry, state=SessionState.ACTIVE)
    fake_msg = AsyncMock()
    fake_msg.channel = AsyncMock(spec=discord.TextChannel)
    bot._edit_states[sid] = _EditState(message=fake_msg)

    with (
        patch("app.discord_bot.timer.spawn_logged") as mock_spawn,
        patch("app.discord_bot.timer.voice.play_wind_chime") as mock_voice_chime,
    ):
        await bot._on_countdown_tick(sid, seconds_remaining=WRAP_UP_MINUTES * 60)

    mock_voice_chime.assert_not_called()
    mock_spawn.assert_called_once()
    mock_spawn.call_args.args[0].close()


@pytest.mark.asyncio
async def test_groove_end_of_session_plays_locally_and_pings(
    bot: TeaModeBot, registry: SessionRegistry
) -> None:
    sid = _seed_groove(registry, state=SessionState.FOLLOWUP)
    channel = AsyncMock()
    channel.id = 444
    times_up, ping, reflect = (AsyncMock(spec=discord.Message) for _ in range(3))
    times_up.id, ping.id, reflect.id = 1, 2, 3
    channel.send = AsyncMock(side_effect=[times_up, ping, reflect])

    with (
        patch(
            "app.discord_bot.lifecycle.local_audio.play",
            new=AsyncMock(return_value=True),
        ) as mock_local,
        patch(
            "app.discord_bot.lifecycle.voice.play_reverie_then_disconnect"
        ) as mock_voice,
        patch.object(bot, "_set_voice_status", new=AsyncMock()) as mock_status,
        patch("app.discord_bot.tasks.asyncio.create_task", side_effect=_close_coro),
    ):
        await bot._run_end_of_session(
            session_id=sid, voice_client=None, channel=channel
        )

    mock_local.assert_awaited_once_with(voice.REVERIE_PATH)
    mock_voice.assert_not_called()
    mock_status.assert_not_called()

    sends = channel.send.call_args_list
    assert sends[0].kwargs["content"] == END_OF_SESSION_NO_MENTION
    assert sends[1].args[0] == GROOVE_END_PING.format(mention="<@111>")
    assert sends[1].kwargs["allowed_mentions"].users is True
    assert bot._channel_cleanup[444].ping_id == 2
    assert bot._reflect_message_ids[sid] == 3


def test_groove_ping_is_clear_eligible() -> None:
    content = GROOVE_END_PING.format(mention="<@111>")
    assert is_delete_eligible(content=content, embed_titles=[])


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


def _stats_interaction() -> Any:
    inter = AsyncMock()
    inter.guild_id = 222
    inter.user = MagicMock()
    inter.user.id = 111
    inter.response = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_stats_groove_field_and_server_excludes_groove(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    _seed_row(conn, guild_id="222", mode="voice", duration=25)
    _seed_row(conn, guild_id="222", mode="groove", duration=50)
    inter = _stats_interaction()
    await bot._handle_stats(inter)

    embed: discord.Embed = inter.response.send_message.call_args.kwargs["embed"]
    fields = {f.name: f.value or "" for f in embed.fields}
    assert "75 min" in fields["You"]
    assert "50 min" in fields[STATS_SECTION_GROOVE]
    assert "25 min" in fields[STATS_SECTION_SERVER]
    assert "75 min" not in fields[STATS_SECTION_SERVER]


@pytest.mark.asyncio
async def test_stats_hides_groove_field_without_groove_sessions(
    bot: TeaModeBot, conn: sqlite3.Connection
) -> None:
    _seed_row(conn, guild_id="222", mode="voice")
    inter = _stats_interaction()
    await bot._handle_stats(inter)
    embed: discord.Embed = inter.response.send_message.call_args.kwargs["embed"]
    assert STATS_SECTION_GROOVE not in {f.name for f in embed.fields}
