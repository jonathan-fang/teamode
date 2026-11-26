"""The /teamode, /groove and /handoff slash command handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.constants import (
    GROOVE_COMMAND_DESCRIPTION,
    GUILD_DAILY_CAP,
    HANDOFF_ANNOUNCE,
    HANDOFF_COMMAND_DESCRIPTION,
    HANDOFF_MEMBER_DESCRIPTION,
    MSG_GROOVE_NO_HANDOFF,
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
from app.discord_bot.messages import best_effort
from app.discord_bot.views import (
    COLORS,
    _build_timer_view,
    _build_welcome_embed,
    _ChannelCleanup,
    _SetupMessages,
)
from app.rate_limit import RateLimiter
from app.session import SessionMode, SessionRegistry

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
    _channel_cleanup: dict[int, _ChannelCleanup]
    # Per-session record of whether it was started via Go again — see
    # BreakMixin's module docstring.
    _chained_via_go_again: dict[int, bool]

    if TYPE_CHECKING:
        # Provided by LifecycleMixin — declared here, type-checking only,
        # so pyright can check this mixin's own methods in isolation.
        def _arm_pending_expiry(self, session_id: int) -> None: ...

        # Provided by BreakMixin — same reasoning.
        async def _clear_chain_state(self, channel_id: int) -> None: ...
        async def _cancel_break(self, channel_id: int) -> None: ...
        def _reset_streak(self, channel_id: int) -> None: ...

    def _register_command(self) -> None:
        """Register /teamode, /groove and /handoff on the global command tree.

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
            name="groove",
            description=GROOVE_COMMAND_DESCRIPTION,
        )
        async def groove(interaction: discord.Interaction) -> None:
            await self._handle_groove(interaction)

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

    async def _handle_groove(self, interaction: discord.Interaction) -> None:
        """The /groove slash command — a session with no voice connection."""
        await self._start_session(interaction, mode=SessionMode.GROOVE)

    async def _start_session(
        self,
        interaction: discord.Interaction,
        *,
        via_go_again: bool = False,
        mode: SessionMode = SessionMode.VOICE,
    ) -> None:
        """Cumulative invocation guard → rate limit → create session → post welcome.

        Shared by the /teamode slash command and the "Go again" button —
        accepts any ``discord.Interaction`` and whoever triggers it becomes
        facilitator. *via_go_again* is ``True`` only for the Go again path
        (see ``BreakMixin._handle_go_again``); it is recorded against the
        new session for the streak logic in
        ``BreakMixin._post_chain_prompt``, and a plain ``/teamode`` start
        (``via_go_again=False``) always resets the channel's streak.

        *mode* is :attr:`SessionMode.GROOVE` for ``/groove`` (and a Go again
        chained from a Groove session): any text channel works, the invoker
        need not be in voice, and Ocha never joins voice.
        """

        # Guard 1 — /teamode must be invoked from a voice channel's text
        # chat. In discord.py, a voice channel's text-chat surface shares
        # the VoiceChannel's channel id; interaction.channel is a
        # VoiceChannel. /groove also accepts a plain text channel.
        channel = interaction.channel
        allowed = (
            (discord.VoiceChannel, discord.TextChannel)
            if mode == SessionMode.GROOVE
            else (discord.VoiceChannel,)
        )
        if not isinstance(channel, allowed):
            embed = discord.Embed(
                description=MSG_WRONG_CHANNEL,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 2 — /teamode's invoker must be in the voice channel.
        user = interaction.user
        voice_state = user.voice if isinstance(user, discord.Member) else None
        voice_channel = (
            voice_state.channel
            if voice_state is not None
            and voice_state.channel is not None
            and voice_state.channel.id == channel.id
            else None
        )
        if mode == SessionMode.VOICE and voice_channel is None:
            embed = discord.Embed(
                description=MSG_NOT_IN_VOICE,
                color=COLORS["refusal"],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Guard 3 — no active session in this text channel.
        existing = self._registry.find_active_in_text_channel(str(channel.id))
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

        # All guards passed — create the session. A voice session's voice
        # channel is its text channel (Guard 2); a Groove session has no
        # voice channel, so the text channel id fills the NOT NULL column.
        session = self._registry.create_pending_session(
            guild_id=str(interaction.guild_id),
            text_channel_id=str(channel.id),
            voice_channel_id=str(channel.id),
            facilitator_id=str(interaction.user.id),
            mode=mode,
        )

        # Record whether this session was chained via Go again, for the
        # streak logic in BreakMixin._post_chain_prompt. A plain /teamode
        # start always restarts the channel's streak from scratch.
        self._chained_via_go_again[session.session_id] = via_go_again
        if not via_go_again:
            self._reset_streak(channel.id)

        # Clean up the previous session's leftover messages in this channel,
        # if any — this also covers a future "Go again" button reusing this
        # same start path. Each step is independent and best-effort: a
        # failure is logged and does not block the others or the new session.
        previous_cleanup = self._channel_cleanup.pop(channel.id, None)
        if previous_cleanup is not None:
            for message_id, what in (
                (previous_cleanup.times_up_id, "Time's up message"),
                (previous_cleanup.why_id, "follow-up why message"),
                (previous_cleanup.ping_id, "Groove ping message"),
            ):
                if message_id is not None:
                    await best_effort(
                        channel.get_partial_message(message_id).delete(),
                        logger,
                        "Failed to delete previous %s %s in channel %s",
                        what,
                        message_id,
                        channel.id,
                    )
            if previous_cleanup.reflect_id is not None:
                await best_effort(
                    channel.get_partial_message(previous_cleanup.reflect_id).edit(
                        embed=None
                    ),
                    logger,
                    "Failed to strip embed from previous Reflect message %s"
                    " in channel %s",
                    previous_cleanup.reflect_id,
                    channel.id,
                )

        # Clear any standing chain prompt (Go again / break offer) and
        # cancel any in-progress break in this channel — a new session
        # (this one) supersedes both. This also covers a "Go again" click,
        # which reaches here via the same start path.
        await self._clear_chain_state(channel.id)
        await self._cancel_break(channel.id)

        await interaction.response.send_message(
            embed=_build_welcome_embed(), view=_build_timer_view(session.session_id)
        )

        # Capture the welcome message id — all later edits/deletes go
        # through the channel, never through the interaction webhook, since
        # interaction tokens expire well before a session ends.
        welcome_message = await interaction.original_response()
        self._setup_messages[session.session_id] = _SetupMessages(
            channel_id=channel.id,
            welcome_message_id=welcome_message.id,
        )

        # Arm the pending-expiry watchdog — cancelled once the intention is
        # submitted (see IntentionModal.on_submit).
        self._arm_pending_expiry(session.session_id)

        # Post the participant prompt after the welcome embed.
        await asyncio.sleep(WELCOME_PROMPT_DELAY_SECONDS)

        # Snapshot voice members, filter the bot itself. A Groove session
        # has no voice members to ping.
        bot_id = self.client.user.id if self.client.user else None
        members = (
            [m for m in voice_channel.members if not m.bot and m.id != bot_id]
            if mode == SessionMode.VOICE and voice_channel is not None
            else []
        )
        if members:
            mentions_prefix = " ".join(m.mention for m in members) + " "
        else:
            mentions_prefix = ""
        participant_prompt = MSG_PARTICIPANT_PROMPT.format(mentions=mentions_prefix)
        # wait=True to get the WebhookMessage id — deleted via the channel
        # (never the webhook) at every non-expiry terminal state.
        intention_message = await interaction.followup.send(
            participant_prompt, ephemeral=False, wait=True
        )
        setup = self._setup_messages.get(session.session_id)
        if setup is not None:
            setup.intention_message_id = intention_message.id

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

        # Groove sessions are solo — there is no one in voice to hand off to.
        if session.mode == SessionMode.GROOVE:
            embed = discord.Embed(
                description=MSG_GROOVE_NO_HANDOFF,
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
