"""Color palette, timer-pick handling, the intention modal, and embed builders."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Protocol

import discord

from app import session as session_module
from app import timer_format
from app import voice
from app.config import TEAMODE_TIMEZONE
from app.constants import (
    BACKOFF_FLOOR_DEFAULT,
    COLOR_MATCHA_SAGE,
    COLOR_MUTED_GREY,
    COLOR_MUTED_RED,
    COLOR_OOLONG_AMBER,
    COLOR_STEEPING_FOREST,
    DURATIONS_MINUTES,
    INTENTION_FIELD_LABEL,
    INTENTION_LINE_UNSET,
    INTENTION_MAX_LENGTH,
    INTENTION_MODAL_TITLE,
    MSG_NOT_FACILITATOR,
    MSG_SESSION_INACTIVE,
    MSG_VOICE_CONNECT_FAILED,
    PHASE_DEEP_FOCUS,
    SESSION_RECORD_INTENTION_SET,
    SESSION_RECORD_INTENTION_UNSET,
    SESSION_RECORD_META,
    TEACUP_BANNER,
    TIMER_BUTTON_LABEL,
    TIMER_CONTENT,
    TIMER_EMBED_TITLE,
    TIMER_FIELD_FACILITATOR,
    TIMER_FIELD_INTENTION,
    TIMER_FIELD_RANGE,
    TIMER_FIELD_VALUE_MAX_LENGTH,
    TIMER_REMAINING,
    TIMER_TIME_RANGE,
    VOICE_STATUS_TIMER,
    WELCOME_BANNER_BLOCK,
    WELCOME_EMBED_DESCRIPTION,
    WELCOME_EMBED_TITLE,
)
from app.discord_bot.tasks import spawn_logged
from app.session import SessionRegistry, SessionState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette — from UI-ADR § "Color palette"
# ---------------------------------------------------------------------------

COLORS = {
    "active": discord.Color.from_str(COLOR_MATCHA_SAGE),
    "wrap_up": discord.Color.from_str(COLOR_OOLONG_AMBER),
    "end_of_session": discord.Color.from_str(COLOR_STEEPING_FOREST),
    "refusal": discord.Color.from_str(COLOR_MUTED_GREY),
    "crashed": discord.Color.from_str(COLOR_MUTED_RED),
    "completed": discord.Color.from_str(COLOR_OOLONG_AMBER),
}


def _now() -> datetime:
    """Return the current UTC time — the single seam patched in tests that
    need a fixed ``started_at``."""
    return datetime.now(timezone.utc)


def _truncate_field_value(value: str) -> str:
    """Truncate *value* to fit an embed field's 1024-char limit.

    Cuts to ``TIMER_FIELD_VALUE_MAX_LENGTH - 1`` characters plus an
    ellipsis when over the limit — the intention field can hold up to
    ``INTENTION_MAX_LENGTH`` (4000) characters, well past the embed limit.
    """
    if len(value) <= TIMER_FIELD_VALUE_MAX_LENGTH:
        return value
    return value[: TIMER_FIELD_VALUE_MAX_LENGTH - 1] + "…"


def _build_timer_message(
    *,
    intention: str | None,
    duration_minutes: int,
    facilitator_id: str,
    started_at: datetime,
    seconds_remaining: int,
    mention_line: str,
) -> tuple[str, discord.Embed]:
    """Build the active-timer message content and embed together — the ONE
    place both the initial send and every tick edit build these, so they can
    never drift apart.

    ``mention_line`` is the pre-snapshotted @-mention line for the
    session's non-bot voice members (built once, when the timer message is
    first sent) — empty when there are none, in which case no extra content
    line is added. ``facilitator_id`` is the *current* facilitator (a
    handoff is reflected on the next tick edit, since the caller re-reads
    the session each time).
    """
    total_seconds = duration_minutes * 60
    elapsed_seconds = total_seconds - seconds_remaining
    mmss = timer_format.format_mmss(seconds_remaining)
    phase = timer_format.select_phase(seconds_remaining)
    progress_line = timer_format.format_progress_bar(elapsed_seconds, total_seconds)

    intention_value = intention.strip() if intention and intention.strip() else None
    intention_field_value = _truncate_field_value(
        intention_value if intention_value is not None else INTENTION_LINE_UNSET
    )

    embed = discord.Embed(
        title=TIMER_EMBED_TITLE.format(duration=duration_minutes),
        description=(
            f"### {phase}\n### {TIMER_REMAINING.format(mmss=mmss)}\n### {progress_line}"
        ),
        color=COLORS["active"] if phase == PHASE_DEEP_FOCUS else COLORS["wrap_up"],
    )
    embed.add_field(
        name=TIMER_FIELD_INTENTION, value=intention_field_value, inline=False
    )
    embed.add_field(
        name=TIMER_FIELD_FACILITATOR, value=f"<@{facilitator_id}>", inline=False
    )
    embed.add_field(
        name=TIMER_FIELD_RANGE,
        value=TIMER_TIME_RANGE.format(
            start=timer_format.format_hhmm(started_at, TEAMODE_TIMEZONE),
            end=timer_format.format_hhmm(
                started_at + timedelta(minutes=duration_minutes), TEAMODE_TIMEZONE
            ),
        ),
        inline=False,
    )

    content = TIMER_CONTENT.format(mmss=mmss)
    if mention_line:
        content = f"{content}\n{mention_line}"
    return content, embed


def _build_session_record_content(
    *,
    intention: str | None,
    duration_minutes: int,
    facilitator_id: str,
    started_at: datetime,
) -> str:
    """Build the plain-text record a finished session's timer message is
    rewritten to at session end (see LifecycleMixin._run_end_of_session).

    Replaces the fielded timer embed with a compact, permanent plain-text
    block — intention, then duration + facilitator, then the time range —
    so the channel's long-term history isn't a lingering multi-field embed.
    """
    intention_value = intention.strip() if intention and intention.strip() else None
    intention_line = (
        SESSION_RECORD_INTENTION_SET.format(
            intention=_truncate_field_value(intention_value)
        )
        if intention_value is not None
        else SESSION_RECORD_INTENTION_UNSET
    )
    meta_line = SESSION_RECORD_META.format(
        duration=duration_minutes, facilitator_id=facilitator_id
    )
    range_line = TIMER_TIME_RANGE.format(
        start=timer_format.format_hhmm(started_at, TEAMODE_TIMEZONE),
        end=timer_format.format_hhmm(
            started_at + timedelta(minutes=duration_minutes), TEAMODE_TIMEZONE
        ),
    )
    return f"{intention_line}\n{meta_line}\n{range_line}"


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
    backoff_floor: float = BACKOFF_FLOOR_DEFAULT
    # seconds_remaining at the moment of the last HTTP 429, or None if none
    # has happened yet (or the last edit since then succeeded). Ticks are
    # gated until backoff_floor seconds have elapsed since that value.
    last_429_seconds_remaining: int | None = None
    # Snapshot of the @-mention line for non-bot voice members, built once
    # when the timer message is first sent, so tick edits reuse it verbatim.
    mention_line: str = ""
    # Timezone-aware activation time, captured once when the timer message
    # is first sent, so every edit's "Range" field reads the same
    # value. Defaults to "now" only for callers (tests) that don't care.
    started_at: datetime = field(default_factory=_now)
    # Set once the wrap-up nudge has fired for this session, so a second
    # tick landing on the trigger boundary (e.g. after a backoff skip) never
    # double-sends it.
    nudge_sent: bool = False


@dataclass
class _SetupMessages:
    """Message ids captured at session start, for later edit/delete.

    ``channel_id`` is the text-chat channel (shared id with the voice
    channel) the welcome message was posted in — messages are always
    edited/deleted through the channel, never through the interaction
    webhook, since interaction tokens expire well before a session ends.
    """

    channel_id: int
    welcome_message_id: int
    intention_message_id: int | None = None
    # Set once the wrap-up nudge message has been sent (see TimerMixin),
    # so terminal cleanup deletes it alongside the welcome and Set
    # Intention messages. None when no nudge has fired (e.g. short
    # sessions, or terminal cleanup before the trigger point).
    nudge_message_id: int | None = None


@dataclass
class _ChannelCleanup:
    """Message ids from the most recently finished session in a text
    channel, kept so the *next* ``/teamode`` invocation in that channel can
    clean them up.

    ``times_up_id`` is the "Time's up" message, ``reflect_id`` is the
    Reflect (facilitator follow-up prompt) message, and ``why_id`` is the
    "share what got in the way" line posted only when the facilitator
    answered ⛔. In-memory only — lost on restart (accepted), like the
    dict it replaces.
    """

    times_up_id: int | None = None
    reflect_id: int | None = None
    why_id: int | None = None


# ---------------------------------------------------------------------------
# Structural bot shape needed by IntentionModal
# ---------------------------------------------------------------------------


class _ModalBot(Protocol):
    """The slice of :class:`~app.discord_bot.client.TeaModeBot` that
    :class:`IntentionModal` reads and mutates.

    ``TeaModeBot`` is composed from mixins rather than a single class body,
    so ``ViewsMixin`` (which owns ``_handle_timer_pick``) cannot import the
    concrete ``TeaModeBot`` without a cycle. Typing ``IntentionModal.bot``
    against this Protocol instead lets ``ViewsMixin`` pass ``self`` directly
    — ``ViewsMixin`` structurally satisfies it once it declares the same
    members below (see ``ViewsMixin``), no cast required.
    """

    client: discord.Client
    _registry: SessionRegistry
    _voice_clients: dict[int, discord.VoiceClient]
    _edit_states: dict[int, _EditState]
    _countdown_tasks: dict[int, asyncio.Task[None]]
    _pending_expiry_tasks: dict[int, asyncio.Task[None]]
    _setup_messages: dict[int, _SetupMessages]

    async def _on_countdown_tick(
        self, session_id: int, seconds_remaining: int
    ) -> None: ...

    async def _run_end_of_session(
        self,
        *,
        session_id: int,
        voice_client: discord.VoiceClient,
        channel: discord.abc.Messageable | None,
    ) -> None: ...

    async def _on_session_terminal(
        self,
        session_id: int,
        *,
        delete_setup_messages: bool = True,
    ) -> None: ...

    async def _set_voice_status(
        self, voice_channel_or_id: discord.VoiceChannel | int, status: str
    ) -> None: ...

    def _reset_streak(self, channel_id: int) -> None: ...

    def _pop_chained_flag(self, session_id: int) -> bool: ...


# ---------------------------------------------------------------------------
# IntentionModal
# ---------------------------------------------------------------------------


class IntentionModal(discord.ui.Modal, title=INTENTION_MODAL_TITLE):
    """Modal that captures the facilitator's session intention.

    Opened after a timer-pick button click.  On submit, records the
    intention via the registry and posts the public participant prompt.
    """

    intention_field: discord.ui.Label = discord.ui.Label(
        text=INTENTION_FIELD_LABEL,
        component=discord.ui.TextInput(
            style=discord.TextStyle.long,
            max_length=INTENTION_MAX_LENGTH,
            required=False,
        ),
    )

    def __init__(
        self,
        *,
        bot: _ModalBot,
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
        # Double-submit guard: the session must still be PENDING. Because
        # `set_intention` is synchronous and transitions the session before
        # any `await`, a check here — before that call — is sufficient under
        # asyncio's single-threaded cooperative scheduling: no other submit
        # can interleave between this check and the transition below.
        session_check = self._bot._registry.get(self._session_id)
        if not _session_actionable(session_check, expect=SessionState.PENDING):
            await _send_refusal(interaction, MSG_SESSION_INACTIVE)
            return

        component = self.intention_field.component
        if not isinstance(component, discord.ui.TextInput):
            # Genuinely impossible given the class-level declaration above,
            # but ``Label.component`` is typed as the broader ``Item`` —
            # narrow defensively rather than trusting the declared shape.
            logger.error(
                "intention_field.component is not a TextInput: %r", type(component)
            )
            intention_text = ""
        else:
            intention_text = component.value or ""
        session = self._bot._registry.set_intention(
            session_id=self._session_id,
            intention=intention_text,
        )
        # The session has left PENDING — the pending-expiry watchdog no
        # longer applies.
        expiry_task = self._bot._pending_expiry_tasks.pop(self._session_id, None)
        if expiry_task is not None:
            expiry_task.cancel()
        # Acknowledge the modal interaction without cluttering the channel.
        await interaction.response.defer(ephemeral=True)

        # Disable the welcome message's duration buttons now that the
        # intention has been submitted — re-picking a duration no longer
        # makes sense past this point. Edited through the channel (the
        # welcome lives in the voice channel's text chat), never through the
        # interaction webhook. Best-effort: a failure here must not block
        # voice connect / session activation below.
        setup = self._bot._setup_messages.get(self._session_id)
        if setup is not None:
            try:
                await self._voice_channel.get_partial_message(
                    setup.welcome_message_id
                ).edit(view=_build_timer_view(self._session_id, disabled=True))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Failed to disable welcome buttons on intention submit"
                    " for session %s",
                    self._session_id,
                )

        # --- Connect voice ---
        # Use the channel resolved at click-handler time — no REST round-trip.
        voice_channel = self._voice_channel
        try:
            voice_client = await voice.connect(voice_channel)
        except Exception:
            logger.exception("Voice connect failed for session %s", self._session_id)
            await interaction.followup.send(MSG_VOICE_CONNECT_FAILED, ephemeral=True)
            self._bot._registry.mark_cancelled(session_id=self._session_id)
            self._bot._reset_streak(int(session.text_channel_id))
            self._bot._pop_chained_flag(self._session_id)
            # No voice status here: the bot never connected, and Discord
            # requires Manage Channels to set a voice status while
            # disconnected (see LifecycleMixin._set_voice_status).
            await self._bot._on_session_terminal(self._session_id)
            return

        # Stash the voice client so the solo-grace flow can disconnect it.
        self._bot._voice_clients[self._session_id] = voice_client

        # --- Advance to ACTIVE and post the timer message ---
        self._bot._registry.mark_active(session_id=self._session_id)
        assert session.duration_minutes is not None

        # Captured once, here, and reused by every tick edit so "Range"
        # never drifts across the session, and by the Timer voice status
        # set immediately below.
        started_at = _now()
        ends_at = started_at + timedelta(minutes=session.duration_minutes)
        await self._bot._set_voice_status(
            voice_channel,
            VOICE_STATUS_TIMER.format(
                hhmm=timer_format.format_hhmm(ends_at, TEAMODE_TIMEZONE)
            ),
        )

        # Snapshot the @-mention set for non-bot voice members — the same
        # filter used for the participant prompt — so the initial timer
        # message pings everyone present. Stored on the edit state so tick
        # edits reuse it verbatim without re-pinging (see timer.py, which
        # sends edits with AllowedMentions.none()).
        bot_id = self._bot.client.user.id if self._bot.client.user else None
        mention_members = [
            m for m in voice_channel.members if not m.bot and m.id != bot_id
        ]
        mention_line = " ".join(m.mention for m in mention_members)

        # Bookkeeping only: a DB failure must never break the session.
        try:
            self._bot._registry.record_participants(
                session_id=self._session_id,
                user_ids=[str(m.id) for m in mention_members],
            )
            logger.info(
                "Session %s participants recorded: %d",
                self._session_id,
                len(mention_members),
            )
        except sqlite3.Error:
            logger.exception(
                "Failed to record participants for session %s", self._session_id
            )

        initial_content, initial_embed = _build_timer_message(
            intention=session.intention,
            duration_minutes=session.duration_minutes,
            facilitator_id=session.handoff_facilitator_id or session.facilitator_id,
            started_at=started_at,
            seconds_remaining=session.duration_minutes * 60,
            mention_line=mention_line,
        )
        # Send on the voice channel resolved at click-handler time — the same
        # typed reference used to connect above, so no cast is needed here.
        timer_message = await voice_channel.send(
            content=initial_content, embed=initial_embed
        )

        # Stash edit state so the tick callback can reach it.
        self._bot._edit_states[self._session_id] = _EditState(
            message=timer_message,
            mention_line=mention_line,
            started_at=started_at,
        )

        # --- Schedule countdown, then run the full end-of-session sequence ---
        session_id = self._session_id
        # The voice channel resolved at click-handler time is Messageable —
        # reuse it for the end-of-session messages, same as the timer message.
        channel: discord.abc.Messageable = voice_channel

        async def _run_and_followup() -> None:
            duration_minutes = session.duration_minutes
            if duration_minutes is None:
                # Genuinely impossible at this point in the flow (duration is
                # set before the intention modal opens), but abort cleanly
                # rather than asserting inside a background task.
                logger.error(
                    "Session %s has no duration_minutes at countdown start",
                    session_id,
                )
                return
            await session_module.run_countdown(
                duration_minutes=duration_minutes,
                on_tick=lambda s: self._bot._on_countdown_tick(session_id, s),
            )
            self._bot._registry.mark_followup(session_id=session_id)
            # Clean up per-session resource dicts. _edit_states is left for
            # _run_end_of_session to consume (it finalizes the timer message
            # from it) and pop itself.
            self._bot._voice_clients.pop(session_id, None)
            self._bot._countdown_tasks.pop(session_id, None)
            # Run the full end-of-session sequence.
            await self._bot._run_end_of_session(
                session_id=session_id,
                voice_client=voice_client,
                channel=channel,
            )

        task = spawn_logged(_run_and_followup(), name=f"session-followup:{session_id}")
        self._bot._countdown_tasks[session_id] = task


# ---------------------------------------------------------------------------
# ViewsMixin — timer-pick button handling
# ---------------------------------------------------------------------------


class ViewsMixin:
    """Timer-pick button handling, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation, and so `self`
    # structurally satisfies `_ModalBot` when passed to IntentionModal
    # (see `_ModalBot` above) without a cast.
    client: discord.Client
    _registry: SessionRegistry
    _voice_clients: dict[int, discord.VoiceClient]
    _edit_states: dict[int, _EditState]
    _countdown_tasks: dict[int, asyncio.Task[None]]
    _pending_expiry_tasks: dict[int, asyncio.Task[None]]
    _setup_messages: dict[int, _SetupMessages]

    if TYPE_CHECKING:
        # Methods provided by TimerMixin / LifecycleMixin at runtime — declared
        # here, type-checking only, purely so `self` matches `_ModalBot`'s
        # shape. Guarded by TYPE_CHECKING so this never shadows the real
        # implementations at runtime (ViewsMixin precedes them in the MRO).
        async def _on_countdown_tick(
            self, session_id: int, seconds_remaining: int
        ) -> None: ...

        async def _run_end_of_session(
            self,
            *,
            session_id: int,
            voice_client: discord.VoiceClient,
            channel: discord.abc.Messageable | None,
        ) -> None: ...

        async def _on_session_terminal(
            self,
            session_id: int,
            *,
            delete_setup_messages: bool = True,
        ) -> None: ...

        async def _set_voice_status(
            self, voice_channel_or_id: discord.VoiceChannel | int, status: str
        ) -> None: ...

        def _reset_streak(self, channel_id: int) -> None: ...

        def _pop_chained_flag(self, session_id: int) -> bool: ...

    async def _handle_timer_pick(
        self,
        interaction: discord.Interaction,
        session_id: int,
        parts: list[str],
    ) -> None:
        """Handle a timer-pick button click."""
        session = self._registry.get(session_id)
        if not _session_actionable(session, expect=SessionState.PENDING):
            await _send_refusal(interaction, MSG_SESSION_INACTIVE)
            return
        assert session is not None  # narrowed by _session_actionable above

        if str(interaction.user.id) != session.facilitator_id:
            await _send_refusal(interaction, MSG_NOT_FACILITATOR)
            return

        # Parse the duration value from the custom_id.
        try:
            duration_minutes = int(parts[3])
        except (IndexError, ValueError):
            logger.warning("Malformed timer custom_id: %r", ":".join(parts))
            return

        # Reject any duration not offered by the timer-pick buttons (e.g. a
        # tampered or stale custom_id) — refuse without advancing state.
        if duration_minutes not in DURATIONS_MINUTES:
            await _send_refusal(interaction, MSG_SESSION_INACTIVE)
            return

        self._registry.set_duration(
            session_id=session_id,
            duration_minutes=duration_minutes,
        )

        # The pending-expiry watchdog stays armed: the session is still
        # PENDING until the intention modal is submitted, and a dismissed
        # modal (with the duration buttons still enabled) must still expire.

        # The welcome's duration buttons stay enabled here — the facilitator
        # may dismiss the modal and re-pick a duration; the latest pick wins
        # (set_duration overwrites). Buttons are disabled once the intention
        # is actually submitted (see IntentionModal.on_submit).

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


