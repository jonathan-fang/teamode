"""Discord client, slash command registration, invocation guard, and welcome embed."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import cast

import discord
from discord import app_commands

from app import voice
from app.config import TEAMODE_DEV_GUILD_ID
from app import session as session_module
from app.session import SessionRegistry

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

# ---------------------------------------------------------------------------
# Guard refusal messages — verbatim from Spec § "Invocation guard"
# ---------------------------------------------------------------------------

_MSG_WRONG_CHANNEL = "Run `/teamode` from a voice channel's text chat."
_MSG_NOT_IN_VOICE = "Join the voice channel first, then try again."
_MSG_SESSION_ACTIVE = (
    "A TeaMode session is already running in this channel"
    " — please pick another text channel."
)

# Verbatim from UI-ADR § "Authorization rules".
_MSG_NOT_FACILITATOR = "Only the facilitator can answer."

# Verbatim from Spec § "Participant flow".
_MSG_PARTICIPANT_PROMPT = (
    "🥅 [Set Intention] Please share your intention for this session in voice or type it in the chat."
)

# Voice connect failure — ephemeral, short, clear.
_MSG_VOICE_CONNECT_FAILED = "Could not join voice — session cancelled."

# Active timer message format (two spaces between intention and timer per Spec).
_ACTIVE_TIMER_FMT = "🍵 Intention: {intention}  ⏳ {mm:02d}:{ss:02d}"

# Edit cadence per UI-ADR § "Timer edit cadence".
_EDIT_INTERVAL_SECONDS = 10

# Backoff limits for 429 handling.
_BACKOFF_FLOOR_DEFAULT = 10.0
_BACKOFF_FLOOR_CAP = 60.0


def _format_timer(seconds_remaining: int) -> str:
    """Format *seconds_remaining* as ``mm:ss`` (zero-padded)."""
    mm, ss = divmod(seconds_remaining, 60)
    return f"{mm:02d}:{ss:02d}"


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
            required=True,
        ),
    )

    def __init__(self, *, bot: TeaModeBot, session_id: int) -> None:
        super().__init__()
        self._bot = bot
        self._session_id = session_id

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
        # Post the participant prompt publicly via the interaction webhook.
        # Using followup.send (ephemeral=False) avoids requiring explicit
        # View Channel + Send Messages permissions on the voice channel.
        await interaction.followup.send(_MSG_PARTICIPANT_PROMPT, ephemeral=False)

        # --- Connect voice ---
        try:
            voice_channel = await self._bot.client.fetch_channel(
                int(session.voice_channel_id)
            )
            if not isinstance(voice_channel, discord.VoiceChannel):
                raise TypeError(
                    f"Expected VoiceChannel, got {type(voice_channel).__name__}"
                )
            voice_client = await voice.connect(voice_channel)
        except Exception:
            logger.exception("Voice connect failed for session %s", self._session_id)
            await interaction.followup.send(_MSG_VOICE_CONNECT_FAILED, ephemeral=True)
            self._bot._registry.mark_cancelled(session_id=self._session_id)
            return

        # --- Advance to ACTIVE and post the timer message ---
        self._bot._registry.mark_active(session_id=self._session_id)
        assert session.duration_minutes is not None
        initial_content = _ACTIVE_TIMER_FMT.format(
            intention=session.intention,
            mm=session.duration_minutes,
            ss=0,
        )
        # wait=True ensures we get the real WebhookMessage back (with .edit/.id).
        timer_message = await interaction.followup.send(
            initial_content, ephemeral=False, wait=True
        )

        # Stash edit state so the tick callback can reach it.
        self._bot._edit_states[self._session_id] = _EditState(message=timer_message)

        # --- Schedule countdown, then mark followup when it completes ---
        session_id = self._session_id

        async def _run_and_followup() -> None:
            await session_module.run_countdown(
                duration_minutes=session.duration_minutes,  # type: ignore[arg-type]
                on_tick=lambda s: self._bot._on_countdown_tick(session_id, s),
            )
            self._bot._registry.mark_followup(session_id=session_id)
            # Clean up edit state; Stage 4 will handle the end-of-session surface.
            self._bot._edit_states.pop(session_id, None)
            await voice_client.disconnect()  # type: ignore[misc]

        asyncio.create_task(_run_and_followup())


# ---------------------------------------------------------------------------
# TeaModeBot
# ---------------------------------------------------------------------------


class TeaModeBot:
    """Owns the Discord client, command tree, DB connection, and session registry.

    Dependencies (conn and registry) are injected by the entry point so that
    tests can substitute fakes without touching this module.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: SessionRegistry,
    ) -> None:
        self._conn = conn
        self._registry = registry

        # Per-session edit state, keyed by session_id.
        # Populated when an active timer message is posted; removed on followup.
        self._edit_states: dict[int, _EditState] = {}

        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

        # Wire event handlers.
        self.client.event(self.on_ready)
        self.client.event(self.on_interaction)

        # Register the slash command on this instance.
        self._register_command()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (id=%s)",
            self.client.user,
            self.client.user and self.client.user.id,
        )

        if TEAMODE_DEV_GUILD_ID is not None:
            guild = discord.Object(id=int(TEAMODE_DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Slash commands synced to guild %s", TEAMODE_DEV_GUILD_ID)
        else:
            logger.warning(
                "TEAMODE_DEV_GUILD_ID is not set — skipping command registration. "
                "Set TEAMODE_DEV_GUILD_ID to your dev guild id for instant "
                "command propagation."
            )

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route component interactions (button clicks, select menus, etc.).

        Dispatch structure: parse ``custom_id`` → route by purpose segment.
        Adding a new purpose (e.g. ``followup``) requires only a new branch
        in the ``if purpose == ...`` block below — the parse logic is shared.

        Application-command interactions are forwarded to the command tree
        instead of being handled here.
        """
        # Application commands are handled by the CommandTree before this
        # on_interaction callback fires; no forwarding needed here.
        if interaction.type != discord.InteractionType.component:
            return

        custom_id: str = interaction.data.get("custom_id", "")  # type: ignore[union-attr]
        parts = custom_id.split(":")

        # Ignore non-teamode custom_ids (other bots, earlier code, etc.).
        if len(parts) < 3 or parts[0] != "teamode":
            return

        # Parse session_id — must be a valid integer.
        try:
            session_id = int(parts[1])
        except ValueError:
            return

        purpose = parts[2]

        if purpose == "timer":
            await self._handle_timer_pick(interaction, session_id, parts)
        # Future purposes (followup, etc.) get their own branch here.

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
        modal = IntentionModal(bot=self, session_id=session_id)
        await interaction.response.send_modal(modal)

    async def _on_countdown_tick(self, session_id: int, seconds_remaining: int) -> None:
        """Tick callback injected into ``run_countdown``.

        Fires every second.  Only attempts a Discord message edit on
        ticks that are multiples of *_EDIT_INTERVAL_SECONDS* or on the
        final tick (``seconds_remaining == 0``).

        Skips the edit if the per-session lock is already held (a previous
        edit is still in flight).  Applies exponential backoff on HTTP 429.
        """
        # Only edit on 10-second boundaries and at zero.
        if seconds_remaining % _EDIT_INTERVAL_SECONDS != 0 and seconds_remaining != 0:
            return

        edit_state = self._edit_states.get(session_id)
        if edit_state is None:
            # Session was cleaned up; nothing to do.
            return

        # Check the session intention for the message content.
        session = self._registry.get(session_id)
        if session is None or session.intention is None:
            return

        # Skip if a previous edit is still in flight.
        if edit_state.lock.locked():
            logger.debug(
                "Skipping edit for session %s at %ds — previous edit in flight",
                session_id,
                seconds_remaining,
            )
            return

        async with edit_state.lock:
            mm, ss = divmod(seconds_remaining, 60)
            content = _ACTIVE_TIMER_FMT.format(
                intention=session.intention,
                mm=mm,
                ss=ss,
            )
            try:
                await edit_state.message.edit(content=content)
                # Successful edit — decay backoff floor back to default.
                edit_state.backoff_floor = _BACKOFF_FLOOR_DEFAULT
            except discord.HTTPException as exc:
                if exc.status == 429:
                    # Rate limited — double the floor, respect the cap.
                    edit_state.backoff_floor = min(
                        edit_state.backoff_floor * 2, _BACKOFF_FLOOR_CAP
                    )
                    logger.warning(
                        "Rate limited on session %s timer edit; backoff floor now %.0fs",
                        session_id,
                        edit_state.backoff_floor,
                    )
                else:
                    logger.warning(
                        "HTTP %s editing timer message for session %s",
                        exc.status,
                        session_id,
                    )

    # ------------------------------------------------------------------
    # Command registration
    # ------------------------------------------------------------------

    def _register_command(self) -> None:
        """Register /teamode on the command tree.

        Guild-scoped when TEAMODE_DEV_GUILD_ID is set (instant propagation
        during dev); global registration is skipped for MVP — global commands
        take up to one hour to propagate and are not suitable for active dev.
        """
        guild_object: discord.Object | None = (
            discord.Object(id=int(TEAMODE_DEV_GUILD_ID))
            if TEAMODE_DEV_GUILD_ID is not None
            else None
        )

        @self.tree.command(
            name="teamode",
            description="Start a TeaMode focus session in this voice channel.",
            guild=guild_object,
        )
        async def teamode(interaction: discord.Interaction) -> None:
            await self._handle_teamode(interaction)

    # ------------------------------------------------------------------
    # Slash command handler
    # ------------------------------------------------------------------

    async def _handle_teamode(self, interaction: discord.Interaction) -> None:
        """Cumulative invocation guard → create session → post welcome embed."""

        # Guard 1 — must be invoked from a voice channel's text chat.
        # In discord.py, a voice channel's text-chat surface shares the
        # VoiceChannel's channel id; interaction.channel is a VoiceChannel.
        if not isinstance(interaction.channel, discord.VoiceChannel):
            embed = discord.Embed(
                description=_MSG_WRONG_CHANNEL,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 2 — invoker must be in the voice channel.
        voice_state = (
            interaction.user.voice
            if isinstance(interaction.user, discord.Member)
            else None
        )  # type: ignore[union-attr]
        user_in_voice = (
            voice_state is not None
            and voice_state.channel is not None
            and voice_state.channel.id == interaction.channel.id
        )
        if not user_in_voice:
            embed = discord.Embed(
                description=_MSG_NOT_IN_VOICE,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 3 — no active session in this text channel.
        existing = self._registry.find_active_in_text_channel(
            str(interaction.channel.id)
        )
        if existing is not None:
            embed = discord.Embed(
                description=_MSG_SESSION_ACTIVE,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # All guards passed — create the session.
        assert (
            voice_state is not None and voice_state.channel is not None
        )  # narrowed above
        session = self._registry.create_pending_session(
            guild_id=str(interaction.guild_id),
            text_channel_id=str(interaction.channel.id),
            voice_channel_id=str(voice_state.channel.id),
            facilitator_id=str(interaction.user.id),
        )

        # Build the welcome embed.
        embed = _build_welcome_embed()

        # Build the timer-pick button row.
        view = _build_timer_view(session.session_id)

        await interaction.response.send_message(embed=embed, view=view)

    def run(self, token: str) -> None:
        """Start the Discord event loop."""
        self.client.run(token)


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
            "Time for TeaMode!\n"
            "· Grab your tea (or water/beverage of your choice),\n"
            "· Clear your desk,\n"
            "· And silence all distractions (like phones, impromptu meetings).\n\n"
            "⏳ **How long would you like to focus today?**"
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
    for minutes in (10, 25, 50):
        button: discord.ui.Button[discord.ui.View] = discord.ui.Button(
            label=f"{minutes} min",
            custom_id=f"teamode:{session_id}:timer:{minutes}",
            style=discord.ButtonStyle.secondary,
        )
        view.add_item(button)
    return view
