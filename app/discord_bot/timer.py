"""Countdown tick handling: edit cadence and 429 backoff."""

from __future__ import annotations

import logging

import discord

from app.constants import (
    ACTIVE_TIMER_FMT,
    BACKOFF_FLOOR_CAP,
    BACKOFF_FLOOR_DEFAULT,
    EDIT_INTERVAL_SECONDS,
)
from app.discord_bot.views import _EditState, _format_intention_line
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class TimerMixin:
    """Countdown tick callback, mixed into :class:`TeaModeBot`."""

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation.
    _edit_states: dict[int, _EditState]
    _registry: SessionRegistry

    async def _on_countdown_tick(self, session_id: int, seconds_remaining: int) -> None:
        """Tick callback injected into ``run_countdown``.

        Fires every second.  Only attempts a Discord message edit on
        ticks that are multiples of *EDIT_INTERVAL_SECONDS* or on the
        final tick (``seconds_remaining == 0``).

        Skips the edit if the per-session lock is already held (a previous
        edit is still in flight).  Applies exponential backoff on HTTP 429.
        """
        # Only edit on 10-second boundaries and at zero.
        if seconds_remaining % EDIT_INTERVAL_SECONDS != 0 and seconds_remaining != 0:
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
            content = ACTIVE_TIMER_FMT.format(
                intention_line=_format_intention_line(session.intention),
                duration=session.duration_minutes,
                mm=mm,
                ss=ss,
            )
            try:
                await edit_state.message.edit(content=content)
                # Successful edit — decay backoff floor back to default.
                edit_state.backoff_floor = BACKOFF_FLOOR_DEFAULT
            except discord.HTTPException as exc:
                if exc.status == 429:
                    # Rate limited — double the floor, respect the cap.
                    edit_state.backoff_floor = min(
                        edit_state.backoff_floor * 2, BACKOFF_FLOOR_CAP
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
