# Changelog

## Unreleased

### Added

- **Participant tracking.** Each session now records which humans were
  in the voice channel: a snapshot when the timer starts plus anyone
  who joins voice later while the session is active, stored in the new
  `session_participants` table (`joined_late` flags late joiners). Read
  from the member cache and voice-state events, so no extra Discord API
  calls.

### Changed

- **`/stats` "You" counts joined sessions.** It now includes sessions
  you joined as well as ones you facilitated; completion rate is still
  computed only from sessions you facilitated.

### Verified

- **Automatic RNG handoff verified live in Discord.** When the
  facilitator leaves with others remaining, the session is reassigned
  to a remaining member. This was one of the eight live paths listed
  as unverified in v26Q3.0.0.0; seven remain.
- **`/handoff` refusals for Ocha and self verified live in Discord.**
  Naming the bot as the target returns the ephemeral "Pick a human
  voice-channel member." refusal; the facilitator naming themselves
  returns "You are already the facilitator." In both cases the
  facilitator is unchanged. This covers two of the `/handoff` refusal
  branches; the others (no session, not facilitator, target not in
  voice) remain unverified live.

### Closed

- **Auto-removing the "Time's up!" message — closed, already handled.**
  The next `/teamode` in the channel deletes the previous session's
  "Time's up!" message, and `/clear` removes any leftovers by content
  (including after a bot restart, when the in-memory message ids are
  gone). No timed auto-delete needed.

## v26Q3.0.0.0 — 2026-09-30

Package refactor, reliability hardening, and the features that were
"Not in V1": chained sessions, the embed timer, `/teamode-stats`, and
`/teamode-clear`.

### Added

- **Chained sessions and breaks.** After a session ends, any voice
  member can click "Go again" or "Take a 5-minute break." Breaks join
  voice silently and end with the reverie chime plus a Go again button
  (disabled after 3 minutes). After two chained sessions of 25+
  minutes, the prompt offers a 10-minute break listing the streak's
  durations instead; any break resets the streak. `/teamode` during an
  active break cancels it.
- **Embed timer.** Replaces the plain-text `mm:ss` cycle with an embed
  (title, Intention/Facilitator/Range fields, a `Deep focus` → `Wrap
  up` phase shift at 3 minutes remaining with a sage-to-amber accent
  change, `MM:SS remaining`, and a unicode progress bar), falling back
  to a plain content line if an embed edit itself fails.
- **Wrap-up nudge.** A one-time message (plus a wind chime in voice)
  when 3 minutes remain, for sessions of 10+ minutes.
- **`/teamode-stats`** — ephemeral "You" / "This server" summary over
  the last 7 days, 30 days, and all time (sessions, focus minutes,
  completion rate), plus a personal day streak.
- **`/teamode-clear`** (requires the invoking member's Manage
  Messages) — deletes Ocha's own past TeaMode clutter from the last
  800 messages, paced to stay under Discord's per-channel delete rate
  limit. Keeps live timers, handoff notices, and anything belonging to
  a live session, chain prompt, or break.
- **Voice channel status**, shown only while Ocha is connected: timer
  countdown, "Done at HH:MM", solo-grace cancellation, and the two
  break phases.
- **ASCII teacup banner** on the welcome embed — a User-approved
  exception to the no-AI-generated-runtime-text rule.
- **PID single-instance lock** (`/tmp/teamode.pid`) — a second bot
  instance against the same token now exits cleanly at startup instead
  of both instances racing every interaction.
- **`ffmpeg` startup probe** — logs a non-fatal WARNING if `ffmpeg`
  isn't on `PATH`, instead of silently skipping reverie playback.
- **`TEAMODE_TIMEZONE`** (IANA name, default `America/Los_Angeles`) —
  drives the timer embed's wall-clock range, voice channel status
  times, and the local-midnight reset for the guild daily cap and
  stats streak. An invalid name logs a WARNING and falls back to the
  default; UTC if even that's unavailable.
- **Per-user (3 per 5 minutes) and per-guild (50/day) rate limits** on
  `/teamode`, resetting at local midnight, in-memory.
- **Pending-session expiry.** A welcome message with no duration pick
  within 10 minutes is edited to `🍵 Expired` with its buttons
  disabled, and duration re-picks are guarded against a double submit.
- **`scripts/teamode_launcher.sh`** — sources `~/.teamode-secrets`,
  activates the venv, supports `dev`/`stable` modes. Paired with
  `docs/windows-shortcut.md` for a Windows Terminal desktop shortcut.
- **`scripts/generate_art.py`** (dev-only, `requirements-dev.txt`) —
  deterministically generates icon/banner/avatar candidates for manual
  review and upload in the Discord Developer Portal.
- **Application art** — `assets/app-icon.png` (1024×1024),
  `assets/app-banner.png` (680×240), `assets/app-avatar.png`
  (1024×1024): a flat teacup with steam on an amber saucer.

### Changed

- **`app/bot.py` refactored into `app/discord_bot/`** — a package of
  mixins (`CommandsMixin`, `ViewsMixin`, `TimerMixin`,
  `LifecycleMixin`, `BreakMixin`, `ClearMixin`, `StatsMixin`) composed
  onto one bot class, with Discord-free logic (rate limiting, timer
  formatting, stats aggregation, message classification) split into
  flat, independently testable modules under `app/`.
