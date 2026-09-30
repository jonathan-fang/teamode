"""Chaining prompt (Go again / break offer), streak tracking, and break
lifecycle (five-minute and ten-minute).

After the facilitator answers the follow-up ✅/⛔, :class:`LifecycleMixin`
posts a chaining prompt via :meth:`BreakMixin._post_chain_prompt`. From
there, either button offered by that prompt is handled here:

- **Go again** hands off to the shared session start (``_start_session``) —
  the clicker becomes facilitator.
- **Break** (five-minute, or ten-minute after a streak — see below) starts
  an in-memory timer; Ocha joins voice for its duration and shows a break
  voice status; on completion Ocha plays the reverie, leaves, and posts a
  fresh chaining prompt with just a Go again button (with its own expiry).

**Streak tracking**: :data:`_streaks` holds, per text channel, the
durations of consecutive qualifying sessions (each at least
``LONG_BREAK_MIN_SESSION_MINUTES`` minutes, ending with a facilitator ✅ or
⛔, and — after the first — started via Go again). Once the streak reaches
``LONG_BREAK_STREAK`` entries, :meth:`_post_chain_prompt` offers a
ten-minute break (:data:`CHAIN_PROMPT_STREAK`) instead of the normal
five-minute offer. :data:`_chained_via_go_again` records, per session,
whether it was started via Go again — read once (and popped) by
``_post_chain_prompt`` to decide whether to extend or restart the streak.
Both are in-memory only and reset per :meth:`_reset_streak` /
:meth:`_pop_chained_flag`'s callers: a break starting, a session started
via ``/teamode``, a session shorter than the threshold, a follow-up
timeout, or a session cancellation (solo grace, voice-connect failure,
pending expiry).

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
    BUTTON_LONG_BREAK,
    CHAIN_PROMPT,
    CHAIN_PROMPT_STREAK,
    GO_AGAIN_TIMEOUT_SECONDS,
    LONG_BREAK_MIN_SESSION_MINUTES,
    LONG_BREAK_MINUTES,
    LONG_BREAK_STREAK,
    MSG_NOT_IN_VOICE,
    MSG_SESSION_INACTIVE,
    STREAK_DURATION_ITEM,
    STREAK_DURATION_SEPARATOR,
    VOICE_STATUS_BREAK,
    VOICE_STATUS_BREAK_OVER,
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

    ``kind`` distinguishes the three prompts this module posts, since they
    need different button rows when disabled: ``"chain"`` is the normal
    prompt posted right after ✅/⛔ (Go again + five-minute break),
    ``"chain_streak"`` is the same moment's prompt when the channel's
    streak qualifies for a ten-minute break offer instead (Go again +
    long break), and ``"post_break"`` is the prompt posted after a break
    ends (Go again only).

    ``timeout_task`` is set only for a ``"post_break"`` prompt — the
    ``GO_AGAIN_TIMEOUT_SECONDS`` watchdog that disables the button if
    nobody clicks it. Cancelled by whatever clears the chain state first.
    """

    session_id: int
    channel_id: int
    message_id: int
    kind: Literal["chain", "chain_streak", "post_break"] = "chain"
    timeout_task: asyncio.Task[None] | None = None


@dataclass
class _BreakState:
    """An in-progress break (five- or ten-minute) in one text channel.

    ``session_id`` is the session whose chaining prompt started this break
    — reused as the ``session_id`` in the post-break Go again button's
    custom_id, so that click is valid (Go again does not require an
    existing session row; it only reads the id back off the custom_id).

    ``voice_client`` is the client connected at break start (``None`` if
    that connect attempt failed) — reused at break end, and disconnected
    by :meth:`BreakMixin._cancel_break` if a new session supersedes the
    break before it ends.
    """

    task: asyncio.Task[None]
    message_id: int
    end_time: datetime
    session_id: int
    voice_client: discord.VoiceClient | None = None


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


