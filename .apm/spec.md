---
title: TeaMode
modified: Spec creation by the Planner. Manager renamed package teamode/ → app/ before Stage 1 dispatch.
---

# APM Spec

## Overview

TeaMode is a self-hosted Discord bot that runs FLOWN/Groove-style guided
co-working sessions in voice channels. The bot user is named Ocha. A
single slash command `/teamode` walks the facilitator through duration
pick → intention capture → countdown → reverie chime → follow-up,
recording every session to a local SQLite database. MVP scope is
personal use on the facilitator's own server, hosted on demand from
their WSL laptop. Success: the facilitator runs real focus sessions
through TeaMode and accumulates a useful look-back log without
returning to the prior `simple-timer` Discord bot.

## Workspace

| Path | Role |
|---|---|
| `/home/jfang/WSL/github.com/jonathan-fang/teamode` | Working repository — greenfield; no source yet |
| `~/WSL/github.com/jonathan-fang/dlqa` | Read-only reference — focuswork countdown pattern; `reverie.wav` origin; conventions ancestor |
| `~/WSL/github.com/jonathan-fang/dawa` | Read-only reference — Python toolchain ancestor |

The repository already contains:
- `assets/reverie.wav` — end-of-session chime (in place).
- `AGENTS.md` and `CLAUDE.md` (one-line `@AGENTS.md` import). APM_RULES
  block is populated; the Manager appends version-control conventions
  during the Implementation Phase.
- `.project-meta/conventions.md` — full project conventions reference.
- `.project-meta/UI-ADR.md` — bot identity, palette, surface inventory,
  custom_id namespace, settled UI decisions.
- `.LLMAO/` — LLMAO workflow documents (USER-GUIDE, pre-plan-research,
  spike-sketch, ui-decisions-subsection, test-patterns,
  uat-verification, scan_injection.sh).
- `.project-meta/USEE/` — knowledge framework (1understand-criteria, 2form-strategy,
  3execute, 4evaluate).
- `docs/discord-platform-notes.md`, `docs/sqlite-schema.md`,
  `docs/language-library-comparison.md` — research docs that inform
  this Spec.

---

> **Notes:**
> - Greenfield repo: no source code yet. The Manager has latitude on
>   file/module layout within the conventions in
>   `.project-meta/conventions.md`. AGENTS.md suggests
>   `teamode.py` (entry) + `app/` package with `bot.py`,
>   `session.py`, `voice.py`, `db.py` — the Manager may reshape if
>   implementation reveals a better split.
> - Sibling repos `dlqa` and `dawa` are read-only references useful
>   for pattern lookup (focuswork countdown, conventions, anti-pattern
>   audit examples). Do not modify them.
> - `DISCORD_BOT_TOKEN` is supplied via env var; never commit. Tests
>   must not require a live token.
> - Approval gates apply before any file edit and any commit per
>   `.project-meta/conventions.md` § Version Control and AGENTS.md
>   APM_RULES.
> - `assets/reverie.wav` is the same file used by `dlqa`'s focuswork
>   routine. Do not symlink — the repo owns its own copy per the
>   shareability decision in `.project-meta/USEE/1understand-criteria.md`.
> - Discord guild registration is dev-time guild-scoped (instant
>   updates). The MVP does not need global command registration.
> - Cleanup/release stage applies per
>   `.project-meta/conventions.md` § Patch Release Structure — feature
>   freeze on the final stage.

## Stack and Toolchain

| Concern | Choice | Rationale source |
|---|---|---|
| Language | Python 3.11+ | `docs/language-library-comparison.md` § "Recommendation" |
| Discord library | `discord.py` with `[voice]` extras | Same |
| Async runtime | `asyncio` (stdlib) | discord.py default |
| Persistence | SQLite (`sqlite3` stdlib) | `docs/sqlite-schema.md` |
| Env loading | `python-dotenv` (dev convenience) | AGENTS.md § Dependencies |
| Test runner | `pytest` + `pytest-asyncio` | `.project-meta/conventions.md` § Testing |
| Type checker | `pyright` | Same |
| Formatter / linter | `ruff format` + `ruff check` | Same |