- **All copy and tunables consolidated into `app/constants.py`** — no
  Discord-facing string or tunable number is inlined elsewhere.
- **Type hints and lint gates tightened**: every function in `app/`
  and `teamode.py` is now annotated on parameters and return type
  (Ruff `ANN`, enforced in `pyproject.toml`); `cast()` and
  `# type: ignore` are banned outside a documented upstream-stub-bug
  escape hatch; `pyright` runs bare with configuration in
  `pyproject.toml`.
- **Message lifecycle cleanup.** The welcome, `[Set Intention]`, and
  wrap-up nudge messages are now deleted at terminal states (not on
  pending expiry, where the welcome is left edited to `🍵 Expired`
  instead). At the next session's start, the previous "Time's up"
  content and the `⛔` follow-up reaction are deleted and the Reflect
  embed is stripped back to its base content.
- **Timer edit backoff** on `discord.HTTPException` (429) now actually
  gates the next edit attempt (floor 10s, cap 60s), instead of only
  informing a retry.
- **Every background `asyncio.create_task`** now logs unexpected
  exceptions via `logger.exception`, so a failing background task
  (watchdog, solo grace, pending expiry, break, Go-again timeout)
  surfaces instead of failing silently.
- **Stale-button refusal unified** to a single "This session is no
  longer active." message across every stale/finished-session
  component click.

### Known issues

- **`PYSEC-2026-1448`** and **`PYSEC-2026-3002`** — PyNaCl 1.5.0 is
  pinned because `discord.py 2.7.1` requires `PyNaCl<1.6`, and the
  fixed PyNaCl releases don't satisfy that constraint. Resolves when
  discord.py 2.8 ships and the pin can move. Ignore both when auditing
  in the meantime:
  ```bash
  pip-audit --ignore-vuln PYSEC-2026-1448 --ignore-vuln PYSEC-2026-3002
  ```
- **In-memory state resets on restart.** Rate limits, break state,
  chaining streaks, and `/teamode-clear`'s known-message-id cache all
  live in process memory — a bot restart clears them (sessions
  themselves are durable in SQLite; this affects only these
  in-process counters and caches).
- **Checks postponed pending a second user/server** (see `TODO.md` §
  Notes and `docs/external-interest-log.md`): intention-text privacy,
  data anonymization, and the shareable-to-one-external-server
  walkthrough.
- **Eight live paths remain unverified against a real Discord
  gateway** (manual-smoke-test-only, not unit-testable):
  non-facilitator reaction, the 3-minute Reflect timeout, the
  `/handoff` manual happy path, `/handoff` refusal branches, automatic
  RNG handoff, solo-grace rejoin cancel, the solo-grace 5-minute
  timeout, and wifi-drop reconnect.

## v26Q2.0.0 — 2026-05-11

The first shippable release of TeaMode. A facilitator can run a real
focus session through Ocha end-to-end and accumulate a local
session log.

### Features

- **`/teamode` slash command.** Single entry point. Invocation guard
  (must be a voice channel's text chat, invoker must be in voice, no
  concurrent session in this channel).
- **Welcome → timer pick → intention modal → voice connect → countdown
  → reverie → Reflect.** Full guided flow with calm aesthetic.
- **Durations: 5 / 10 / 25 / 50 minutes.**
- **Empty intention accepted.** Active timer collapses to
  `🍵 No intention set`.
- **Participant `[Set Intention]` prompt** 1 second after welcome,
  @-mentioning current voice members.
- **End-of-session reverie chime** played in voice via `ffmpeg`.
- **Reflect embed with facilitator-authoritative ✅/⛔ reactions** for
  completed-intention bookkeeping.
- **3-minute follow-up watchdog** marks `followup_timeout` if no
  facilitator reaction.
- **Facilitator handoff.** Automatic (`random.choice`) when the
  facilitator leaves with others remaining; manual via `/handoff @user`
  for explicit transfer.
- **5-minute solo grace.** Facilitator leaves alone → rejoin grace;
  timeout cancels with `Session ended — facilitator did not return.`
- **Crash reconciliation** marks non-terminal rows `crashed` on next
  startup.
- **SQLite session log** at `$TEAMODE_DB_PATH` (default `./sessions.db`).

### Known issues

- **PyNaCl CVE-2025-69277** is unresolved at V1. The fix requires
  PyNaCl >= 1.6.2, but `discord.py[voice]==2.7.1` (the latest release
  on PyPI as of 2026-05-11) pins `PyNaCl<1.6`. The CVE affects atypical
  custom-cryptography paths and is low-risk for TeaMode's standard
  voice-channel usage. Revisit when discord.py releases a version that
  allows PyNaCl 1.6.x; bump `discord.py[voice]` and re-run `pip-audit`
  to confirm clear.

### Not in V1

- Chained sessions, embed-with-progress-bar timer, `/teamode-stats`,
  cross-server analytics, AI-generated reflection prompts, voice
  transcription.
