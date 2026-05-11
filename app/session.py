"""Session state machine and in-memory registry for TeaMode."""

import asyncio
import enum
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import app.db as db


class SessionState(str, enum.Enum):
    """Session lifecycle states — values match the SQLite status enum exactly."""

    PENDING = "pending"
    INTENTION_SET = "intention_set"
    ACTIVE = "active"
    FOLLOWUP = "followup"
    COMPLETED = "completed"
    FOLLOWUP_TIMEOUT = "followup_timeout"
    CANCELLED = "cancelled"
    CRASHED = "crashed"


_TERMINAL: frozenset[SessionState] = frozenset(
    {
        SessionState.COMPLETED,
        SessionState.FOLLOWUP_TIMEOUT,
        SessionState.CANCELLED,
        SessionState.CRASHED,
    }
)


class InvalidTransition(Exception):
    """Raised when a state transition is called from an invalid prior state."""


@dataclass
class Session:
    """In-memory representation of a single TeaMode session.

    Mirrors the SQLite ``sessions`` row but tracks only the fields needed
    by the state machine and the Discord layer.
    """

    session_id: int
    guild_id: str
    text_channel_id: str
    voice_channel_id: str
    facilitator_id: str
    state: SessionState
    duration_minutes: int | None = field(default=None)
    intention: str | None = field(default=None)
    handoff_facilitator_id: str | None = field(default=None)


