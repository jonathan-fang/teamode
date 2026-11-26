"""In-memory runtime state for live sessions and text channels.

Everything the bot keeps about a session while it runs (its setup messages,
timer edit state, voice client, background tasks, ...) lives on one
:class:`SessionRuntime`, and everything it keeps per text channel (the last
session's leftover messages, the chain prompt, a break, the streak) on one
:class:`ChannelRuntime`. Both live in a :class:`RuntimeStore` on the bot.

A session's runtime is dropped in one ``pop`` when the session reaches a
terminal state (``LifecycleMixin._on_session_terminal``), so no per-session
entry can be left behind. Channel runtimes are never dropped; they hold at
most a few ids per channel. All of this is in-memory only and lost on
restart.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.discord_bot.views import _ChannelCleanup

if TYPE_CHECKING:
    import discord

    from app.discord_bot.breaks import _BreakState, _ChainState
    from app.discord_bot.views import _EditState, _SetupMessages


@dataclass
class SessionRuntime:
    """In-memory state for one live (non-terminal) session."""

    # Welcome / Set-Intention / nudge message ids, captured at session start
    # for later edit or delete through the channel (never the webhook).
    setup: _SetupMessages | None = None
    # The active timer message; set on activation, taken by end-of-session.
    edit_state: _EditState | None = None
    # Set after voice.connect succeeds; None for Groove sessions.
    voice_client: discord.VoiceClient | None = None
    # The Reflect message the facilitator reacts ✅/⛔ on.
    reflect_message_id: int | None = None
    # Started via Go again (True) or /teamode / /groove (False); decides
    # whether the channel's streak is extended or restarted.
    chained_via_go_again: bool = False
    # Background tasks: cancelled when the session ends.
    pending_expiry_task: asyncio.Task[None] | None = None
    countdown_task: asyncio.Task[None] | None = None
    watchdog_task: asyncio.Task[None] | None = None
    solo_grace_task: asyncio.Task[None] | None = None

    def cancel_tasks(self, *, keep: asyncio.Task[object] | None = None) -> None:
        """Cancel every unfinished background task except *keep*.

        *keep* is the task doing the cancelling, when a session's own task
        ends it (a task must not cancel itself partway through).
        """
        for task in (
            self.pending_expiry_task,
            self.watchdog_task,
            self.solo_grace_task,
            self.countdown_task,
        ):
            if task is not None and task is not keep and not task.done():
                task.cancel()


@dataclass
class ChannelRuntime:
    """In-memory state for one text channel, across sessions."""

    # The previous session's Time's up / Reflect / why / ping message ids,
    # cleaned up when the next session starts here.
    cleanup: _ChannelCleanup = field(default_factory=_ChannelCleanup)
    # The standing Go again / break offer prompt, if any.
    chain: _ChainState | None = None
    # The break in progress, if any.
    break_state: _BreakState | None = None
    # Durations of the chained, qualifying sessions so far (see breaks.py).
    streak: list[int] = field(default_factory=list[int])


class RuntimeStore:
    """The bot's session and channel runtimes, keyed by id."""

    def __init__(self) -> None:
        self.sessions: dict[int, SessionRuntime] = {}
        self.channels: dict[int, ChannelRuntime] = {}

    def session(self, session_id: int) -> SessionRuntime:
        """Return *session_id*'s runtime, creating it if needed.

        Only for writes made while the session is live; reads use
        :meth:`peek_session` so they never recreate a dropped runtime.
        """
        return self.sessions.setdefault(session_id, SessionRuntime())

    def peek_session(self, session_id: int) -> SessionRuntime | None:
        """Return *session_id*'s runtime, or ``None`` if it has none."""
        return self.sessions.get(session_id)

    def pop_session(self, session_id: int) -> SessionRuntime | None:
        """Remove and return *session_id*'s runtime, if any."""
        return self.sessions.pop(session_id, None)

    def session_for_reflect(self, message_id: int) -> int | None:
        """Return the session whose Reflect message is *message_id*, if any."""
        for session_id, runtime in self.sessions.items():
            if runtime.reflect_message_id == message_id:
                return session_id
        return None

    def channel(self, channel_id: int) -> ChannelRuntime:
        """Return *channel_id*'s runtime, creating it if needed."""
        return self.channels.setdefault(channel_id, ChannelRuntime())

    def peek_channel(self, channel_id: int) -> ChannelRuntime | None:
        """Return *channel_id*'s runtime, or ``None`` if it has none."""
        return self.channels.get(channel_id)
