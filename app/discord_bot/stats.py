"""The /stats command: sessions, focus minutes and completion rate."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands

from app.config import TEAMODE_TIMEZONE
from app.constants import (
    MSG_WRONG_CHANNEL,
    STATS_COMMAND_DESCRIPTION,
    STATS_EMPTY,
    STATS_SECTION_SERVER,
    STATS_SECTION_YOU,
    STATS_TITLE,
)
from app.db import fetch_user_stats_rows, fetch_guild_stats_rows
from app.discord_bot.views import COLORS
from app.stats import (
    compute_stats_summary,
    compute_streak,
    render_section_value,
    render_streak_line,
)


class StatsMixin:
    """The /stats command, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check this mixin's own methods in isolation.
    tree: app_commands.CommandTree
    _conn: sqlite3.Connection

    def _register_stats_command(self) -> None:
        """Register /stats on the command tree."""

        @self.tree.command(
            name="stats",
            description=STATS_COMMAND_DESCRIPTION,
        )
        async def stats(interaction: discord.Interaction) -> None:
            await self._handle_stats(interaction)

    async def _handle_stats(self, interaction: discord.Interaction) -> None:
        """Handle /stats: an ephemeral embed of You / This server stats."""
        if interaction.guild_id is None:
            await interaction.response.send_message(MSG_WRONG_CHANNEL, ephemeral=True)
            return

        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild_id)
        now = datetime.now(timezone.utc)
        tz = TEAMODE_TIMEZONE

        you_rows = fetch_user_stats_rows(self._conn, user_id=user_id)
        server_rows = fetch_guild_stats_rows(self._conn, guild_id=guild_id)

        you_summary = compute_stats_summary(you_rows, now=now)
        server_summary = compute_stats_summary(server_rows, now=now)

        embed = discord.Embed(title=STATS_TITLE, color=COLORS["active"])

        you_all_time = you_summary[2]
        server_all_time = server_summary[2]
        if you_all_time.sessions == 0 and server_all_time.sessions == 0:
            embed.description = STATS_EMPTY
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        streak_days = compute_streak(you_rows, now=now, tz=tz)
        streak_line = render_streak_line(streak_days)

        embed.add_field(
            name=STATS_SECTION_YOU,
            value=render_section_value(you_summary, streak_line=streak_line),
            inline=False,
        )
        embed.add_field(
            name=STATS_SECTION_SERVER,
            value=render_section_value(server_summary),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
