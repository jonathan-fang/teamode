"""Tests for the timer-pick button handler and intention modal."""

from __future__ import annotations

import sqlite3
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.bot import (
    IntentionModal,
    TeaModeBot,
    _MSG_NOT_FACILITATOR,
    _MSG_PARTICIPANT_PROMPT,
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

    The discord.Client inside is never started; we call handlers directly.
    """
    return TeaModeBot(conn=conn, registry=registry)


def _make_component_interaction(
    custom_id: str,
    user_id: int = 111,
) -> Any:
    """Build a FakeInteraction that looks like a component (button) click.

    ``interaction.data`` carries the custom_id as Discord sends it.
    ``interaction.type`` is set to ``discord.InteractionType.component``.
    """
    inter = AsyncMock()
    inter.type = discord.InteractionType.component
    inter.data = {"custom_id": custom_id}

    user = MagicMock()
    user.id = user_id
    inter.user = user

    inter.response = AsyncMock()
    return inter


def _seed_session(registry: SessionRegistry, facilitator_id: int = 111) -> int:
    """Insert a PENDING session and return its session_id."""
    session = registry.create_pending_session(
        guild_id="222",
        text_channel_id="333",
        voice_channel_id="333",
        facilitator_id=str(facilitator_id),
    )
    return session.session_id


# ---------------------------------------------------------------------------
# Facilitator click — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facilitator_click_sets_duration_and_opens_modal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """Facilitator clicking a timer button records the duration and opens the modal."""
    session_id = _seed_session(registry, facilitator_id=111)
    custom_id = f"teamode:{session_id}:timer:25"
    inter = _make_component_interaction(custom_id, user_id=111)

    await bot.on_interaction(inter)

    # Duration must be recorded in the in-memory session.
    session = registry.get(session_id)
    assert session is not None
    assert session.duration_minutes == 25

    # send_modal must have been called once with an IntentionModal instance.
    inter.response.send_modal.assert_called_once()
    modal_arg = inter.response.send_modal.call_args.args[0]
    assert isinstance(modal_arg, IntentionModal)


# ---------------------------------------------------------------------------
# Non-facilitator click — refusal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_facilitator_click_sends_refusal(
    bot: TeaModeBot,
    registry: SessionRegistry,
) -> None:
    """A click from a non-facilitator sends the verbatim refusal and makes no transition."""
    session_id = _seed_session(registry, facilitator_id=111)
    custom_id = f"teamode:{session_id}:timer:25"
    inter = _make_component_interaction(custom_id, user_id=999)  # different user

    await bot.on_interaction(inter)

    # Ephemeral refusal must be sent with the exact message from UI-ADR.
    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    embed: discord.Embed = kwargs["embed"]
    assert embed.description == _MSG_NOT_FACILITATOR

    # No modal, no duration change.
    inter.response.send_modal.assert_not_called()
    session = registry.get(session_id)
    assert session is not None
    assert session.duration_minutes is None


# ---------------------------------------------------------------------------
# Stale-session click
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_session_click_sends_refusal(bot: TeaModeBot) -> None:
    """Clicking a button for a session_id not in the registry gets a stale refusal."""
    custom_id = "teamode:9999:timer:25"
    inter = _make_component_interaction(custom_id, user_id=111)

    await bot.on_interaction(inter)

    inter.response.send_message.assert_called_once()
    kwargs = inter.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    # Not the facilitator message — a separate stale-session message.
    embed: discord.Embed = kwargs["embed"]
    assert embed.description != _MSG_NOT_FACILITATOR
    assert embed.description is not None

    inter.response.send_modal.assert_not_called()


# ---------------------------------------------------------------------------
# Foreign (non-teamode) custom_id — ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foreign_custom_id_is_ignored(bot: TeaModeBot) -> None:
    """A component interaction with a non-teamode custom_id produces no response."""
    custom_id = "someone-else:42"
    inter = _make_component_interaction(custom_id, user_id=111)

    await bot.on_interaction(inter)

    # No response sent, no modal.
    inter.response.send_message.assert_not_called()
    inter.response.send_modal.assert_not_called()


# ---------------------------------------------------------------------------
# Modal submit — intention recorded and participant prompt posted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modal_submit_records_intention_and_posts_participant_prompt(
    bot: TeaModeBot,
    registry: SessionRegistry,
    conn: sqlite3.Connection,
) -> None:
    """Submitting the intention modal records the intention and posts the prompt."""
    session_id = _seed_session(registry, facilitator_id=111)

    modal = IntentionModal(bot=bot, session_id=session_id)

    # Simulate the text-input value that discord.py would populate on submit.
    text_input = cast(
        discord.ui.TextInput[discord.ui.Modal], modal.intention_field.component
    )
    text_input._value = "finish the changelog"

    # Build a fake interaction for the modal submit.
    inter = AsyncMock()
    inter.response = AsyncMock()
    inter.channel = AsyncMock()

    await modal.on_submit(inter)

    # Intention must be recorded in the registry and in SQLite.
    session = registry.get(session_id)
    assert session is not None
    assert session.intention == "finish the changelog"

    # Verify SQLite was updated (exercises the real query path).
    cur = conn.execute(
        "SELECT intention, status FROM sessions WHERE id = ?", (session_id,)
    )
    row = cur.fetchone()
    assert row[0] == "finish the changelog"
    assert row[1] == "intention_set"

    # Modal interaction must be deferred (ephemeral ack, no channel noise).
    inter.response.defer.assert_called_once_with(ephemeral=True)

    # Participant prompt posted to the channel with exact Spec text.
    inter.channel.send.assert_called_once_with(_MSG_PARTICIPANT_PROMPT)