Dependency pinning rule: pin exact versions in `requirements.txt` per
`.project-meta/conventions.md` § Dependency Maintenance.

### System requirements (deployment, not design)

These are runtime prerequisites the host machine must provide. They
are not architectural decisions; they are what `discord.py[voice]`
needs to function.

- **`ffmpeg` on `PATH`** — discord.py uses `FFmpegPCMAudio` to play
  `assets/reverie.wav`. ffmpeg reads the WAV and produces a raw PCM
  stream. Without it, the first `voice_client.play(...)` call fails.
- **`libopus`** — Discord's voice protocol mandates the Opus codec.
  discord.py encodes the PCM stream from ffmpeg into Opus packets
  before sending to Discord. Usually bundled with
  `pip install "discord.py[voice]"` (along with PyNaCl for
  encryption); a system `libopus0` package may be required on some
  Linux distros.
- **Python 3.11+** — runtime version, see Stack table above.

These belong in the README's "Requirements" section as setup
instructions for self-hosters, not in the bot's source code.

## Bot Identity and Invocation

| Decision | Value |
|---|---|
| Discord application name (developer portal) | `TeaMode` |
| Bot user display name (chat-visible) | `Ocha` |
| Slash command | `/teamode` — single command, no subcommands, no command-time options |
| Command scope | Guild-scoped during dev (instant registration). Global registration deferred. |

Full identity and avatar/status guidance in
`.project-meta/UI-ADR.md` § "Bot identity."

### Invocation guard (cumulative — all must pass)

1. The invocation channel is a Discord voice channel's own text chat
   (not a regular text channel).
2. The invoker is currently a member of the voice channel that owns
   that text chat.
3. There is no other TeaMode session with `status = 'active'` in this
   text channel.

Failure responses are ephemeral (visible only to the invoker) using the
muted-grey embed accent from `.project-meta/UI-ADR.md`. Failure
messages:

| Failure | Message |
|---|---|
| Wrong channel type | "Run `/teamode` from a voice channel's text chat." |
| Not in voice | "Join the voice channel first, then try again." |
| Session already active here | "A TeaMode session is already running in this channel — please pick another text channel." |

## Session Lifecycle

The session is a state machine. One session per `/teamode` invocation.
Sessions in different text channels run as independent asyncio tasks
keyed by `session_id`.

### States

| State | Entry trigger | Exit trigger |
|---|---|---|
| `pending` | `/teamode` invocation passes guard; row written to SQLite | Facilitator picks duration |
| `intention_set` | Facilitator submits intention modal | Bot joins voice channel and starts timer |
| `active` | Voice connection established; timer started | Timer reaches zero |
| `followup` | Reverie plays; follow-up button row posted | Facilitator answers Y/N, OR 3-minute timeout, OR facilitator ends early |
| `completed` (terminal) | Follow-up answered | — |
| `followup_timeout` (terminal) | 3 min elapse with no facilitator answer | — |
| `cancelled` (terminal) | Solo facilitator left voice and did not return within 5 min | — |
| `crashed` (terminal) | Bot process died; reconciliation on next startup | — |

State transitions write to SQLite at every step; no in-memory-only
state survives a process restart.

### Sequence of bot actions

