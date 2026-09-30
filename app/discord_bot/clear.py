"""The /teamode-clear command: deletes past TeaMode clutter in a channel."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from app.cleanup import is_delete_eligible
from app.constants import (
    CLEAR_COMMAND_DESCRIPTION,
    CLEAR_DONE,
    CLEAR_NO_PERMISSION,
    CLEAR_NOTHING,
    CLEAR_SCAN_LIMIT,
    MSG_WRONG_CHANNEL,
)
from app.discord_bot.breaks import _BreakState, _ChainState
from app.discord_bot.views import _ChannelCleanup, _EditState, _SetupMessages
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class ClearMixin:
    """The /teamode-clear command, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check this mixin's own methods in isolation.
    client: discord.Client
    tree: app_commands.CommandTree
    _registry: SessionRegistry
    _edit_states: dict[int, _EditState]
    _setup_messages: dict[int, _SetupMessages]
    _reflect_message_ids: dict[int, int]
    _channel_cleanup: dict[int, _ChannelCleanup]
    _chain_states: dict[int, _ChainState]
    _break_states: dict[int, _BreakState]

    def _register_clear_command(self) -> None:
        """Register /teamode-clear on the command tree."""

        @self.tree.command(
            name="teamode-clear",
            description=CLEAR_COMMAND_DESCRIPTION,
        )
        async def teamode_clear(interaction: discord.Interaction) -> None:
            await self._handle_clear(interaction)

    def _protected_message_ids(self, channel_id: int) -> set[int]:
        """Return message ids to keep in *channel_id* for /teamode-clear.

        Covers the channel's non-terminal session (if any) — its timer
        message, its welcome / Set-Intention / nudge messages, and its
        Reflect message (a session in FOLLOWUP, awaiting ✅/⛔, is
        non-terminal, so this also protects a live Reflect prompt) — plus
        the live chaining prompt (any kind: chain / chain_streak /
        post_break) and the live break message, if either is standing in
        this channel.

        While the channel has a non-terminal session, its
        ``_channel_cleanup`` entry (if any) is also protected: a FOLLOWUP
        session's Time's up id can be reachable only via
        ``_channel_cleanup`` (set by the end-of-session sequence), so this
        guards it until the *next* session start consumes/clears it —
        past that point (no non-terminal session in the channel), those
        ids belong to a finished session and are eligible for deletion.
        """
        protected: set[int] = set()

        session = self._registry.find_active_in_text_channel(str(channel_id))
        if session is not None:
            sid = session.session_id
            edit_state = self._edit_states.get(sid)
            if edit_state is not None:
                protected.add(edit_state.message.id)

            setup = self._setup_messages.get(sid)
            if setup is not None:
                for message_id in (
                    setup.welcome_message_id,
                    setup.intention_message_id,
                    setup.nudge_message_id,
                ):
                    if message_id is not None:
                        protected.add(message_id)

            reflect_id = self._reflect_message_ids.get(sid)
            if reflect_id is not None:
                protected.add(reflect_id)

            cleanup = self._channel_cleanup.get(channel_id)
            if cleanup is not None:
                for message_id in (
                    cleanup.times_up_id,
                    cleanup.reflect_id,
                    cleanup.why_id,
                ):
                    if message_id is not None:
                        protected.add(message_id)

        chain = self._chain_states.get(channel_id)
        if chain is not None:
            protected.add(chain.message_id)

        break_state = self._break_states.get(channel_id)
        if break_state is not None:
            protected.add(break_state.message_id)

        return protected

    async def _handle_clear(self, interaction: discord.Interaction) -> None:
        """Handle /teamode-clear.

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

        deleted_count = 0
        async for message in channel.history(limit=CLEAR_SCAN_LIMIT):
            if not message.author.bot:
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
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Failed to delete message %s in channel %s via /teamode-clear",
                    message.id,
                    channel_id,
                )
                continue

            deleted_count += 1
            # The message is gone — clear any _channel_cleanup field that
            # pointed at it, so the next session start doesn't try to
            # delete/edit a message that no longer exists.
            cleanup = self._channel_cleanup.get(channel_id)
            if cleanup is not None:
                if cleanup.times_up_id == message.id:
                    cleanup.times_up_id = None
                if cleanup.reflect_id == message.id:
                    cleanup.reflect_id = None
                if cleanup.why_id == message.id:
                    cleanup.why_id = None

        logger.info(
            "Cleared %s message(s) in channel %s via /teamode-clear",
            deleted_count,
            channel_id,
        )
        if deleted_count > 0:
            await interaction.followup.send(
                CLEAR_DONE.format(n=deleted_count), ephemeral=True
            )
        else:
            await interaction.followup.send(CLEAR_NOTHING, ephemeral=True)
