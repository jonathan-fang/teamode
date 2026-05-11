"""Discord client, slash command registration, invocation guard, and welcome embed."""

from __future__ import annotations

import asyncio
import logging
import random
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
_MSG_PARTICIPANT_PROMPT = "🥅 **[Set Intention]** Please share your intention for this session in voice or type it in the chat."

# Voice connect failure — ephemeral, short, clear.
_MSG_VOICE_CONNECT_FAILED = "Could not join voice — session cancelled."

# Active timer message format (two spaces between intention and timer per Spec).
_ACTIVE_TIMER_FMT = "{intention_line}\n{duration} min session\n⏳ {mm:02d}:{ss:02d}"

# Edit cadence per UI-ADR § "Timer edit cadence".
_EDIT_INTERVAL_SECONDS = 10

# Backoff limits for 429 handling.
_BACKOFF_FLOOR_DEFAULT = 10.0
_BACKOFF_FLOOR_CAP = 60.0

# End-of-session embed — canonical from UI-ADR § "End-of-session embed copy".
_END_EMBED_TITLE = "✨ Session complete!"
_END_EMBED_BODY = "🌿 Sip your tea, stretch, and notice your progress."

# Follow-up timeout per Spec § "Edge Cases" (3-minute watchdog).
_FOLLOWUP_TIMEOUT_SECONDS = 180

# Solo-facilitator grace window: 5 minutes before auto-cancel.
_SOLO_GRACE_SECONDS = 300


def _format_timer(seconds_remaining: int) -> str:
    """Format *seconds_remaining* as ``mm:ss`` (zero-padded)."""
    mm, ss = divmod(seconds_remaining, 60)
    return f"{mm:02d}:{ss:02d}"


