"""Discord client, slash command registration, invocation guard, and welcome embed."""

from __future__ import annotations

import asyncio
import logging
import sqlite3

import discord
from discord import app_commands

from app.config import TEAMODE_DEV_GUILD_IDS, TEAMODE_TIMEZONE
from app.discord_bot.breaks import BreakMixin, _BreakState, _ChainState
from app.discord_bot.commands import CommandsMixin
from app.discord_bot.lifecycle import LifecycleMixin
from app.discord_bot.timer import TimerMixin
from app.discord_bot.views import (
    ViewsMixin,
    _ChannelCleanup,
    _EditState,
    _SetupMessages,
)
from app.rate_limit import RateLimiter
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class TeaModeBot(CommandsMixin, ViewsMixin, TimerMixin, LifecycleMixin, BreakMixin):
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

        # Per-user sliding-window and per-guild daily-cap rate limiting for
        # /teamode invocations. In-memory only — resets on restart.
        self._rate_limiter = RateLimiter(tz=TEAMODE_TIMEZONE)

        # Per-session edit state, keyed by session_id.
        # Populated when an active timer message is posted; removed on followup.
        self._edit_states: dict[int, _EditState] = {}

        # Per-session watchdog tasks for the 3-minute follow-up timeout.
        # Keyed by session_id; cancelled on facilitator reaction.
        self._watchdog_tasks: dict[int, asyncio.Task[None]] = {}

        # Per-session Reflect message ids; maps session_id → message.id.
        # Used by on_raw_reaction_add to identify which session a reaction belongs to.
        self._reflect_message_ids: dict[int, int] = {}

        # Per-session voice client; populated after voice.connect succeeds.
        # Cleared at normal end-of-session and by the solo-grace timeout flow.
        self._voice_clients: dict[int, discord.VoiceClient] = {}

        # Per-session countdown asyncio.Task; populated when _run_and_followup is
        # scheduled. Cancelled by the solo-grace timeout to prevent the normal
        # end-of-session sequence from racing in.
        self._countdown_tasks: dict[int, asyncio.Task[None]] = {}

        # Per-session solo-grace watchdog tasks; keyed by session_id.
        # Armed when the facilitator leaves and no other humans remain.
        # Cancelled on facilitator rejoin; self-clearing on timeout.
        self._solo_grace_tasks: dict[int, asyncio.Task[None]] = {}

        # Per-session pending-expiry watchdog tasks; keyed by session_id.
        # Armed at session start; cancelled once a duration is picked;
        # self-clearing (and cancelling the session) on timeout.
        self._pending_expiry_tasks: dict[int, asyncio.Task[None]] = {}

        # Per-session welcome / Set-Intention message ids, keyed by
        # session_id — captured at session start for later edit/delete via
        # the channel (never the interaction webhook).
        self._setup_messages: dict[int, _SetupMessages] = {}

        # The most recently finished session's cleanup-relevant message ids
        # per text-channel id (Time's up, Reflect, and the ⛔ "why" line).
        # In-memory only — lost on restart (accepted). Cleaned up when the
        # next session starts in that channel.
        self._channel_cleanup: dict[int, _ChannelCleanup] = {}

        # The standing "Go again / break offer" chaining prompt per text
        # channel — posted after a facilitator ✅/⛔, and again (Go-again
        # only) after a break ends. In-memory only — lost on restart.
        # Cleared when a break starts or a new session starts in the
        # channel (see BreakMixin._clear_chain_state).
        self._chain_states: dict[int, _ChainState] = {}

        # The in-progress five-minute break per text channel, if any.
        # In-memory only — lost on restart. Cancelled when a new session
        # starts in the channel (see BreakMixin._cancel_break).
        self._break_states: dict[int, _BreakState] = {}

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
        elif purpose == "again":
            await self._handle_go_again(interaction, session_id, parts)
        elif purpose == "break":
            await self._handle_break(interaction, session_id, parts)

    def run(self, token: str) -> None:
        """Start the Discord event loop."""
        self.client.run(token)