```
/teamode invocation
  └─ guard checks pass
       └─ INSERT row (status='pending')
            └─ post welcome embed + timer-pick button row
                 └─ facilitator clicks [10|25|50]
                      └─ open intention modal
                           └─ facilitator submits modal
                                └─ UPDATE row (intention, duration_minutes)
                                     └─ post participant intention prompt
                                        ("Everyone — share your intention in chat or voice")
                                          └─ bot joins voice channel
                                               └─ UPDATE row (started_at, status='active')
                                                    └─ post active timer message
                                                         └─ countdown loop (edit every 10s)
                                                              └─ at zero:
                                                                   ├─ post end-of-session embed (🍵🌿✨ flourish)
                                                                   ├─ post participant follow-up prompt
                                                                   │  ("Everyone — share how the session went")
                                                                   ├─ play assets/reverie.wav in voice
                                                                   ├─ @-mention facilitator
                                                                   └─ post follow-up button row
                                                                   └─ facilitator clicks [Y|N] OR timeout OR end-early
                                                                        ├─ if N: prompt for "why" text
                                                                        └─ UPDATE row (status, completed_intention, followup_note, ended_at)
                                                                             └─ bot leaves voice
```

### Message visibility

All session messages — welcome embed, active timer, end-of-session
embed, follow-up question — are **public to the voice channel's text
chat**, not ephemeral. Anyone with access to that text channel
(everyone in the voice channel, plus anyone with channel-view
permission in the server) sees them. Mid-session joiners — anyone who
joins the voice channel after the session is already running — gain
visibility automatically because they now have access to the voice
channel's text chat. They see all subsequent edits and the
end-of-session messages, and they can react to the follow-up if they
are in voice when it posts.

The intention text is also public: once the facilitator submits the
intention modal, the bot publishes the intention into the active
timer message. All participants and joiners see it. (Discord modals
are by design a single-user form — only the user who clicked the
button gets the modal — but the *result* is broadcast.)

The only ephemeral messages are **refusals**: wrong-channel,
not-in-voice, session-already-active, unauthorised click. These stay
private to the invoker so they don't pollute the channel.

Voice channel seat capacity is a Discord-platform concern (default 99
users, configurable per channel by server admins). The bot does not
enforce or surface this — when a channel is full, Discord rejects new
joiners with its own message before they reach the bot.

### Participant flow (other voice-channel members)

The session has two parallel flows: the **facilitator flow** (drives the
state machine — picks duration, submits intention, answers follow-up) and
the **participant flow** (everyone else in the voice channel — invited
to share, but not driving state).

**Participant prompts.** The bot posts two non-interactive text prompts
during the session:

| When | Prompt |
|---|---|
| Right after the facilitator submits their intention modal, before the timer starts | "Everyone — type your intention in chat or share it in voice. Take a minute." |
| Right after the end-of-session embed, before the facilitator's Y/N follow-up | "Everyone — share how the session went, in chat or voice." |

The prompts are **plain text messages** in the channel — not embeds,
not modals, no buttons. Anyone may respond by chatting in the channel
or speaking in voice.

**No capture.** The bot does not parse, log, or persist participant
chat messages or voice. Participation is social, not bookkept. The
SQLite schema is unchanged. (Capture-via-listener and capture-via-modal
are tracked in `TODO.md` as v2 ideas.)

**Reactions remain.** The 👍/👎 reactions on the follow-up button row
are unchanged — they coexist with the participant prompt. Reactions
are a passive social signal; the prompt is an active invitation.

**Mid-session joiners** see all subsequent prompts and may react to
the follow-up if they are in voice when it posts. They miss the
intention prompt because it's already past — that's fine; they can
still chat their intention if they want.

### Authorization

The matrix below is about **who can interact**, not who can see.
Everyone with access to the channel sees the buttons and reactions;
only the facilitator's clicks count for state transitions.

