"""Color palette, timer-pick handling, the intention modal, and embed builders."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import discord

from app import session as session_module
from app import voice
from app.constants import (
    ACTIVE_TIMER_FMT,
    BACKOFF_FLOOR_DEFAULT,
    COLOR_MATCHA_SAGE,
    COLOR_MUTED_GREY,
    COLOR_MUTED_RED,
    COLOR_OOLONG_AMBER,
    COLOR_STEEPING_FOREST,
    DURATIONS_MINUTES,
    INTENTION_FIELD_LABEL,
    INTENTION_LINE_SET,
    INTENTION_LINE_UNSET,
    INTENTION_MAX_LENGTH,
    INTENTION_MODAL_TITLE,
    MSG_NOT_FACILITATOR,
    MSG_SESSION_INACTIVE,
    MSG_VOICE_CONNECT_FAILED,
    TIMER_BUTTON_LABEL,
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
    "end_of_session": discord.Color.from_str(COLOR_STEEPING_FOREST),
    "refusal": discord.Color.from_str(COLOR_MUTED_GREY),
    "crashed": discord.Color.from_str(COLOR_MUTED_RED),
    "completed": discord.Color.from_str(COLOR_OOLONG_AMBER),
}


def _format_timer(seconds_remaining: int) -> str:
    """Format *seconds_remaining* as ``mm:ss`` (zero-padded)."""
    mm, ss = divmod(seconds_remaining, 60)
    return f"{mm:02d}:{ss:02d}"


def _format_intention_line(intention: str | None) -> str:
    """Render the first line of the active timer message.

    Returns the placeholder when no intention was captured.
    """
    if intention and intention.strip():
        return INTENTION_LINE_SET.format(intention=intention)
    return INTENTION_LINE_UNSET


def _build_active_timer_content(
    *,
    intention: str | None,
    duration_minutes: int | None,
    seconds_remaining: int,
    mention_line: str,
) -> str:
    """Build the active-timer message content — the ONE place both the
    initial send and every tick edit build this string, so they can never
    drift apart.

    ``mention_line`` is the pre-snapshotted @-mention line for the
    session's non-bot voice members (built once, when the timer message is
    first sent) — empty when there are none, in which case no extra line
    is added.
    """
    mm, ss = divmod(seconds_remaining, 60)
    base = ACTIVE_TIMER_FMT.format(
        intention_line=_format_intention_line(intention),
        duration=duration_minutes,
        mm=mm,
        ss=ss,
    )
    if mention_line:
        return f"{base}\n{mention_line}"
    return base


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
        self, session_id: int, *, delete_setup_messages: bool = True
    ) -> None: ...


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

        # --- Connect voice ---
        # Use the channel resolved at click-handler time — no REST round-trip.
        voice_channel = self._voice_channel
        try:
            voice_client = await voice.connect(voice_channel)
        except Exception:
            logger.exception("Voice connect failed for session %s", self._session_id)
            await interaction.followup.send(MSG_VOICE_CONNECT_FAILED, ephemeral=True)
            self._bot._registry.mark_cancelled(session_id=self._session_id)
            await self._bot._on_session_terminal(self._session_id)
            return

        # Stash the voice client so the solo-grace flow can disconnect it.
        self._bot._voice_clients[self._session_id] = voice_client

        # --- Advance to ACTIVE and post the timer message ---
        self._bot._registry.mark_active(session_id=self._session_id)
        assert session.duration_minutes is not None

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

        initial_content = _build_active_timer_content(
            intention=session.intention,
            duration_minutes=session.duration_minutes,
            seconds_remaining=session.duration_minutes * 60,
            mention_line=mention_line,
        )
        # Send on the voice channel resolved at click-handler time — the same
        # typed reference used to connect above, so no cast is needed here.
        timer_message = await voice_channel.send(initial_content)

        # Stash edit state so the tick callback can reach it.
        self._bot._edit_states[self._session_id] = _EditState(
            message=timer_message, mention_line=mention_line
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
            self, session_id: int, *, delete_setup_messages: bool = True
        ) -> None: ...

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
        # modal (with the duration buttons now disabled) must still expire.

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
        description=WELCOME_EMBED_DESCRIPTION,
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
