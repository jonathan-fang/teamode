"""The /clear command: deletes past TeaMode clutter in a channel."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from app.cleanup import is_delete_eligible
from app.constants import (
    CLEAR_COMMAND_DESCRIPTION,
    CLEAR_DELETE_INTERVAL_SECONDS,
    CLEAR_DONE,
    CLEAR_NO_PERMISSION,
    CLEAR_NOTHING,
    CLEAR_SCAN_LIMIT,
    MSG_WRONG_CHANNEL,
)
from app.discord_bot.messages import best_effort
from app.discord_bot.runtime import RuntimeStore
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class ClearMixin:
    """The /clear command, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check this mixin's own methods in isolation.
    client: discord.Client
    tree: app_commands.CommandTree
    _registry: SessionRegistry
    _rt: RuntimeStore

    def _register_clear_command(self) -> None:
        """Register /clear on the command tree."""

        @self.tree.command(
            name="clear",
            description=CLEAR_COMMAND_DESCRIPTION,
        )
        async def clear(interaction: discord.Interaction) -> None:
            await self._handle_clear(interaction)

    def _protected_message_ids(self, channel_id: int) -> set[int]:
        """Return message ids to keep in *channel_id* for /clear.

        Covers the channel's non-terminal session (if any) — its timer
        message, its welcome / Set-Intention / nudge messages, and its
        Reflect message (a session in FOLLOWUP, awaiting ✅/⛔, is
        non-terminal, so this also protects a live Reflect prompt) — plus
        the live chaining prompt (any kind: chain / chain_streak /
        post_break) and the live break message, if either is standing in
        this channel.

        While the channel has a non-terminal session, its
        ``ChannelRuntime.cleanup`` ids are also protected: a FOLLOWUP
        session's Time's up id can be reachable only via
        ``ChannelRuntime.cleanup`` (set by the end-of-session sequence), so this
        guards it until the *next* session start consumes/clears it —
        past that point (no non-terminal session in the channel), those
        ids belong to a finished session and are eligible for deletion.
        """
        protected: set[int] = set()
        channel_runtime = self._rt.peek_channel(channel_id)

        session = self._registry.find_active_in_text_channel(str(channel_id))
        runtime = (
            self._rt.peek_session(session.session_id) if session is not None else None
        )
        if runtime is not None:
            if runtime.edit_state is not None:
                protected.add(runtime.edit_state.message.id)

            setup = runtime.setup
            if setup is not None:
                for message_id in (
                    setup.welcome_message_id,
                    setup.intention_message_id,
                    setup.nudge_message_id,
                ):
                    if message_id is not None:
                        protected.add(message_id)

            if runtime.reflect_message_id is not None:
                protected.add(runtime.reflect_message_id)

        if session is not None and channel_runtime is not None:
            cleanup = channel_runtime.cleanup
            for message_id in (
                cleanup.times_up_id,
                cleanup.reflect_id,
                cleanup.why_id,
            ):
                if message_id is not None:
                    protected.add(message_id)

        if channel_runtime is not None:
            if channel_runtime.chain is not None:
                protected.add(channel_runtime.chain.message_id)
            if channel_runtime.break_state is not None:
                protected.add(channel_runtime.break_state.message_id)

        return protected

    async def _handle_clear(self, interaction: discord.Interaction) -> None:
        """Handle /clear.

        Guard → defer ephemeral → scan up to ``CLEAR_SCAN_LIMIT`` messages
        of channel history → delete each bot-authored, non-protected,
        delete-eligible message one at a time (no bulk delete — the bot
        has no Manage Messages permission of its own) → report the count.
        """
        if not interaction.permissions.manage_messages:
            await interaction.response.send_message(CLEAR_NO_PERMISSION, ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, (discord.VoiceChannel, discord.TextChannel)):
            await interaction.response.send_message(MSG_WRONG_CHANNEL, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel_id = channel.id
        protected = self._protected_message_ids(channel_id)

        # Only Ocha's own messages — other bots' messages are never touched.
        bot_id = self.client.user.id if self.client.user else None
        deleted_count = 0
        attempted_delete = False
        async for message in channel.history(limit=CLEAR_SCAN_LIMIT):
            if bot_id is None or message.author.id != bot_id:
                continue
            if message.id in protected:
                continue
            embed_titles = [
                embed.title for embed in message.embeds if embed.title is not None
            ]
            if not is_delete_eligible(
                content=message.content, embed_titles=embed_titles
            ):
                continue
            # Pace deletes to stay under Discord's per-channel delete limit
            # (~5 per 5 s) instead of relying on 429 retries.
            if attempted_delete:
                await asyncio.sleep(CLEAR_DELETE_INTERVAL_SECONDS)
            attempted_delete = True
            if not await best_effort(
                message.delete(),
                logger,
                "Failed to delete message %s in channel %s via /clear",
                message.id,
                channel_id,
            ):
                continue

            deleted_count += 1
            # The message is gone — clear any cleanup field that pointed at
            # it, so the next session start doesn't try to delete/edit a
            # message that no longer exists.
            channel_runtime = self._rt.peek_channel(channel_id)
            if channel_runtime is not None:
                cleanup = channel_runtime.cleanup
                if cleanup.times_up_id == message.id:
                    cleanup.times_up_id = None
                if cleanup.reflect_id == message.id:
                    cleanup.reflect_id = None
                if cleanup.why_id == message.id:
                    cleanup.why_id = None

        logger.info(
            "Cleared %s message(s) in channel %s via /clear",
            deleted_count,
            channel_id,
        )
        if deleted_count > 0:
            await interaction.followup.send(
                CLEAR_DONE.format(n=deleted_count), ephemeral=True
            )
        else:
            await interaction.followup.send(CLEAR_NOTHING, ephemeral=True)