| Action | Who can interact | Effect of unauthorised click |
|---|---|---|
| Timer-pick buttons (`[10] [25] [50]`) | Facilitator only | Ephemeral: "Only the facilitator can answer." |
| Intention modal submission | Facilitator only (modal opens for them; non-facilitators can't click the timer-pick that triggers it) | N/A — modal never opens for non-facilitator |
| Follow-up Y/N buttons | Facilitator only | Ephemeral: "Only the facilitator can answer." |
| Follow-up "end early" button | Facilitator only | Ephemeral: "Only the facilitator can end the follow-up window." |
| Follow-up reactions (👍/👎) | Anyone in the voice channel | Recorded as social signal only; not authoritative for `completed_intention` |
| Facilitator handoff (after departure) | System (`random.choice` over remaining voice members) | N/A — bot-driven, not user-driven |

## UI Surface

Authoritative source: `.project-meta/UI-ADR.md`.

| Concern | Reference |
|---|---|
| Color palette (active / refusal / completed / crashed) | UI-ADR § "Color palette" |
| Emoji palette (🍵 + ⏳ pair, 🌿✨ flourish) | UI-ADR § "Emoji palette" |
| Surface inventory (welcome, timer, follow-up) | UI-ADR § "Surface inventory" |
| Custom_id namespace `teamode:<session_id>:<purpose>[:<value>]` | UI-ADR § "Custom_id namespace" |
| Mobile rendering constraints | UI-ADR § "Mobile rendering" |
| Settled decisions list | UI-ADR § "Decisions already made" |

### Visual fidelity tier (MVP)

- Active timer surface: **plain text edit** cycling
  `🍵 Intention: <…>  ⏳ <mm>:<ss>` every 10 seconds.
- End-of-session: an embed (steeping forest accent) with the 🍵🌿✨
  flourish, plus a follow-up button row.
- Welcome: a single tidy embed (matcha sage accent) with the timer-pick
  button row inline.

V2 polish (out of scope here): embed-with-progress-bar on the active
timer; ASCII teacup banner on welcome.

### Edit cadence rules (cross-Task constraint)

1. Edit interval: **10 seconds**.
2. Skip an edit if the previous edit is still in flight (no edit-queue
   build-up).
3. On `discord.HTTPException` with status 429 (rate limit): exponential
   backoff with floor of 10 seconds. Do not retry faster than the
   cycle.

## Persistence

Authoritative source: `docs/sqlite-schema.md` (field-by-field, with
Discord-API citations).

### Database location

- Path: `$TEAMODE_DB_PATH` env var, default `./sessions.db` relative
  to the bot's working directory.
- Schema migration: applied at first startup (table-creation SQL is
  idempotent via `CREATE TABLE IF NOT EXISTS`). No migration framework
  for V1.

### Write discipline (cross-Task constraint)

| Trigger | SQLite operation |
|---|---|
| Guard checks pass | `INSERT` row with `status='pending'` |
| Duration picked | `UPDATE duration_minutes` |
| Intention submitted | `UPDATE intention, status='intention_set'` (and again to `'active'` once voice connects) |
| Voice connected, timer starts | `UPDATE started_at, status='active'` |
| Timer reaches zero | `UPDATE status='followup'` |
| Follow-up Y/N answered | `UPDATE completed_intention, followup_note, ended_at, status='completed'` |
| Follow-up times out | `UPDATE ended_at, status='followup_timeout'` |
| Facilitator handoff | `UPDATE handoff_facilitator_id` |
| Solo-facilitator 5-min grace expires | `UPDATE ended_at, status='cancelled'` |
| Bot startup, reconciliation | `UPDATE ended_at, status='crashed'` for any rows still `active`, `pending`, `intention_set`, or `followup` |

## Voice

Authoritative source: `docs/discord-platform-notes.md` § "Voice Audio
Playback."

### Connection lifecycle

1. Bot joins the facilitator's voice channel **at session start** (after
   intention is captured), not at the end. Rationale: reverie reliability
   outweighs the cost of holding an idle voice connection.
2. Bot stays connected silently through the timer.
3. At zero, bot plays `assets/reverie.wav` via `FFmpegPCMAudio`.
4. After playback completes, bot disconnects from voice.
5. If the bot's voice connection drops mid-session, discord.py
   auto-reconnects. The session continues; do not crash.
6. If `voice_client.play(...)` raises at zero, fall back to a text
   `@-mention` of the facilitator (which produces a Discord
   notification). Log the failure to console.

