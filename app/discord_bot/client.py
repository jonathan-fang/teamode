"""Discord client, slash command registration, invocation guard, and welcome embed."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence

import discord
from discord import app_commands

from app.config import TEAMODE_DEV_GUILD_IDS, TEAMODE_TIMEZONE
from app.db import CrashedSession
from app.discord_bot.breaks import BreakMixin
from app.discord_bot.clear import ClearMixin
from app.discord_bot.commands import CommandsMixin
from app.discord_bot.lifecycle import LifecycleMixin
from app.discord_bot.runtime import RuntimeStore
from app.discord_bot.stats import StatsMixin
from app.discord_bot.tasks import spawn_logged
from app.discord_bot.timer import TimerMixin
from app.discord_bot.views import ViewsMixin
from app.rate_limit import RateLimiter
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class TeaModeBot(
    CommandsMixin,
    ViewsMixin,
    TimerMixin,
    LifecycleMixin,
    BreakMixin,
    ClearMixin,
    StatsMixin,
):
    """Owns the Discord client, command tree, DB connection, and session registry.

    Dependencies (conn and registry) are injected by the entry point so that
    tests can substitute fakes without touching this module.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: SessionRegistry,
        crashed_sessions: Sequence[CrashedSession] = (),
    ) -> None:
        self._conn = conn
        self._registry = registry

        # Sessions marked crashed at startup, whose Discord messages are
        # tidied once after the first on_ready (see
        # LifecycleMixin._cleanup_crashed_sessions). Emptied when handed off,
        # so gateway reconnects (which re-fire on_ready) don't repeat it.
        self._crashed_sessions: list[CrashedSession] = list(crashed_sessions)

        # Per-user sliding-window and per-guild daily-cap rate limiting for
        # /teamode invocations. In-memory only — resets on restart.
        self._rate_limiter = RateLimiter(tz=TEAMODE_TIMEZONE)

        # Everything kept in memory about live sessions and text channels
        # (messages to edit or delete later, background tasks, the chain
        # prompt, breaks, streaks). In-memory only — lost on restart.
        self._rt = RuntimeStore()

        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True
        # reactions intent: required to receive on_raw_reaction_add events.
        intents.reactions = True

        # discord.py auto-reconnects the gateway with exponential backoff on
        # websocket drop. No reconnect handling needed in our code.
        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

        # Wire event handlers.
        self.client.event(self.on_ready)
        self.client.event(self.on_interaction)
        self.client.event(self.on_raw_reaction_add)
        self.client.event(self.on_voice_state_update)

        # Register the slash commands on this instance.
        self._register_command()
        self._register_clear_command()
        self._register_stats_command()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (id=%s)",
            self.client.user,
            self.client.user and self.client.user.id,
        )

        if TEAMODE_DEV_GUILD_IDS:
            for gid in TEAMODE_DEV_GUILD_IDS:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                try:
                    await self.tree.sync(guild=guild)
                    logger.info("Slash commands synced to guild %s", gid)
                except discord.Forbidden:
                    logger.warning(
                        "Cannot sync commands to guild %s — bot lacks access, skipping",
                        gid,
                    )
        else:
            logger.warning(
                "TEAMODE_DEV_GUILD_ID is not set — skipping command registration. "
                "Set TEAMODE_DEV_GUILD_ID to your dev guild id for instant "
                "command propagation."
            )

        if self._crashed_sessions:
            crashed, self._crashed_sessions = self._crashed_sessions, []
            spawn_logged(self._cleanup_crashed_sessions(crashed), name="crash-cleanup")

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route component interactions (button clicks, select menus, etc.).

        Dispatch structure: parse ``custom_id`` → route by purpose segment.
        Adding a new purpose requires only a new branch in the
        ``if purpose == ...`` block below — the parse logic is shared.

        Application-command interactions are forwarded to the command tree
        instead of being handled here.
        """
        # Application commands are handled by the CommandTree before this
        # on_interaction callback fires; no forwarding needed here.
        if interaction.type != discord.InteractionType.component:
            return

        data = interaction.data
        if data is None:
            return
        raw_custom_id = data.get("custom_id")
        if not isinstance(raw_custom_id, str):
            return
        parts = raw_custom_id.split(":")

        # Ignore custom_ids that don't belong to teamode (e.g. other bots).
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
        elif purpose == "again":
            await self._handle_go_again(interaction, session_id, parts)
        elif purpose == "break":
            await self._handle_break(interaction, session_id, parts)

    def run(self, token: str) -> None:
        """Start the Discord event loop."""
        self.client.run(token)
