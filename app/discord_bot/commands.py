"""The /teamode and /handoff slash command handlers."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from app.discord_bot.views import COLORS, _build_timer_view, _build_welcome_embed
from app.session import SessionRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guard refusal messages — verbatim from Spec § "Invocation guard"
# ---------------------------------------------------------------------------

_MSG_WRONG_CHANNEL = "Run `/teamode` from a voice channel's text chat."
_MSG_NOT_IN_VOICE = "Join the voice channel first, then try again."
_MSG_SESSION_ACTIVE = (
    "A TeaMode session is already running in this channel"
    " — please pick another text channel."
)

# Verbatim from Spec § "Participant flow".
_MSG_PARTICIPANT_PROMPT = "🥅 **[Set Intention]** Please share your intention for this session in voice or type it in the chat."


class CommandsMixin:
    """Slash command registration and handlers, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation.
    client: discord.Client
    tree: app_commands.CommandTree
    _registry: SessionRegistry

    def _register_command(self) -> None:
        """Register /teamode and /handoff on the global command tree.

        Commands are registered globally here; on_ready copies them to each
        guild in TEAMODE_DEV_GUILD_IDS for instant propagation during dev.
        """

        @self.tree.command(
            name="teamode",
            description="Start a TeaMode focus session in this voice channel.",
        )
        async def teamode(interaction: discord.Interaction) -> None:
            await self._handle_teamode(interaction)

        @self.tree.command(
            name="handoff",
            description="Transfer the facilitator role to another voice-channel member.",
        )
        @app_commands.describe(
            member="The voice-channel member to make the new facilitator."
        )
        async def handoff(
            interaction: discord.Interaction, member: discord.Member
        ) -> None:
            await self._handle_handoff(interaction, member)

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

        # Post the participant prompt 1 second after the welcome embed.
        await asyncio.sleep(1.0)

        # Snapshot voice members, filter the bot itself.
        assert voice_state.channel is not None
        bot_id = self.client.user.id if self.client.user else None
        members = [
            m for m in voice_state.channel.members if not m.bot and m.id != bot_id
        ]
        if members:
            mentions = " ".join(m.mention for m in members)
            participant_prompt = (
                f"🥅 **[Set Intention]** {mentions} Please share your intention "
                "for this session in voice or type it in the chat."
            )
        else:
            participant_prompt = _MSG_PARTICIPANT_PROMPT
        await interaction.followup.send(participant_prompt, ephemeral=False)

    async def _handle_handoff(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        """Handle the /handoff slash command.

        Validates that the invoker is the current facilitator of an active
        session, then transfers the role to the specified voice-channel member.
        """

        # Guard 1 — Session must be active in this channel.
        session = self._registry.find_active_in_text_channel(
            str(interaction.channel.id) if interaction.channel is not None else ""  # type: ignore[union-attr]
        )
        if session is None:
            embed = discord.Embed(
                description="No active TeaMode session in this channel.",
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 2 — Invoker must be the current facilitator.
        if str(interaction.user.id) != session.facilitator_id:
            embed = discord.Embed(
                description="Only the facilitator can hand off the role.",
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 3 — Target must not be the invoker themselves.
        if member.id == interaction.user.id:
            embed = discord.Embed(
                description="You are already the facilitator.",
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 4 — Target must be a human (not a bot).
        if member.bot:
            embed = discord.Embed(
                description="Pick a human voice-channel member.",
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 5 — Target must be present in the voice channel.
        voice_channel = self.client.get_channel(int(session.voice_channel_id))
        if voice_channel is None or member not in voice_channel.members:  # type: ignore[union-attr]
            embed = discord.Embed(
                description="Target must be in the voice channel.",
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # All guards passed — perform the handoff.
        old_facilitator_id = (
            session.facilitator_id
        )  # snapshot before mark_handoff updates it
        self._registry.mark_handoff(
            session_id=session.session_id,
            handoff_facilitator_id=str(member.id),
        )

        content = (
            f"<@{old_facilitator_id}> handed off — <@{member.id}>,"
            " you're now the facilitator."
        )
        await interaction.response.send_message(
            content,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