def _format_intention_line(intention: str | None) -> str:
    """Render the first line of the active timer message.

    Returns the placeholder when no intention was captured.
    """
    if intention and intention.strip():
        return f"🍵 Facilitator's Intention: {intention}"
    return "🍵 No intention set"


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
            required=False,
        ),
    )

    def __init__(
        self,
        *,
        bot: TeaModeBot,
        session_id: int,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        """Initialise the modal.

        *voice_channel* is the resolved ``discord.VoiceChannel`` from the
        click-handler call site.  Passing it here avoids a REST round-trip
        (``fetch_channel``) in :meth:`on_submit` and the permission gate that
        round-trip would cross.
        """
        super().__init__()
        self._bot = bot
        self._session_id = session_id
        self._voice_channel = voice_channel

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

        # --- Connect voice ---
        # Use the channel resolved at click-handler time — no REST round-trip.
        voice_channel = self._voice_channel
        try:
            voice_client = await voice.connect(voice_channel)
        except Exception:
            logger.exception("Voice connect failed for session %s", self._session_id)
            await interaction.followup.send(_MSG_VOICE_CONNECT_FAILED, ephemeral=True)
            self._bot._registry.mark_cancelled(session_id=self._session_id)
            return

        # Stash the voice client so the solo-grace flow can disconnect it.
        self._bot._voice_clients[self._session_id] = voice_client

        # --- Advance to ACTIVE and post the timer message ---
        self._bot._registry.mark_active(session_id=self._session_id)
        assert session.duration_minutes is not None
        initial_content = _ACTIVE_TIMER_FMT.format(
            intention_line=_format_intention_line(session.intention),
            duration=session.duration_minutes,
            mm=session.duration_minutes,
            ss=0,
        )
        # wait=True ensures we get the real WebhookMessage back (with .edit/.id).
        timer_message = await interaction.followup.send(
            initial_content, ephemeral=False, wait=True
        )

        # Stash edit state so the tick callback can reach it.
        self._bot._edit_states[self._session_id] = _EditState(message=timer_message)

        # --- Schedule countdown, then run the full end-of-session sequence ---
        session_id = self._session_id
        # Capture the channel reference for the end-of-session messages.
        # interaction.channel is a VoiceChannel here (enforced by the
        # /teamode guard), which is Messageable. Cast to satisfy pyright.
        channel = cast(discord.abc.Messageable | None, interaction.channel)

        async def _run_and_followup() -> None:
            await session_module.run_countdown(
                duration_minutes=session.duration_minutes,  # type: ignore[arg-type]
                on_tick=lambda s: self._bot._on_countdown_tick(session_id, s),
            )
            self._bot._registry.mark_followup(session_id=session_id)
            # Clean up edit state and per-session resource dicts.
            self._bot._edit_states.pop(session_id, None)
            self._bot._voice_clients.pop(session_id, None)
            self._bot._countdown_tasks.pop(session_id, None)
            # Run the full end-of-session sequence.
            await self._bot._run_end_of_session(
                session_id=session_id,
                voice_client=voice_client,
                channel=channel,
            )

        task = asyncio.create_task(_run_and_followup())
        self._bot._countdown_tasks[session_id] = task


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

        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True
        # reactions intent: required to receive on_raw_reaction_add events.
        intents.reactions = True

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
        Adding a new purpose requires only a new branch in the
        ``if purpose == ...`` block below — the parse logic is shared.

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

        # Disable the timer-pick buttons so a second click is impossible.
        # Must be done before opening the modal (responding to the interaction
        # with a modal consumes the response slot).
        assert interaction.message is not None
        view = discord.ui.View.from_message(interaction.message)
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.message.edit(view=view)

        # interaction.channel is guaranteed to be a VoiceChannel here — the
        # /teamode invocation guard (Guard 1 in _handle_teamode) already
        # enforced it.  The assert satisfies pyright's narrowing requirement.
        assert isinstance(interaction.channel, discord.VoiceChannel)
        modal = IntentionModal(
            bot=self,
            session_id=session_id,
            voice_channel=interaction.channel,
        )
        await interaction.response.send_modal(modal)

    async def _run_end_of_session(
        self,
        *,
        session_id: int,
        voice_client: discord.VoiceClient,
        channel: discord.abc.Messageable | None,
    ) -> None:
        """Run the full end-of-session sequence after countdown reaches zero.

        Order: Session-complete embed (@-mention) → reverie+disconnect
        → Reflect embed (facilitator prompt) → pre-populate reactions
        → 3-minute watchdog.
        """
        if channel is None:
            logger.warning(
                "No channel reference for session %s end-of-session sequence",
                session_id,
            )
            return

        # Step a: Snapshot voice channel members (excluding the bot).
        voice_channel = voice_client.channel
        if isinstance(voice_channel, discord.VoiceChannel):
            members = [
                m
                for m in voice_channel.members
                if not m.bot
                and m.id != (self.client.user.id if self.client.user else None)
            ]
        else:
            members = []

        if members:
            mentions = " ".join(m.mention for m in members)
            mention_content = f"Time's up, {mentions}!"
        else:
            mention_content = "Time's up!"

        # Step b: Post Session-complete embed with the @-mention content.
        session_complete_embed = discord.Embed(
            title=_END_EMBED_TITLE,
            description=f"### {_END_EMBED_BODY}",
            color=COLORS["end_of_session"],
        )
        await channel.send(content=mention_content, embed=session_complete_embed)

        # Step c: Reverie playback + disconnect.
        playback_ok = await voice.play_reverie_then_disconnect(voice_client)
        if not playback_ok:
            logger.warning("Reverie playback failed for session %s", session_id)

        # Step d: Post Reflect message with facilitator prompt.
        facilitator_prompt = "[Follow-up] React with ✅ if you finished, or ⛔ if not."
        reflect_embed = discord.Embed(
            title="🌿 [Reflect]",
            description=(
                "### Share how your session went!\n"
                "### · React with emoji\n"
                "### · Share in voice\n"
                "### · Or type in chat"
            ),
            color=COLORS["end_of_session"],
        )
        reflect_msg = await channel.send(
            content=facilitator_prompt, embed=reflect_embed
        )

        # Step e: Pre-populate reactions on the Reflect message.
        await reflect_msg.add_reaction("✅")
        await reflect_msg.add_reaction("⛔")

        # Step f: Store the Reflect message id for the reaction listener.
        self._reflect_message_ids[session_id] = reflect_msg.id

        # Step g: 3-minute watchdog.
        async def _watchdog() -> None:
            try:
                await asyncio.sleep(_FOLLOWUP_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                return
            # Watchdog fired — mark timeout and clean up.
            try:
                self._registry.mark_followup_timeout(session_id=session_id)
            except Exception:
                logger.exception(
                    "mark_followup_timeout failed for session %s", session_id
                )
            self._reflect_message_ids.pop(session_id, None)
            logger.info(
                "Follow-up watchdog fired for session %s — marked followup_timeout",
                session_id,
            )

        task: asyncio.Task[None] = asyncio.create_task(_watchdog())
        self._watchdog_tasks[session_id] = task

    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Facilitator-authoritative reaction handler for the Reflect message.

        The facilitator's ✅ or ⛔ reaction on the Reflect embed sets
        ``completed_intention`` and terminates the watchdog. Non-facilitator
        reactions and the bot's own pre-populated reactions are ignored.
        """
        # Ignore the bot's own pre-populated reactions.
        if self.client.user is not None and payload.user_id == self.client.user.id:
            return

        # Find the session whose Reflect message matches this payload.
        session_id: int | None = None
        for sid, msg_id in self._reflect_message_ids.items():
            if msg_id == payload.message_id:
                session_id = sid
                break
        if session_id is None:
            return

        # Look up the session; it must be in followup state.
        session = self._registry.get(session_id)
        if session is None:
            return
        from app.session import SessionState

        if session.state != SessionState.FOLLOWUP:
            return

        emoji_str = str(payload.emoji)
        if emoji_str not in ("✅", "⛔"):
            return

        # Non-facilitator reaction: log only.
        if payload.user_id != int(session.facilitator_id):
            logger.info(
                "Non-facilitator reaction %s by user %s on session %s — logged only",
                emoji_str,
                payload.user_id,
                session_id,
            )
            return

        # Facilitator reaction — authoritative answer.
        task = self._watchdog_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()

        # Pop the Reflect-message id to prevent duplicate handling.
        self._reflect_message_ids.pop(session_id, None)

        if emoji_str == "✅":
            self._registry.mark_completed(
                session_id=session_id,
                completed_intention=1,
                followup_note=None,
            )
        else:
            # ⛔ — record incomplete, then post the "why" prompt.
            self._registry.mark_completed(
                session_id=session_id,
                completed_intention=0,
                followup_note=None,
            )
            channel = self.client.get_channel(int(session.text_channel_id))
            if channel is not None:
                await cast(discord.abc.Messageable, channel).send(
                    f"<@{session.facilitator_id}> — share what got in the way: "
                    "type in chat or share in voice."
                )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Automatic facilitator handoff and solo-grace watchdog for voice events.

        Fires whenever any guild member's voice state changes.

        Join path: if the facilitator rejoins a channel with an active
        session and a solo-grace watchdog is pending, cancel the watchdog.

        Leave path: if the facilitator leaves a channel with an active session
        and no other humans remain, arm the 5-minute solo-grace watchdog. If
        other humans remain, pick a new facilitator at random (auto-handoff).
        """
        # Detect a join into a voice channel: after.channel is set and either
        # the member was not in voice before, or they moved to a different channel.
        if after.channel is not None and (
            before.channel is None or before.channel.id != after.channel.id
        ):
            joined_session = self._registry.find_active_in_voice_channel(
                str(after.channel.id)
            )
            if (
                joined_session is not None
                and str(member.id) == joined_session.facilitator_id
                and joined_session.session_id in self._solo_grace_tasks
            ):
                # Facilitator rejoined within the grace window — cancel watchdog.
                task = self._solo_grace_tasks.pop(joined_session.session_id)
                task.cancel()
                # No need to await — the watchdog's CancelledError handler cleans up.

        # Step 1 — Did this member just leave a voice channel?
        if before.channel is None:
            return
        if after.channel is not None and after.channel.id == before.channel.id:
            return  # Same channel — not a leave event.

        # Step 2 — Is there an in-progress session in the channel they left?
        session = self._registry.find_active_in_voice_channel(str(before.channel.id))
        if session is None:
            return

        # Step 3 — Is the leaver the current facilitator?
        if str(member.id) != session.facilitator_id:
            return

        # Step 4 — Count remaining human members (exclude the leaver and the bot).
        bot_id = self.client.user.id if self.client.user else None
        remaining = [
            m
            for m in before.channel.members
            if not m.bot and m.id != member.id and m.id != bot_id
        ]

        if not remaining:
            # Solo leave — arm the 5-minute rejoin watchdog.
            # Defensive guard: if one is already pending, don't double-arm.
            if session.session_id not in self._solo_grace_tasks:
                task = asyncio.create_task(
                    self._run_solo_grace(session_id=session.session_id),
                    name=f"solo-grace:{session.session_id}",
                )
                self._solo_grace_tasks[session.session_id] = task
            return

        # Step 5 — Pick a new facilitator at random and record the handoff.
        new_facilitator = random.choice(remaining)
        old_facilitator_id = (
            session.facilitator_id
        )  # snapshot before mark_handoff updates it
        self._registry.mark_handoff(
            session_id=session.session_id,
            handoff_facilitator_id=str(new_facilitator.id),
        )

        # Step 6 — Announce in the text channel.
        channel = self.client.get_channel(int(session.text_channel_id))
        if channel is not None:
            content = (
                f"<@{old_facilitator_id}> left — <@{new_facilitator.id}>,"
                " you're now the facilitator."
            )
            try:
                await channel.send(content)  # type: ignore[union-attr]
            except discord.HTTPException:
                logger.exception(
                    "Failed to announce auto handoff for session %s",
                    session.session_id,
                )

    async def _run_solo_grace(
        self,
        *,
        session_id: int,
        sleep_seconds: float = _SOLO_GRACE_SECONDS,
    ) -> None:
        """5-minute rejoin watchdog for solo facilitator-leave.

        Sleeps ``sleep_seconds``. If cancelled (facilitator rejoined), exits
        cleanly. If the sleep completes, terminates the session as
        ``cancelled``: rewrites the timer message, cancels the countdown task,
        disconnects voice, and writes status='cancelled' to SQLite.

        ``sleep_seconds`` defaults to ``_SOLO_GRACE_SECONDS``. Tests pass a
        small value (e.g. 0 or 0.01) to exercise the timeout path without
        waiting 5 minutes.
        """
        try:
            await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            # Facilitator rejoined within the grace window — nothing to do.
            return

        # Timeout fired. Resolve resources defensively (pops are no-ops if missing).
        countdown_task = self._countdown_tasks.pop(session_id, None)
        voice_client = self._voice_clients.pop(session_id, None)
        edit_state = self._edit_states.pop(session_id, None)
        self._solo_grace_tasks.pop(session_id, None)

        # 1) Cancel the countdown task so it doesn't trigger end-of-session.
        if countdown_task is not None:
            countdown_task.cancel()
            try:
                await countdown_task
            except (asyncio.CancelledError, Exception):
                # Best-effort: a swallowed exception here is acceptable —
                # we're tearing the session down anyway.
                pass

        # 2) Rewrite the timer message.
        if edit_state is not None:
            try:
                await edit_state.message.edit(
                    content="Session ended — facilitator did not return."
                )
            except discord.HTTPException:
                logger.exception(
                    "Failed to edit timer message on solo-grace timeout for session %s",
                    session_id,
                )

        # 3) Disconnect voice (no reverie).
        if voice_client is not None:
            try:
                await voice.disconnect(voice_client)
            except Exception:
                logger.exception(
                    "Failed to disconnect voice on solo-grace timeout for session %s",
                    session_id,
                )

        # 4) Write status='cancelled' to SQLite.
        try:
            self._registry.mark_cancelled(session_id=session_id)
        except Exception:
            logger.exception(
                "Failed to mark session %s cancelled on solo-grace timeout",
                session_id,
            )

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

        # Check the session for the message content.
        session = self._registry.get(session_id)
        if session is None:
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
                intention_line=_format_intention_line(session.intention),
                duration=session.duration_minutes,
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
        """Register /teamode and /handoff on the command tree.

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

        @self.tree.command(
            name="handoff",
            description="Transfer the facilitator role to another voice-channel member.",
            guild=guild_object,
        )
        @app_commands.describe(
            member="The voice-channel member to make the new facilitator."
        )
        async def handoff(
            interaction: discord.Interaction, member: discord.Member
        ) -> None:
            await self._handle_handoff(interaction, member)

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
            "### Time for TeaMode!\n"
            "### · Grab your tea (or water/beverage of your choice),\n"
            "### · Clear your desk,\n"
            "### · And silence all distractions (like phones, impromptu meetings).\n\n"
            "### ⏳ **How long would you like to focus today?**"
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
    for minutes in (5, 10, 25, 50):
        button: discord.ui.Button[discord.ui.View] = discord.ui.Button(
            label=f"{minutes} min",
            custom_id=f"teamode:{session_id}:timer:{minutes}",
            style=discord.ButtonStyle.secondary,
        )
        view.add_item(button)
    return view
