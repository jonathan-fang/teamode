"""Countdown tick handling: edit cadence, wrap-up nudge, and 429 backoff."""

from __future__ import annotations

import logging

import discord

from app import timer_format
from app.constants import (
    BACKOFF_FLOOR_CAP,
    BACKOFF_FLOOR_DEFAULT,
    EDIT_INTERVAL_SECONDS,
    MSG_WRAP_UP_NUDGE,
    WRAP_UP_MINUTES,
)
from app.discord_bot.views import _build_timer_message, _EditState
from app.session import SessionRegistry, SessionState

logger = logging.getLogger(__name__)


class TimerMixin:
    """Countdown tick callback, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation.
    _edit_states: dict[int, _EditState]
    _registry: SessionRegistry

    async def _on_countdown_tick(self, session_id: int, seconds_remaining: int) -> None:
        """Tick callback injected into ``run_countdown``.

        Fires every second.  Checks the one-time wrap-up nudge first (it has
        its own trigger point, independent of the edit cadence), then only
        attempts a Discord message edit on ticks that are multiples of
        *EDIT_INTERVAL_SECONDS* or on the final tick (``seconds_remaining ==
        0``).

        Skips the edit if the per-session lock is already held (a previous
        edit is still in flight).  Applies exponential backoff on HTTP 429.
        """
        edit_state = self._edit_states.get(session_id)
        if edit_state is None:
            # Session was cleaned up; nothing to do.
            return

        # Check the session for the message content.
        session = self._registry.get(session_id)
        if session is None:
            return

        # Wrap-up nudge: fires once, exactly at the trigger point, for
        # sessions long enough to warrant it. Checked before the edit-cadence
        # early return below since the trigger (WRAP_UP_MINUTES * 60) need
        # not fall on an EDIT_INTERVAL_SECONDS boundary in general (it does
        # today, but this keeps the two concerns independent).
        if (
            not edit_state.nudge_sent
            and session.duration_minutes is not None
            and timer_format.should_nudge(session.duration_minutes, seconds_remaining)
        ):
            # Re-check liveness at fire time — never nudge a session that
            # has since left ACTIVE (e.g. cancelled via solo grace).
            live_session = self._registry.get(session_id)
            if live_session is not None and live_session.state == SessionState.ACTIVE:
                edit_state.nudge_sent = True
                channel = getattr(edit_state.message, "channel", None)
                if channel is not None:
                    try:
                        await channel.send(
                            MSG_WRAP_UP_NUDGE.format(minutes=WRAP_UP_MINUTES)
                        )
                    except discord.HTTPException:
                        logger.warning(
                            "Failed to send wrap-up nudge for session %s", session_id
                        )

        # Only edit on 10-second boundaries and at zero.
        if seconds_remaining % EDIT_INTERVAL_SECONDS != 0 and seconds_remaining != 0:
            return

        # 429 backoff gate: skip edits until backoff_floor seconds have
        # elapsed since the last 429. seconds_remaining counts down ~1 per
        # real second (see run_countdown's drift correction), so the
        # difference doubles as elapsed real time without a separate clock
        # — keeps this deterministic under tests. The final tick (0) is not
        # special-cased, so it can still be skipped while inside the floor.
        if edit_state.last_429_seconds_remaining is not None:
            elapsed = edit_state.last_429_seconds_remaining - seconds_remaining
            if elapsed < edit_state.backoff_floor:
                logger.debug(
                    "Skipping edit for session %s at %ds — within 429 backoff floor",
                    session_id,
                    seconds_remaining,
                )
                return

        # Skip if a previous edit is still in flight. run_countdown awaits
        # on_tick inline (no concurrent ticks in production), so this never
        # actually trips today — kept as a defensive no-op for a future
        # caller that might invoke ticks concurrently.
        if edit_state.lock.locked():
            logger.debug(
                "Skipping edit for session %s at %ds — previous edit in flight",
                session_id,
                seconds_remaining,
            )
            return

        async with edit_state.lock:
            # duration_minutes is always set by this point — the session
            # reached ACTIVE via mark_active, which requires it.
            assert session.duration_minutes is not None
            content, embed = _build_timer_message(
                intention=session.intention,
                duration_minutes=session.duration_minutes,
                facilitator_id=session.handoff_facilitator_id or session.facilitator_id,
                started_at=edit_state.started_at,
                seconds_remaining=seconds_remaining,
                mention_line=edit_state.mention_line,
            )
            try:
                # AllowedMentions.none() is explicit belt-and-suspenders —
                # Discord does not re-ping on message edits regardless —
                # while the mention line itself stays in the edited content
                # so it remains visible for the rest of the session.
                await edit_state.message.edit(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                # Successful edit — decay backoff floor back to default and
                # clear the gate.
                edit_state.backoff_floor = BACKOFF_FLOOR_DEFAULT
                edit_state.last_429_seconds_remaining = None
            except discord.HTTPException as exc:
                if exc.status == 429:
                    # Rate limited — double the floor, respect the cap, and
                    # arm the gate from this point.
                    edit_state.backoff_floor = min(
                        edit_state.backoff_floor * 2, BACKOFF_FLOOR_CAP
                    )
                    edit_state.last_429_seconds_remaining = seconds_remaining
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
