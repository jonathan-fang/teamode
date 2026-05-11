# Changelog

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
