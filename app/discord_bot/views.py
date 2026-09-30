"""Color palette, timer-pick handling, the intention modal, and embed builders."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import discord

from app import session as session_module
from app import voice
from app.session import SessionRegistry

if TYPE_CHECKING:
    from app.discord_bot.client import TeaModeBot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette — from UI-ADR § "Color palette"
# ---------------------------------------------------------------------------

COLORS = {
    "active": discord.Color.from_str("#7B9D6F"),  # Matcha sage
    "end_of_session": discord.Color.from_str("#3F5E4A"),  # Steeping forest
    "refusal": discord.Color.from_str("#8A8A8A"),  # Muted grey
    "crashed": discord.Color.from_str("#A05A5A"),  # Muted red
    "completed": discord.Color.from_str("#C97B53"),  # Oolong amber
}

# Verbatim from UI-ADR § "Authorization rules".
_MSG_NOT_FACILITATOR = "Only the facilitator can answer."

# Voice connect failure — ephemeral, short, clear.
_MSG_VOICE_CONNECT_FAILED = "Could not join voice — session cancelled."

# Active timer message format (two spaces between intention and timer per Spec).
_ACTIVE_TIMER_FMT = "{intention_line}\n{duration} min session\n⏳ {mm:02d}:{ss:02d}"

# Backoff limits for 429 handling.
_BACKOFF_FLOOR_DEFAULT = 10.0


def _format_timer(seconds_remaining: int) -> str:
    """Format *seconds_remaining* as ``mm:ss`` (zero-padded)."""
    mm, ss = divmod(seconds_remaining, 60)
    return f"{mm:02d}:{ss:02d}"


def _format_intention_line(intention: str | None) -> str:
    """Render the first line of the active timer message.

    Returns the placeholder when no intention was captured.
    """
    if intention and intention.strip():
        return f"🍵 Facilitator's Intention: {intention}"
    return "🍵 No intention set"


# ---------------------------------------------------------------------------
# Per-session edit-state holder
# ---------------------------------------------------------------------------


@dataclass
class _EditState:
    """Mutable edit state for one active timer session.

    Holds the message handle to edit, a lock to prevent concurrent edits,
    and the current rate-limit backoff floor.
    """

    message: discord.Message
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    backoff_floor: float = _BACKOFF_FLOOR_DEFAULT


# ---------------------------------------------------------------------------
# IntentionModal
# ---------------------------------------------------------------------------


class IntentionModal(discord.ui.Modal, title="Set your intention"):
    """Modal that captures the facilitator's session intention.

    Opened after a timer-pick button click.  On submit, records the
    intention via the registry and posts the public participant prompt.
    """

    intention_field: discord.ui.Label = discord.ui.Label(
        text="What will you focus on?",
        component=discord.ui.TextInput(
            style=discord.TextStyle.long,
            max_length=4000,
            required=False,
        ),
    )

    def __init__(
        self,
        *,
        bot: TeaModeBot,
        session_id: int,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        """Initialise the modal.

        *voice_channel* is the resolved ``discord.VoiceChannel`` from the
        click-handler call site.  Passing it here avoids a REST round-trip
        (``fetch_channel``) in :meth:`on_submit` and the permission gate that
        round-trip would cross.
        """
        super().__init__()
        self._bot = bot
        self._session_id = session_id
        self._voice_channel = voice_channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text_input = cast(
            discord.ui.TextInput[discord.ui.Modal], self.intention_field.component
        )
        intention_text = text_input.value or ""
        session = self._bot._registry.set_intention(
            session_id=self._session_id,
            intention=intention_text,
        )
        # Acknowledge the modal interaction without cluttering the channel.
        await interaction.response.defer(ephemeral=True)

        # --- Connect voice ---
        # Use the channel resolved at click-handler time — no REST round-trip.
        voice_channel = self._voice_channel
        try:
            voice_client = await voice.connect(voice_channel)
        except Exception:
            logger.exception("Voice connect failed for session %s", self._session_id)
            await interaction.followup.send(_MSG_VOICE_CONNECT_FAILED, ephemeral=True)
            self._bot._registry.mark_cancelled(session_id=self._session_id)
            return

        # Stash the voice client so the solo-grace flow can disconnect it.
        self._bot._voice_clients[self._session_id] = voice_client

        # --- Advance to ACTIVE and post the timer message ---
        self._bot._registry.mark_active(session_id=self._session_id)
        assert session.duration_minutes is not None
        initial_content = _ACTIVE_TIMER_FMT.format(
            intention_line=_format_intention_line(session.intention),
            duration=session.duration_minutes,
            mm=session.duration_minutes,
            ss=0,
        )
        timer_message = await cast(discord.VoiceChannel, interaction.channel).send(
            initial_content
        )

        # Stash edit state so the tick callback can reach it.
        self._bot._edit_states[self._session_id] = _EditState(message=timer_message)

        # --- Schedule countdown, then run the full end-of-session sequence ---
        session_id = self._session_id
        # Capture the channel reference for the end-of-session messages.
        # interaction.channel is a VoiceChannel here (enforced by the
        # /teamode guard), which is Messageable. Cast to satisfy pyright.
        channel = cast(discord.abc.Messageable | None, interaction.channel)

        async def _run_and_followup() -> None:
            await session_module.run_countdown(
                duration_minutes=session.duration_minutes,  # type: ignore[arg-type]
                on_tick=lambda s: self._bot._on_countdown_tick(session_id, s),
            )
            self._bot._registry.mark_followup(session_id=session_id)
            # Clean up edit state and per-session resource dicts.
            self._bot._edit_states.pop(session_id, None)
            self._bot._voice_clients.pop(session_id, None)
            self._bot._countdown_tasks.pop(session_id, None)
            # Run the full end-of-session sequence.
            await self._bot._run_end_of_session(
                session_id=session_id,
                voice_client=voice_client,
                channel=channel,
            )

        task = asyncio.create_task(_run_and_followup())
        self._bot._countdown_tasks[session_id] = task


# ---------------------------------------------------------------------------
# ViewsMixin — timer-pick button handling
# ---------------------------------------------------------------------------


class ViewsMixin:
    """Timer-pick button handling, mixed into :class:`TeaModeBot`."""

    # Attribute provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation.
    _registry: SessionRegistry

    async def _handle_timer_pick(
        self,
        interaction: discord.Interaction,
        session_id: int,
        parts: list[str],
    ) -> None:
        """Handle a timer-pick button click."""
        session = self._registry.get(session_id)
        if session is None:
            embed = discord.Embed(
                description="This session is no longer active.",
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if str(interaction.user.id) != session.facilitator_id:
            embed = discord.Embed(
                description=_MSG_NOT_FACILITATOR,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Parse the duration value from the custom_id.
        try:
            duration_minutes = int(parts[3])
        except (IndexError, ValueError):
            logger.warning("Malformed timer custom_id: %r", ":".join(parts))
            return

        self._registry.set_duration(
            session_id=session_id,
            duration_minutes=duration_minutes,
        )

        # Disable the timer-pick buttons so a second click is impossible.
        # Must be done before opening the modal (responding to the interaction
        # with a modal consumes the response slot).
        assert interaction.message is not None
        view = discord.ui.View.from_message(interaction.message)
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(view=view)

        # interaction.channel is guaranteed to be a VoiceChannel here — the
        # /teamode invocation guard (Guard 1 in _handle_teamode) already
        # enforced it.  The assert satisfies pyright's narrowing requirement.
        assert isinstance(interaction.channel, discord.VoiceChannel)
        modal = IntentionModal(
            bot=cast("TeaModeBot", self),
            session_id=session_id,
            voice_channel=interaction.channel,
        )
        await interaction.response.send_modal(modal)


# ---------------------------------------------------------------------------
# Embed and view builders
# ---------------------------------------------------------------------------


def _build_welcome_embed() -> discord.Embed:
    """Construct the welcome embed (matcha sage accent, 🍵 + ⏳ pair).

    Copy source: UI-ADR § "Surface inventory" — welcome embed greets the
    facilitator and prompts tea / desk / distractions check.
    """
    embed = discord.Embed(
        title="🍵 Now Entering TeaMode",
        description=(
            "### Time for TeaMode!\n"
            "### · Grab your tea (or water/beverage of your choice),\n"
            "### · Clear your desk,\n"
            "### · And silence all distractions (like phones, impromptu meetings).\n\n"
            "### ⏳ **How long would you like to focus today?**"
        ),
        color=COLORS["active"],
    )
    return embed


def _build_timer_view(session_id: int) -> discord.ui.View:
    """Build the 10 / 25 / 50 timer-pick button row for *session_id*.

    Custom_ids follow UI-ADR § "Custom_id namespace":
    ``teamode:<session_id>:timer:<value>``.
    """
    view = discord.ui.View()
    for minutes in (5, 10, 25, 50):
        button: discord.ui.Button[discord.ui.View] = discord.ui.Button(
            label=f"{minutes} min",
            custom_id=f"teamode:{session_id}:timer:{minutes}",
            style=discord.ButtonStyle.secondary,
        )
        view.add_item(button)
    return view