def _build_streak_chain_view(
    session_id: int, *, disabled: bool = False
) -> discord.ui.View:
    """Build the Go again / ten-minute break offer row for *session_id*.

    Posted instead of :func:`_build_chain_view` once the channel's streak
    of chained, qualifying sessions reaches ``LONG_BREAK_STREAK``. The long
    break's custom_id carries a trailing ``:long`` value so
    ``BreakMixin._handle_break`` can tell the two break buttons apart.
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
            label=BUTTON_LONG_BREAK,
            custom_id=f"teamode:{session_id}:break:long",
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
    # Per-channel streak of chained, qualifying session durations — see the
    # module docstring. Reset by _reset_streak; extended by _post_chain_prompt.
    _streaks: dict[int, list[int]]
    # Per-session record of whether it was started via Go again — read once
    # (and popped) by _post_chain_prompt via _pop_chained_flag.
    _chained_via_go_again: dict[int, bool]

    if TYPE_CHECKING:
        # Provided by CommandsMixin — declared here, type-checking only.
        async def _start_session(
            self, interaction: discord.Interaction, *, via_go_again: bool = False
        ) -> None: ...

        # Provided by LifecycleMixin — same reasoning.
        async def _set_voice_status(
            self, voice_channel_or_id: discord.VoiceChannel | int, status: str
        ) -> None: ...

    # ------------------------------------------------------------------
    # Chaining prompt
    # ------------------------------------------------------------------

    async def _post_chain_prompt(self, session_id: int, text_channel_id: str) -> None:
        """Post the Go again / break offer prompt for *session_id*.

        Called after a facilitator ✅ or ⛔ is processed (after the ⛔ "why"
        line, when present) — never after a follow-up timeout. Updates the
        channel's streak first (see the module docstring): a session not
        started via Go again always restarts the streak; a qualifying
        session (``duration_minutes >= LONG_BREAK_MIN_SESSION_MINUTES``)
        then extends it, otherwise the streak is cleared. Once the streak
        reaches ``LONG_BREAK_STREAK`` entries, the streak prompt (long
        break offer) is posted instead of the normal one. Send failures are
        logged at WARNING and leave no chain state behind.
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

        session = self._registry.get(session_id)
        duration = session.duration_minutes if session is not None else None
        chained = self._pop_chained_flag(session_id)
        qualifies = duration is not None and duration >= LONG_BREAK_MIN_SESSION_MINUTES

        if not chained:
            self._streaks.pop(channel_id, None)
        if qualifies:
            assert duration is not None  # narrowed by `qualifies` above
            self._streaks.setdefault(channel_id, []).append(duration)
        else:
            self._streaks.pop(channel_id, None)

        streak = self._streaks.get(channel_id, [])
        kind: Literal["chain", "chain_streak"]
        if len(streak) >= LONG_BREAK_STREAK:
            text = CHAIN_PROMPT_STREAK.format(
                count=len(streak),
                durations=STREAK_DURATION_SEPARATOR.join(
                    STREAK_DURATION_ITEM.format(minutes=m) for m in streak
                ),
            )
            view = _build_streak_chain_view(session_id)
            kind = "chain_streak"
        else:
            text = CHAIN_PROMPT
            view = _build_chain_view(session_id)
            kind = "chain"

        try:
            message = await channel.send(text, view=view)
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
            kind=kind,
        )

    def _reset_streak(self, channel_id: int) -> None:
        """Clear the chained-session streak for *channel_id*, if any.

        Called whenever the streak must restart from scratch: a break
        starting, a session started via ``/teamode``, a follow-up timeout,
        or a session cancellation. A short or non-chained qualifying
        session resets the streak inline in :meth:`_post_chain_prompt`
        instead, since that path also needs to seed the fresh streak.
        """
        self._streaks.pop(channel_id, None)

    def _pop_chained_flag(self, session_id: int) -> bool:
        """Pop and return whether *session_id* was started via Go again.

        Defaults to ``False`` (a plain ``/teamode`` start, or a session id
        this bot instance never recorded — e.g. after a restart).
        """
        return self._chained_via_go_again.pop(session_id, False)

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
        if chain.kind == "chain":
            view = _build_chain_view(chain.session_id, disabled=True)
        elif chain.kind == "chain_streak":
            view = _build_streak_chain_view(chain.session_id, disabled=True)
        else:
            view = _build_post_break_view(chain.session_id, disabled=True)
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

        await self._start_session(interaction, via_go_again=True)

    async def _handle_break(
        self,
        interaction: discord.Interaction,
        session_id: int,
        parts: list[str],
    ) -> None:
        """Handle a Take a break button click (five-minute, or ten-minute
        when the custom_id carries a trailing ``:long`` value).

        Valid only while the chain state for this channel exists and
        matches *session_id*. The clicker must be in the voice channel
        (ephemeral ``MSG_NOT_IN_VOICE`` otherwise, but their click does not
        clear the still-valid chain state). Any break resets the channel's
        streak, and Ocha joins voice for its duration (see the module
        docstring and ``_run_break``).
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

        is_long = len(parts) > 3 and parts[3] == "long"
        break_minutes = LONG_BREAK_MINUTES if is_long else BREAK_MINUTES

        # Clear the chain state before acknowledging — a race with another
        # click sees no chain state and is refused as stale. Any break
        # (long or short) resets the streak.
        await self._clear_chain_state(channel_id)
        self._reset_streak(channel_id)

        await interaction.response.defer()

        end_time = _now() + timedelta(minutes=break_minutes)
        hhmm = timer_format.format_hhmm(end_time, TEAMODE_TIMEZONE)
        break_message = await channel.send(BREAK_STARTED.format(hhmm=hhmm))

        # Join voice for the break and show a break status — Ocha stays
        # connected silently until the break ends. A connect failure is
        # logged and the break continues without a status (the end still
        # tries to connect, same as today).
        voice_client: discord.VoiceClient | None = None
        try:
            voice_client = await voice.connect(channel)
        except Exception:
            logger.warning(
                "Voice connect failed for break start in channel %s", channel_id
            )
            voice_client = None

        if voice_client is not None:
            await self._set_voice_status(channel, VOICE_STATUS_BREAK.format(hhmm=hhmm))

        task = spawn_logged(
            self._run_break(
                channel_id=channel_id,
                session_id=session_id,
                voice_channel=channel,
                break_minutes=break_minutes,
                voice_client=voice_client,
            ),
            name=f"break:{channel_id}",
        )
        self._break_states[channel_id] = _BreakState(
            task=task,
            message_id=break_message.id,
            end_time=end_time,
            session_id=session_id,
            voice_client=voice_client,
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
        break_minutes: int = BREAK_MINUTES,
        voice_client: discord.VoiceClient | None = None,
    ) -> None:
        """Sleep *break_minutes*, then run the break-over sequence.

        *voice_client* is the client connected at break start, if that
        connect succeeded — reused here rather than reconnecting. If it is
        ``None`` (start-time connect failed, or a direct/test caller passed
        none), a connect is attempted here as before. The break-over voice
        status is set before reverie playback so it is visible for the
        whole disconnect sequence.

        Cancelled (via ``_break_states[channel_id].task.cancel()``) when a
        new session starts in this channel — see
        ``CommandsMixin._start_session`` / ``_cancel_break``.
        """
        try:
            await asyncio.sleep(break_minutes * 60)
        except asyncio.CancelledError:
            return

        self._break_states.pop(channel_id, None)
        logger.info("Break ended in channel %s for session %s", channel_id, session_id)

        if voice_client is None or not voice_client.is_connected():
            try:
                voice_client = await voice.connect(voice_channel)
            except Exception:
                logger.warning(
                    "Voice connect failed for break end in channel %s", channel_id
                )
                voice_client = None

        if voice_client is not None:
            await self._set_voice_status(
                voice_channel,
                VOICE_STATUS_BREAK_OVER.format(
                    hhmm=timer_format.format_hhmm(_now(), TEAMODE_TIMEZONE)
                ),
            )
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

        Disconnects the break's voice client (if it connected), so the new
        session's own voice connect isn't fighting an existing connection.
        No status is set here — the new session's own Timer status (once
        it activates) overwrites whatever the break last showed. Edits the
        break message to ``BREAK_CANCELLED``. Called when a new session
        starts in this channel (``/teamode`` or Go again) — see
        ``CommandsMixin._start_session``.
        """
        break_state = self._break_states.pop(channel_id, None)
        if break_state is None:
            return
        if not break_state.task.done():
            break_state.task.cancel()

        if break_state.voice_client is not None:
            try:
                await voice.disconnect(break_state.voice_client)
            except Exception:
                logger.warning(
                    "Failed to disconnect break voice client in channel %s",
                    channel_id,
                )

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
