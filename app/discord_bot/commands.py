"""The /teamode and /handoff slash command handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.constants import (
    GUILD_DAILY_CAP,
    HANDOFF_ANNOUNCE,
    HANDOFF_COMMAND_DESCRIPTION,
    HANDOFF_MEMBER_DESCRIPTION,
    MSG_HANDOFF_NO_SESSION,
    MSG_HANDOFF_NOT_FACILITATOR,
    MSG_HANDOFF_SELF,
    MSG_HANDOFF_TARGET_BOT,
    MSG_HANDOFF_TARGET_NOT_IN_VOICE,
    MSG_NOT_IN_VOICE,
    MSG_PARTICIPANT_PROMPT,
    MSG_RATE_LIMIT_GUILD,
    MSG_RATE_LIMIT_USER,
    MSG_SESSION_ACTIVE,
    MSG_WRONG_CHANNEL,
    TEAMODE_COMMAND_DESCRIPTION,
    WELCOME_PROMPT_DELAY_SECONDS,
)
from app.discord_bot.views import (
    COLORS,
    _build_timer_view,
    _build_welcome_embed,
    _SetupMessages,
)
from app.rate_limit import RateLimiter
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class CommandsMixin:
    """Slash command registration and handlers, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation.
    client: discord.Client
    tree: app_commands.CommandTree
    _registry: SessionRegistry
    _rate_limiter: RateLimiter
    _setup_messages: dict[int, _SetupMessages]

    if TYPE_CHECKING:
        # Provided by LifecycleMixin — declared here, type-checking only,
        # so pyright can check this mixin's own methods in isolation.
        def _arm_pending_expiry(self, session_id: int) -> None: ...

    def _register_command(self) -> None:
        """Register /teamode and /handoff on the global command tree.

        Commands are registered globally here; on_ready copies them to each
        guild in TEAMODE_DEV_GUILD_IDS for instant propagation during dev.
        """

        @self.tree.command(
            name="teamode",
            description=TEAMODE_COMMAND_DESCRIPTION,
        )
        async def teamode(interaction: discord.Interaction) -> None:
            await self._handle_teamode(interaction)

        @self.tree.command(
            name="handoff",
            description=HANDOFF_COMMAND_DESCRIPTION,
        )
        @app_commands.describe(member=HANDOFF_MEMBER_DESCRIPTION)
        async def handoff(
            interaction: discord.Interaction, member: discord.Member
        ) -> None:
            await self._handle_handoff(interaction, member)

    async def _handle_teamode(self, interaction: discord.Interaction) -> None:
        """The /teamode slash command — delegates to the shared session start."""
        await self._start_session(interaction)

    async def _start_session(self, interaction: discord.Interaction) -> None:
        """Cumulative invocation guard → rate limit → create session → post welcome.

        Shared by the /teamode slash command and (in a later Task) a
        "Go again" button — accepts any ``discord.Interaction`` and whoever
        triggers it becomes facilitator.
        """

        # Guard 1 — must be invoked from a voice channel's text chat.
        # In discord.py, a voice channel's text-chat surface shares the
        # VoiceChannel's channel id; interaction.channel is a VoiceChannel.
        if not isinstance(interaction.channel, discord.VoiceChannel):
            embed = discord.Embed(
                description=MSG_WRONG_CHANNEL,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 2 — invoker must be in the voice channel.
        user = interaction.user
        voice_state = user.voice if isinstance(user, discord.Member) else None
        user_in_voice = (
            voice_state is not None
            and voice_state.channel is not None
            and voice_state.channel.id == interaction.channel.id
        )
        if not user_in_voice:
            embed = discord.Embed(
                description=MSG_NOT_IN_VOICE,
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
                description=MSG_SESSION_ACTIVE,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Rate limit — only invocations that passed the guards above count,
        # so a mistyped channel or an absent voice join doesn't burn the
        # allowance. Per-user check runs before per-guild (see RateLimiter
        # docstring); a refusal at either stage creates no session row.
        rate_result = self._rate_limiter.check_and_record(
            user_id=str(interaction.user.id),
            guild_id=str(interaction.guild_id),
        )
        if not rate_result.allowed:
            if rate_result.reason == "user":
                logger.info(
                    "Rate limit refusal (user) — user_id=%s retry_after=%s",
                    interaction.user.id,
                    rate_result.retry_after_seconds,
                )
                description = MSG_RATE_LIMIT_USER.format(
                    seconds=rate_result.retry_after_seconds
                )
            else:
                logger.info(
                    "Rate limit refusal (guild) — guild_id=%s",
                    interaction.guild_id,
                )
                description = MSG_RATE_LIMIT_GUILD.format(cap=GUILD_DAILY_CAP)
            embed = discord.Embed(
                description=description,
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

        # Capture the welcome message id — all later edits/deletes go
        # through the channel, never through the interaction webhook, since
        # interaction tokens expire well before a session ends.
        welcome_message = await interaction.original_response()
        self._setup_messages[session.session_id] = _SetupMessages(
            channel_id=interaction.channel.id,
            welcome_message_id=welcome_message.id,
        )

        # Arm the pending-expiry watchdog — cancelled once a duration is
        # picked (see ViewsMixin._handle_timer_pick).
        self._arm_pending_expiry(session.session_id)

        # Post the participant prompt after the welcome embed.
        await asyncio.sleep(WELCOME_PROMPT_DELAY_SECONDS)

        # Snapshot voice members, filter the bot itself.
        assert voice_state.channel is not None
        bot_id = self.client.user.id if self.client.user else None
        members = [
            m for m in voice_state.channel.members if not m.bot and m.id != bot_id
        ]
        if members:
            mentions_prefix = " ".join(m.mention for m in members) + " "
        else:
            mentions_prefix = ""
        participant_prompt = MSG_PARTICIPANT_PROMPT.format(mentions=mentions_prefix)
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
            str(interaction.channel_id) if interaction.channel_id is not None else ""
        )
        if session is None:
            embed = discord.Embed(
                description=MSG_HANDOFF_NO_SESSION,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 2 — Invoker must be the current facilitator.
        if str(interaction.user.id) != session.facilitator_id:
            embed = discord.Embed(
                description=MSG_HANDOFF_NOT_FACILITATOR,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 3 — Target must not be the invoker themselves.
        if member.id == interaction.user.id:
            embed = discord.Embed(
                description=MSG_HANDOFF_SELF,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 4 — Target must be a human (not a bot).
        if member.bot:
            embed = discord.Embed(
                description=MSG_HANDOFF_TARGET_BOT,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 5 — Target must be present in the voice channel.
        voice_channel = self.client.get_channel(int(session.voice_channel_id))
        if not isinstance(voice_channel, discord.VoiceChannel) or member not in (
            voice_channel.members
        ):
            embed = discord.Embed(
                description=MSG_HANDOFF_TARGET_NOT_IN_VOICE,
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

        content = HANDOFF_ANNOUNCE.format(
            old_facilitator_id=old_facilitator_id,
            new_facilitator_id=member.id,
        )
        await interaction.response.send_message(
            content,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
