"""Discord client, slash command registration, invocation guard, and welcome embed."""

from __future__ import annotations

import logging
import sqlite3

import discord
from discord import app_commands

from app.config import TEAMODE_DEV_GUILD_ID
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

        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

        # Wire event handlers.
        self.client.event(self.on_ready)

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
        title="🍵 TeaMode",
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