### Asset path

- Constant: `REVERIE_PATH = Path(__file__).parent / ".." / "assets" / "reverie.wav"` (resolved once at import).
- Do not hardcode the path inline in voice playback calls.

## Edge Cases

| Case | Behavior |
|---|---|
| Facilitator leaves voice mid-session, ≥1 other in voice | `random.choice` selects a new facilitator from remaining voice members; bot announces "@OldFac left — @NewFac, you're now the facilitator"; `handoff_facilitator_id` recorded. Follow-up rights transfer. |
| Facilitator leaves voice mid-session, alone | 5-minute rejoin grace begins. If they rejoin the same voice channel, cancel the watchdog and continue. If 5 min elapses with the voice channel empty, terminate: edit message to "Session ended — facilitator did not return", play no reverie, `status='cancelled'`. |
| Bot websocket drops, process alive | discord.py auto-reconnects with backoff. asyncio task continues; `asyncio.sleep` is unaffected. Pending edits may fail and retry; worst case, `mm:ss` is briefly stale. No special handling beyond logging. |
| Bot process dies (laptop sleep, OOM, crash) | All in-memory state lost. On next startup, query for non-terminal `status` and `UPDATE status='crashed'` with `ended_at = now()`. Do not attempt resume. |
| Voice connect fails at session start | Surface ephemeral error to facilitator; `status='cancelled'`. Session does not proceed without voice (the session contract requires the bot in voice). |
| Voice playback fails at zero | Fall back to `@-mention` text. Continue with follow-up flow normally. |
| Discord API degraded (5xx on edits or interactions) | Catch `discord.HTTPException` at boundaries. Log. Surface ephemeral message only when user-facing. Don't crash on transient errors. |
| Modal text exceeds Discord's 4000-char cap | Discord rejects the submission client-side; user retries shorter. Bot does not need to validate length. |
| User invokes `/teamode` from a server-text channel that happens to be linked to a voice channel they are not in | Falls through to the "not in voice" failure of the cumulative guard. |

## Validation Approach

- **Automated**: `ruff format --check`, `ruff check`, `pytest`,
  `pyright`, `.LLMAO/scan_injection.sh .apm`. Per AGENTS.md §
  Validation Protocol.
- **Manual Discord smoke test**: required for any user-facing change.
  Smoke-test command shape per AGENTS.md § Smoke Test Delivery.
- **UAT walkthrough**: required at the end of any Stage delivering
  user-facing functionality, per `.LLMAO/uat-verification.md`.

Concrete success criteria from `.project-meta/USEE/1understand-criteria.md`:
- Facilitator can run a real focus session through the bot
  end-to-end.
- Session log persists every session correctly.
- Bot is stable enough that a 50-minute session does not require
  intervention.
- Voice playback succeeds in ≥ 9 of 10 sessions (graceful degradation
  to text mention is acceptable).

## Hosting

| Environment | Status | Source |
|---|---|---|
| WSL on facilitator's laptop | Supported (MVP) | `docs/language-library-comparison.md` § "Hosting options" |
| Linux VPS | Planned (V2, not in this project) | Same |
| Termux (Android) | Not supported | Voice playback path unverified |

The bot is started on demand (`python3 teamode.py`), not run as a
persistent service for V1. Process lifecycle is the facilitator's
responsibility.

## Out of Scope (V1)

These are explicitly deferred and must not be addressed by Tasks in
this project:

- Chained sessions ("go again? / 5-min break?") — defer to V2.
- Embed with progress bar timer surface — V2 polish.
- `/teamode-stats` command — facilitator queries SQLite directly.
- Cross-server analytics, web dashboard.
- AI-generated reflection prompts (also forbidden by
  `.project-meta/conventions.md` § Code Hygiene "Runtime output").
- Voice transcription, presence analysis.
- Participant snapshot at session start (would require additional
  Discord API calls; defer to V2).