# ---------------------------------------------------------------------------
# Shared stale-button handling
# ---------------------------------------------------------------------------


def _session_actionable(
    session: session_module.Session | None, *, expect: SessionState
) -> bool:
    """Return whether a component interaction on *session* should proceed.

    ``False`` covers every "stale button" case: the session is missing
    (e.g. after a restart), terminal, or not in the state the button
    expects (e.g. a timer-pick after the duration was already picked).
    Callers refuse with :data:`MSG_SESSION_INACTIVE` when this is ``False``.
    """
    if session is None:
        return False
    return session.state == expect


async def _send_refusal(interaction: discord.Interaction, message: str) -> None:
    """Send the standard ephemeral refusal embed (muted-grey, plain body).

    Shared by every guard refusal — stale-session, wrong-state, and
    non-facilitator — so new buttons get consistent styling for free.
    """
    embed = discord.Embed(description=message, color=COLORS["refusal"])
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Embed and view builders
# ---------------------------------------------------------------------------


def _build_welcome_embed() -> discord.Embed:
    """Construct the welcome embed (matcha sage accent, 🍵 + ⏳ pair).

    Copy source: UI-ADR § "Surface inventory" — welcome embed greets the
    facilitator and prompts tea / desk / distractions check.
    """
    embed = discord.Embed(
        title=WELCOME_EMBED_TITLE,
        description=WELCOME_BANNER_BLOCK.format(banner=TEACUP_BANNER)
        + WELCOME_EMBED_DESCRIPTION,
        color=COLORS["active"],
    )
    return embed


def _build_timer_view(session_id: int, *, disabled: bool = False) -> discord.ui.View:
    """Build the duration timer-pick button row for *session_id*.

    Custom_ids follow UI-ADR § "Custom_id namespace":
    ``teamode:<session_id>:timer:<value>``. Pass ``disabled=True`` to build
    the all-disabled row shown after pending expiry.
    """
    view = discord.ui.View()
    for minutes in DURATIONS_MINUTES:
        button: discord.ui.Button[discord.ui.View] = discord.ui.Button(
            label=TIMER_BUTTON_LABEL.format(minutes=minutes),
            custom_id=f"teamode:{session_id}:timer:{minutes}",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        view.add_item(button)
    return view
