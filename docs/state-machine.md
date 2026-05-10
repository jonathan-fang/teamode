# Session State Machine — Why

A TeaMode session moves through a fixed sequence of phases:

```
pending → intention_set → active → followup → terminal
```

Each phase only allows a small set of next moves. The state machine
(`app/session.py`) encodes that as data + rules in one place, so the
rest of the code doesn't have to think about "is this allowed right
now?"

## What it does for us

1. **Reject illegal moves cheaply.** If the facilitator double-clicks
   the timer-pick button mid-session, or a stale Discord interaction
   fires after the timer ended, the registry raises
   `InvalidTransition` instead of corrupting the row. No defensive
   `if status == 'active'` checks scattered through `bot.py`.

2. **Keep memory and disk in lockstep.** Every transition writes both
   the in-memory `Session` and the SQLite row in one method. The
   Discord layer never touches `db.py` directly, so there's no path
   where the two diverge.

3. **Enforce the "one session per text channel" invariant.**
   `create_pending_session` checks the reverse index and refuses if a
   non-terminal session exists there. This is the *real* guard — the
   slash-command guard in `bot.py` is just a polite UX wrapper around
   it.

4. **Define what "is there an active session?" means.** Without an
   explicit state set, every caller would have its own definition
   (does `pending` count? `followup`?). With the `SessionState` enum
   and the `_TERMINAL` set, the answer lives in one place.

## What it would cost without one

The Discord layer would sprawl: every button handler hand-rolling
status checks, every error path forgetting to update SQLite, the
channel-exclusivity rule duplicated in three places. The state
machine collapses that complexity into one module that's testable
without Discord at all (which is why `tests/test_session.py` runs in
40 ms against `:memory:`).

## States and transitions

See `app/session.py` for the canonical surface. States and their
SQLite `status` values:

| Enum | SQLite value | Terminal? |
|---|---|---|
| `PENDING` | `pending` | no |
| `INTENTION_SET` | `intention_set` | no |
| `ACTIVE` | `active` | no |
| `FOLLOWUP` | `followup` | no |
| `COMPLETED` | `completed` | yes |
| `FOLLOWUP_TIMEOUT` | `followup_timeout` | yes |
| `CANCELLED` | `cancelled` | yes |
| `CRASHED` | `crashed` | yes |

Every transition function on `SessionRegistry` validates the prior
state and raises `InvalidTransition` if the call is illegal. Terminal
transitions also remove the session from the text-channel index so a
new session can be started in the same channel.

For the field-level shape of the SQLite row, see
`docs/sqlite-schema.md`. For the user-facing flow that drives these
transitions, see the Spec's "Session Lifecycle" section.
