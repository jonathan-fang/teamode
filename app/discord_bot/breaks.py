"""Chaining prompt (Go again / break offer) and five-minute break lifecycle.

After the facilitator answers the follow-up ✅/⛔, :class:`LifecycleMixin`
posts a chaining prompt via :meth:`BreakMixin._post_chain_prompt`. From
there, either button offered by that prompt is handled here:

- **Go again** hands off to the shared session start (``_start_session``) —
  the clicker becomes facilitator.
- **Break** starts an in-memory five-minute timer; on completion Ocha joins
  voice, plays the reverie, leaves, and posts a fresh chaining prompt with
  just a Go again button (with its own expiry).

Both the chaining prompt and the break are in-memory, per text-channel
state — lost on restart, and cleared whenever a break starts or a new
session starts in that channel (see ``_clear_chain_state`` /
``_cancel_break``, called from ``CommandsMixin._start_session``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import discord

from app import timer_format, voice
from app.config import TEAMODE_TIMEZONE
from app.constants import (
    BREAK_CANCELLED,
    BREAK_MINUTES,
    BREAK_OVER,
    BREAK_STARTED,
    BUTTON_BREAK,
    BUTTON_GO_AGAIN,
    CHAIN_PROMPT,
    GO_AGAIN_TIMEOUT_SECONDS,
    MSG_NOT_IN_VOICE,
    MSG_SESSION_INACTIVE,
)
from app.discord_bot.tasks import spawn_logged
from app.discord_bot.views import _now, _send_refusal
from app.session import SessionRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-channel state
# ---------------------------------------------------------------------------


@dataclass
class _ChainState:
    """A standing chaining prompt (Go again [/ break]) in one text channel.

    ``kind`` distinguishes the two prompts this module posts, since they
    need different button rows when disabled: ``"chain"`` is the prompt
    posted right after ✅/⛔ (Go again + break), ``"post_break"`` is the
    prompt posted after a break ends (Go again only).

    ``timeout_task`` is set only for a ``"post_break"`` prompt — the
    ``GO_AGAIN_TIMEOUT_SECONDS`` watchdog that disables the button if
    nobody clicks it. Cancelled by whatever clears the chain state first.
    """

    session_id: int
    channel_id: int
    message_id: int
    kind: Literal["chain", "post_break"] = "chain"
    timeout_task: asyncio.Task[None] | None = None


@dataclass
class _BreakState:
    """An in-progress five-minute break in one text channel.

    ``session_id`` is the session whose chaining prompt started this break
    — reused as the ``session_id`` in the post-break Go again button's
    custom_id, so that click is valid (Go again does not require an
    existing session row; it only reads the id back off the custom_id).
    """

    task: asyncio.Task[None]
    message_id: int
    end_time: datetime
    session_id: int


# ---------------------------------------------------------------------------
# View builders
# ---------------------------------------------------------------------------


def _build_chain_view(session_id: int, *, disabled: bool = False) -> discord.ui.View:
    """Build the Go again / break offer row for *session_id*.

    Custom_ids follow the ``teamode:<session_id>:<purpose>`` namespace:
    ``teamode:<session_id>:again`` and ``teamode:<session_id>:break``.
    """
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=BUTTON_GO_AGAIN,
            custom_id=f"teamode:{session_id}:again",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
    )
    view.add_item(
        discord.ui.Button(
            label=BUTTON_BREAK,
            custom_id=f"teamode:{session_id}:break",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
    )
    return view


def _build_post_break_view(
    session_id: int, *, disabled: bool = False
) -> discord.ui.View:
    """Build the single Go again button row posted after a break ends."""
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=BUTTON_GO_AGAIN,
            custom_id=f"teamode:{session_id}:again",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
    )
    return view


# ---------------------------------------------------------------------------
# BreakMixin
# ---------------------------------------------------------------------------


class BreakMixin:
    """Chaining prompt and break lifecycle, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check this mixin's own methods in isolation.
    client: discord.Client
    _registry: SessionRegistry
    _chain_states: dict[int, _ChainState]
    _break_states: dict[int, _BreakState]

    if TYPE_CHECKING:
        # Provided by CommandsMixin — declared here, type-checking only.
        async def _start_session(self, interaction: discord.Interaction) -> None: ...

    # ------------------------------------------------------------------
    # Chaining prompt
    # ------------------------------------------------------------------

    async def _post_chain_prompt(self, session_id: int, text_channel_id: str) -> None:
        """Post the Go again / break offer prompt for *session_id*.

        Called after a facilitator ✅ or ⛔ is processed (after the ⛔ "why"
        line, when present) — never after a follow-up timeout. Send
        failures are logged at WARNING and leave no chain state behind.
        """
        channel_id = int(text_channel_id)
        channel = self.client.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning(
                "Channel %s is not sendable — skipping chain prompt for session %s",
                channel_id,
                session_id,
            )
            return
        try:
            message = await channel.send(
                CHAIN_PROMPT, view=_build_chain_view(session_id)
            )
        except discord.HTTPException:
            logger.warning(
                "Failed to send chain prompt for session %s in channel %s",
                session_id,
                channel_id,
            )
            return
        self._chain_states[channel_id] = _ChainState(
            session_id=session_id,
            channel_id=channel_id,
            message_id=message.id,
        )

    async def _disable_chain_message(self, chain: _ChainState) -> None:
        """Edit *chain*'s message to an all-disabled button row.

        Never raises: a missing channel type or a failed edit is logged at
        WARNING and swallowed.
        """
        channel = self.client.get_channel(chain.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            logger.warning(
                "Channel %s for chain state is not a VoiceChannel —"
                " skipping button disable",
                chain.channel_id,
            )
            return
        view = (
            _build_chain_view(chain.session_id, disabled=True)
            if chain.kind == "chain"
            else _build_post_break_view(chain.session_id, disabled=True)
        )
        try:
            await channel.get_partial_message(chain.message_id).edit(view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to disable chain prompt buttons for session %s in channel %s",
                chain.session_id,
                chain.channel_id,
            )

    async def _clear_chain_state(self, channel_id: int) -> None:
        """Pop and disable the standing chain prompt in *channel_id*, if any.

        Cancels its expiry watchdog (the post-break Go again timeout), if
        one is armed. Called when a break starts or a new session starts in
        this channel. Not used by the expiry watchdog itself — it pops and
        disables directly to avoid cancelling its own running task.
        """
        chain = self._chain_states.pop(channel_id, None)
        if chain is None:
            return
        if chain.timeout_task is not None and not chain.timeout_task.done():
            chain.timeout_task.cancel()
        await self._disable_chain_message(chain)

    # ------------------------------------------------------------------
    # Router entry points
    # ------------------------------------------------------------------

    async def _handle_go_again(
        self,
        interaction: discord.Interaction,
        session_id: int,
        parts: list[str],
    ) -> None:
        """Handle a Go again button click.

        Valid only while the chain state for this channel exists and
        matches *session_id* (see ``_ChainState``) — this replaces the
        generic stale-session refusal for this purpose. Any voice-channel
        member may click; whoever does becomes facilitator, via the same
        guarded path as ``/teamode``.
        """
        channel_id = interaction.channel_id
        chain = self._chain_states.get(channel_id) if channel_id is not None else None
        if chain is None or chain.session_id != session_id:
            await _send_refusal(interaction, MSG_SESSION_INACTIVE)
            return

        await self._start_session(interaction)

    async def _handle_break(
        self,
        interaction: discord.Interaction,
        session_id: int,
        parts: list[str],
    ) -> None:
        """Handle a Take a 5-minute break button click.

        Valid only while the chain state for this channel exists and
        matches *session_id*. The clicker must be in the voice channel
        (ephemeral ``MSG_NOT_IN_VOICE`` otherwise, but their click does not
        clear the still-valid chain state).
        """
        channel_id = interaction.channel_id
        chain = self._chain_states.get(channel_id) if channel_id is not None else None
        if chain is None or chain.session_id != session_id:
            await _send_refusal(interaction, MSG_SESSION_INACTIVE)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.VoiceChannel):
            await _send_refusal(interaction, MSG_SESSION_INACTIVE)
            return
        # Narrowed to a VoiceChannel — use its id (always present) rather
        # than the interaction's optional channel_id from here on.
        channel_id = channel.id

        user = interaction.user
        voice_state = user.voice if isinstance(user, discord.Member) else None
        user_in_voice = (
            voice_state is not None
            and voice_state.channel is not None
            and voice_state.channel.id == channel.id
        )
        if not user_in_voice:
            await _send_refusal(interaction, MSG_NOT_IN_VOICE)
            return

        # Clear the chain state before acknowledging — a race with another
        # click sees no chain state and is refused as stale.
        await self._clear_chain_state(channel_id)

        await interaction.response.defer()

        end_time = _now() + timedelta(minutes=BREAK_MINUTES)
        hhmm = timer_format.format_hhmm(end_time, TEAMODE_TIMEZONE)
        break_message = await channel.send(BREAK_STARTED.format(hhmm=hhmm))

        task = spawn_logged(
            self._run_break(
                channel_id=channel_id,
                session_id=session_id,
                voice_channel=channel,
            ),
            name=f"break:{channel_id}",
        )
        self._break_states[channel_id] = _BreakState(
            task=task,
            message_id=break_message.id,
            end_time=end_time,
            session_id=session_id,
        )
        logger.info(
            "Break started in channel %s for session %s — back at %s",
            channel_id,
            session_id,
            hhmm,
        )

    # ------------------------------------------------------------------
    # Break lifecycle
    # ------------------------------------------------------------------

    async def _run_break(
        self,
        *,
        channel_id: int,
        session_id: int,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        """Sleep ``BREAK_MINUTES``, then run the break-over sequence.

        Cancelled (via ``_break_states[channel_id].task.cancel()``) when a
        new session starts in this channel — see
        ``CommandsMixin._start_session`` / ``_cancel_break``.
        """
        try:
            await asyncio.sleep(BREAK_MINUTES * 60)
        except asyncio.CancelledError:
            return

        self._break_states.pop(channel_id, None)
        logger.info("Break ended in channel %s for session %s", channel_id, session_id)

        voice_client: discord.VoiceClient | None = None
        try:
            voice_client = await voice.connect(voice_channel)
        except Exception:
            logger.warning(
                "Voice connect failed for break end in channel %s", channel_id
            )

        if voice_client is not None:
            playback_ok = await voice.play_reverie_then_disconnect(voice_client)
            if not playback_ok:
                logger.warning(
                    "Reverie playback failed for break end in channel %s", channel_id
                )

        channel = self.client.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning(
                "Channel %s is not sendable — skipping break-over message", channel_id
            )
            return

        over_message = await channel.send(
            BREAK_OVER, view=_build_post_break_view(session_id)
        )

        timeout_task = spawn_logged(
            self._run_go_again_timeout(channel_id=channel_id),
            name=f"go-again-timeout:{channel_id}",
        )
        self._chain_states[channel_id] = _ChainState(
            session_id=session_id,
            channel_id=channel_id,
            message_id=over_message.id,
            kind="post_break",
            timeout_task=timeout_task,
        )

    async def _run_go_again_timeout(self, *, channel_id: int) -> None:
        """Disable the post-break Go again button after ``GO_AGAIN_TIMEOUT_SECONDS``.

        Cancelled if Go again is clicked (chain state consumed by
        ``_start_session``) or a new session starts in the channel (see
        ``_clear_chain_state``).
        """
        try:
            await asyncio.sleep(GO_AGAIN_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return

        chain = self._chain_states.pop(channel_id, None)
        if chain is None:
            return
        await self._disable_chain_message(chain)
        logger.info("Post-break Go again expired in channel %s", channel_id)

    async def _cancel_break(self, channel_id: int) -> None:
        """Pop and cancel the in-progress break in *channel_id*, if any.

        Edits the break message to ``BREAK_CANCELLED``. Called when a new
        session starts in this channel (``/teamode`` or Go again) — see
        ``CommandsMixin._start_session``.
        """
        break_state = self._break_states.pop(channel_id, None)
        if break_state is None:
            return
        if not break_state.task.done():
            break_state.task.cancel()

        channel = self.client.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            logger.warning(
                "Channel %s for break state is not a VoiceChannel —"
                " skipping cancel edit",
                channel_id,
            )
            return
        try:
            await channel.get_partial_message(break_state.message_id).edit(
                content=BREAK_CANCELLED
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to edit break message to cancelled in channel %s", channel_id
            )
        logger.info("Break cancelled by new session in channel %s", channel_id)