class SessionRegistry:
    """Orchestrates session lifecycle: in-memory state + SQLite writes.

    Construct with an open ``sqlite3.Connection`` (schema already applied
    by ``app.db.init_db``). The registry is the single authority for
    session state — all transitions go through it.

    Index design
    ------------
    ``_by_id``            — session_id → Session (primary index)
    ``_by_text_channel``  — text_channel_id → session_id (for O(1) lookup
                            of the active session in a text channel)

    The text-channel index only contains entries for non-terminal sessions.
    Terminal sessions are removed from the index on transition so a new
    session can be started in the same channel immediately.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._by_id: dict[int, Session] = {}
        self._by_text_channel: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get(self, session_id: int) -> Session | None:
        """Return the Session for *session_id*, or ``None`` if not found."""
        return self._by_id.get(session_id)

    def find_active_in_text_channel(self, text_channel_id: str) -> Session | None:
        """Return the non-terminal session in *text_channel_id*, or ``None``.

        Uses the text-channel index for O(1) lookup. Guards defensively
        against stale index entries by confirming the session is non-terminal
        before returning.
        """
        session_id = self._by_text_channel.get(text_channel_id)
        if session_id is None:
            return None
        session = self._by_id.get(session_id)
        if session is None or session.state in _TERMINAL:
            # Stale index entry — clean it up defensively.
            self._by_text_channel.pop(text_channel_id, None)
            return None
        return session

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, session_id: int) -> Session:
        session = self._by_id.get(session_id)
        if session is None:
            raise ValueError(f"No session with id={session_id}")
        return session

    def _require_state(
        self,
        session: Session,
        *valid_states: SessionState,
    ) -> None:
        if session.state not in valid_states:
            valid = ", ".join(s.value for s in valid_states)
            raise InvalidTransition(
                f"Transition requires state in ({valid}); "
                f"session {session.session_id} is in state {session.state.value!r}"
            )

    def _remove_from_channel_index(self, session: Session) -> None:
        stored_id = self._by_text_channel.get(session.text_channel_id)
        if stored_id == session.session_id:
            del self._by_text_channel[session.text_channel_id]

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def create_pending_session(
        self,
        *,
        guild_id: str,
        text_channel_id: str,
        voice_channel_id: str,
        facilitator_id: str,
    ) -> Session:
        """Create a new session in PENDING state for the given text channel.

        Raises ``InvalidTransition`` if a non-terminal session already exists
        in *text_channel_id* — one active session per channel is a hard
        invariant enforced here (the Discord layer checks too, but the
        registry is authoritative).
        """
        existing = self.find_active_in_text_channel(text_channel_id)
        if existing is not None:
            raise InvalidTransition(
                f"A non-terminal session (id={existing.session_id}) already "
                f"exists in text_channel_id={text_channel_id!r}"
            )

        row_id = db.insert_pending_session(
            self._conn,
            guild_id=guild_id,
            text_channel_id=text_channel_id,
            voice_channel_id=voice_channel_id,
            facilitator_id=facilitator_id,
        )
        session = Session(
            session_id=row_id,
            guild_id=guild_id,
            text_channel_id=text_channel_id,
            voice_channel_id=voice_channel_id,
            facilitator_id=facilitator_id,
            state=SessionState.PENDING,
        )
        self._by_id[row_id] = session
        self._by_text_channel[text_channel_id] = row_id
        return session

    def set_duration(self, *, session_id: int, duration_minutes: int) -> None:
        """Record the chosen timer length.

        Valid prior state: PENDING. State does not advance — duration capture
        happens within PENDING, alongside intention capture; the state
        advances to INTENTION_SET only after ``set_intention`` is called.
        """
        session = self._get_or_raise(session_id)
        self._require_state(session, SessionState.PENDING)
        db.update_duration(
            self._conn, session_id=session_id, duration_minutes=duration_minutes
        )
        session.duration_minutes = duration_minutes

    def set_intention(self, *, session_id: int, intention: str) -> Session:
        """Record the facilitator's intention and advance state to INTENTION_SET.

        Valid prior state: PENDING. Note: ``set_duration`` must be called
        before ``set_intention`` in the normal flow, but this transition
        only validates that the session is PENDING — it does not enforce that
        duration has been set. The Discord UI enforces the ordering by only
        showing the intention modal after a duration is chosen.
        """
        session = self._get_or_raise(session_id)
        self._require_state(session, SessionState.PENDING)
        db.update_intention_and_status(
            self._conn, session_id=session_id, intention=intention
        )
        session.intention = intention
        session.state = SessionState.INTENTION_SET
        return session

    def mark_active(self, *, session_id: int, started_at: str | None = None) -> None:
        """Start the timer — advance state to ACTIVE.

        Valid prior state: INTENTION_SET.
        """
        session = self._get_or_raise(session_id)
        self._require_state(session, SessionState.INTENTION_SET)
        db.update_started_at_active(
            self._conn, session_id=session_id, started_at=started_at
        )
        session.state = SessionState.ACTIVE

    def mark_followup(self, *, session_id: int) -> None:
        """Timer reached zero — advance state to FOLLOWUP.

        Valid prior state: ACTIVE.
        """
        session = self._get_or_raise(session_id)
        self._require_state(session, SessionState.ACTIVE)
        db.update_to_followup(self._conn, session_id=session_id)
        session.state = SessionState.FOLLOWUP

    def mark_completed(
        self,
        *,
        session_id: int,
        completed_intention: int,
        followup_note: str | None,
        ended_at: str | None = None,
    ) -> None:
        """Follow-up answered — advance state to COMPLETED (terminal).

        Valid prior state: FOLLOWUP. Removes the session from the
        text-channel index so a new session can start in the same channel.
        """
        session = self._get_or_raise(session_id)
        self._require_state(session, SessionState.FOLLOWUP)
        db.update_completed(
            self._conn,
            session_id=session_id,
            completed_intention=completed_intention,
            followup_note=followup_note,
            ended_at=ended_at,
        )
        session.state = SessionState.COMPLETED
        self._remove_from_channel_index(session)

    def mark_followup_timeout(
        self,
        *,
        session_id: int,
        ended_at: str | None = None,
    ) -> None:
        """Follow-up timed out — advance state to FOLLOWUP_TIMEOUT (terminal).

        Valid prior state: FOLLOWUP. Removes from the text-channel index.
        """
        session = self._get_or_raise(session_id)
        self._require_state(session, SessionState.FOLLOWUP)
        db.update_followup_timeout(self._conn, session_id=session_id, ended_at=ended_at)
        session.state = SessionState.FOLLOWUP_TIMEOUT
        self._remove_from_channel_index(session)

    def mark_handoff(
        self,
        *,
        session_id: int,
        handoff_facilitator_id: str,
    ) -> None:
        """Hand session control to a new facilitator.

        Valid prior states: INTENTION_SET, ACTIVE, FOLLOWUP. State does not
        advance. Updates both the handoff record and the authoritative
        ``facilitator_id`` so future authorization checks use the new
        facilitator.
        """
        session = self._get_or_raise(session_id)
        self._require_state(
            session,
            SessionState.INTENTION_SET,
            SessionState.ACTIVE,
            SessionState.FOLLOWUP,
        )
        db.update_handoff_facilitator(
            self._conn,
            session_id=session_id,
            handoff_facilitator_id=handoff_facilitator_id,
        )
        session.handoff_facilitator_id = handoff_facilitator_id
        session.facilitator_id = handoff_facilitator_id

    def mark_cancelled(
        self,
        *,
        session_id: int,
        ended_at: str | None = None,
    ) -> None:
        """Cancel a session at any non-terminal state (terminal: CANCELLED).

        Valid prior states: PENDING, INTENTION_SET, ACTIVE, FOLLOWUP.
        Removes from the text-channel index.
        """
        session = self._get_or_raise(session_id)
        non_terminal = (
            SessionState.PENDING,
            SessionState.INTENTION_SET,
            SessionState.ACTIVE,
            SessionState.FOLLOWUP,
        )
        self._require_state(session, *non_terminal)
        db.update_cancelled(self._conn, session_id=session_id, ended_at=ended_at)
        session.state = SessionState.CANCELLED
        self._remove_from_channel_index(session)


# ---------------------------------------------------------------------------
# Countdown coroutine — pure logic, no Discord imports
# ---------------------------------------------------------------------------


async def run_countdown(
    *,
    duration_minutes: int,
    on_tick: Callable[[int], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Drive a countdown from *duration_minutes* to zero, calling *on_tick* every second.

    The tick callback receives the number of seconds remaining (starting at
    ``duration_minutes * 60`` and counting down to ``0`` inclusive).

    Drift correction: each sleep target is computed from a fixed origin
    (``start``) rather than accumulated ``await sleep(1)`` calls.  Under load,
    individual ticks may fire slightly late, but the next sleep compensates so
    the total elapsed time stays close to ``duration_minutes * 60`` seconds.

    The coroutine is intentionally Discord-free.  Callers are responsible for
    advancing session state (``mark_followup``) after this coroutine returns.

    Parameters
    ----------
    duration_minutes:
        Session length to count down.
    on_tick:
        Async callback called with the remaining seconds at each 1-second tick.
        Called with ``seconds_remaining = total_seconds`` on the first tick
        and with ``0`` on the final tick.
    sleep:
        Injectable sleep function (default: ``asyncio.sleep``). Tests inject a
        fake that advances a virtual clock without real waiting.
    monotonic:
        Injectable monotonic clock (default: ``time.monotonic``). Tests inject
        a fake that is driven by the fake sleep.
    """
    total_seconds = duration_minutes * 60
    start = monotonic()

    for tick_number in range(total_seconds + 1):
        seconds_remaining = total_seconds - tick_number
        await on_tick(seconds_remaining)

        if seconds_remaining == 0:
            # Final tick delivered — done.
            break

        # Sleep until the next whole-second boundary relative to start.
        next_target = start + (tick_number + 1)
        elapsed = monotonic()
        delay = next_target - elapsed
        if delay > 0:
            await sleep(delay)
