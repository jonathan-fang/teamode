---
title: TeaMode v26Q3.0.0.0
modified: Spec creation by the Planner.
---

# APM Spec

## Overview

TeaMode is a self-hosted Discord bot (bot user "Ocha", discord.py + asyncio + SQLite) that runs guided co-working sessions in voice channels via `/teamode`. This release, tagged `v26Q3.0.0.0` (quarter rollover), delivers every "Next Patch" and "Next Minor" item in `TODO.md`, fixes three pre-existing defects (pending-session lockout, unused 429 backoff, swallowed post-countdown errors), restructures `app/bot.py` into a package, and tightens typing and tooling. The driver is the developer's own daily use with accurate documentation; external-server items stay postponed per `docs/external-interest-log.md`. Success is: all features behave as specified below, the five-check validation pipeline passes clean, Discord smoke tests pass, and docs match behavior. Priority if time runs short: art assets, ASCII banner and `/teamode-stats` slip first; chained sessions and breaks second; core session behavior must ship.

## Workspace

- **Working repository:** `/home/jfang/WSL/github.com/jonathan-fang/teamode` (single git repo, branch `main`, remote `origin/main`). Python 3.12 venv at `.venv`.
- **Package:** `app/` (note: the repo root directory is also named `teamode/`; always refer to the package as `app/`). Entry point `teamode.py`.
- **Read-only reference:** `/home/jfang/WSL/github.com/jonathan-fang/dlqa/app/ui/widgets.py:173` (`FocusTimerWidget`, Textual) — layout model for the embed timer.
- **Authoritative documents:**
  - `TODO.md` §"Next Patch" and §"Next Minor" — feature source text.
  - `.project-meta/conventions.md` — coding, testing, versioning standards (amended by this release, see Tooling and Typing).
  - `.project-meta/UI-ADR.md` — Discord surface authority: palette, embed formatting (`### ` prefix rule), custom_id namespace `teamode:<session_id>:<purpose>[:<value>]`, authorization rules.
  - `docs/sqlite-schema.md` — schema reference.
  - `docs/discordpy-api/gotchas.md`, `docs/discord-bot-setup.md` — discord.py pitfalls and permissions.
  - `.LLMAO/test-patterns.md` — discord.py / asyncio test patterns.
  - `docs/external-interest-log.md` — postponed items (out of scope).
- **Background only (partly stale):** `docs/groove-boogaloo-deployment.md`.
- **Prior APM session archive:** `.apm/archives/session-2026-05-11-001-MVP/` (V1 MVP, tag `v26Q2.0.0`).
- **Existing `CLAUDE.md`:** contains only `@AGENTS.md`. `AGENTS.md` holds repository guidelines, a "Working Preferences" section, and an existing `APM_RULES { … }` block from the MVP session.

---

> **Notes:**
> - Working tree at planning time has uncommitted edits to `README.md`, `TODO.md`, `changelog.md`, plus untracked `docs/external-interest-log.md`, `.apm/*`, `.claude/`. These are the User's in-progress edits and should be preserved, not reverted.
> - Existing version-control pattern (MVP): one `type/short-desc` branch per unit of work off `main`, merged `--no-ff`, branch deleted; Conventional Commits with 50/72 rule; no attribution trailers of any kind (no `Co-Authored-By`). Pushes and tags require User approval.
> - `scripts/teamode_launcher.sh` runs `dev` and `stable` modes from different worktrees — the source of the dual-instance bug.
> - Baseline at planning time: 122 tests pass; `ruff check` clean; `pyright` clean only when pointed at the venv (bare `pyright` shows 6 false import errors because there is no config).
> - User approval gates for this project: generated art review, each Discord smoke test, and every commit/merge/tag/push. Per-edit approval is relaxed for this session's agents (User decision).
> - User preferences: terse approvals ("y", "1y 2y"); sequential agent dispatch worked better than parallel worktrees in the MVP (~75k extra tokens in parallel); the User adds TODO entries liberally.
> - Target is to finish within one day — aggressive for this scope.
> - Eight MVP live paths remain unverified in Discord (1 non-facilitator reaction logged-only, 2 3-min Reflect timeout, 3 `/handoff` manual happy path, 4 `/handoff` refusal branches, 5 auto RNG handoff, 6 solo-grace rejoin cancel, 7 solo-grace 5-min timeout, 8 wifi-drop reconnect tolerance) per `.apm/archives/session-2026-05-11-001-MVP/session-summary.md`.

## Architecture

`app/bot.py` (1038 lines) becomes the package `app/discord_bot/`. Discord-free logic lives in flat modules under `app/`.

| Module | Responsibility |
|---|---|
| `app/discord_bot/__init__.py` | Re-exports `TeaModeBot` so `teamode.py`'s import changes only from `app.bot` to `app.discord_bot`. |
| `app/discord_bot/client.py` | `TeaModeBot` class, intents, `on_ready` (command sync), `on_interaction` custom_id router, per-session state dicts. |
| `app/discord_bot/commands.py` | `/teamode`, `/handoff`, `/teamode-stats`, `/teamode-clear` handlers, including the shared session-start function. |
| `app/discord_bot/views.py` | `IntentionModal`, duration buttons, Go again / Break buttons, embed builders. |
| `app/discord_bot/timer.py` | Countdown tick handling, edit cadence, 429 backoff, wrap-up nudge trigger. |
| `app/discord_bot/lifecycle.py` | End-of-session sequence, follow-up / watchdog, solo grace, pending expiry, break lifecycle, message cleanup hooks, voice status updates. |
| `app/constants.py` | All tunables and all Discord-facing copy (see Constants and Copy). No imports from `app.config` or `discord`. |
| `app/rate_limit.py` | Per-user sliding window and per-guild daily cap (pure, clock-injectable). |
| `app/timer_format.py` | Pure formatting: `MM:SS`, progress bar, phase selection, HH:MM in timezone. |
| `app/stats.py` | Stats aggregation over rows returned by `db.py` read helpers (pure). |
| `app/cleanup.py` | Pure predicates classifying a bot message as welcome / Set Intention / Time's up / Reflect / nudge / break (for `/teamode-clear`). |
| `app/session.py`, `app/voice.py`, `app/db.py`, `app/config.py` | Unchanged responsibilities; extended as features require (`db.py` gains read helpers; `config.py` gains `TEAMODE_TIMEZONE`). |

The split preserves all existing runtime behavior. The module list may be adjusted if a cleaner seam appears during the split, but `app/discord_bot/` naming, the `TeaModeBot` re-export, and "pure logic outside `discord_bot/`" are fixed. Test patch targets move from `app.bot.X` to the module where each name is used. The deferred "rename `bot.py`" item in `TODO.md` §Future is resolved by this and should be removed from `TODO.md`.

## Constants and Copy

`app/constants.py` is the single place the User edits numbers and wording. It holds:

- **Every tunable number** (table below).
- **Every string Ocha sends to Discord** — new and existing (refusals, Set Intention prompt, Time's up, Reflect, embed titles/bodies, slash-command descriptions, voice status strings, button labels) — as named constants, using `str.format` placeholders where values vary.
- **Palette hex strings** (`#7B9D6F` matcha sage, `#3F5E4A` steeping forest, `#8A8A8A` muted grey, `#A05A5A` muted red, `#C97B53` oolong amber); `discord.Color` objects are built from them inside `app/discord_bot/`.

| Constant | Value | Notes |
|---|---|---|
| `DURATIONS_MINUTES` | `(5, 10, 25, 50)` | Duration buttons; `_handle_timer_pick` must reject values not in this tuple. |
| `RATE_LIMIT_WINDOW_SECONDS` | `300` | Per-user sliding window. |
| `RATE_LIMIT_ALLOWANCE` | `3` | Invocations allowed per window; the 4th is refused. |
| `GUILD_DAILY_CAP` | `50` | Per-guild invocations per day. |
| `WRAP_UP_MINUTES` | `3` | Embed Wrap up phase + nudge trigger. |
| `NUDGE_MIN_DURATION_MINUTES` | `20` | Nudge only for sessions ≥ this. |
| `PENDING_TIMEOUT_SECONDS` | `600` | Unstarted-session expiry. |
| `BREAK_MINUTES` | `5` | Break length. |
| `GO_AGAIN_TIMEOUT_SECONDS` | `180` | Post-break Go again button lifetime. |
| `CLEAR_SCAN_LIMIT` | `200` | `/teamode-clear` history depth. |
| `FOLLOWUP_TIMEOUT_SECONDS` | `180` | Moved from `bot.py`. |
| `SOLO_GRACE_SECONDS` | `300` | Moved from `bot.py`. |
| `EDIT_INTERVAL_SECONDS` | `10` | Timer edit cadence. |
| `BACKOFF_FLOOR_DEFAULT` / `BACKOFF_FLOOR_CAP` | `10.0` / `60.0` | 429 backoff. |
| `WELCOME_PROMPT_DELAY_SECONDS` | `1.0` | Delay before Set Intention prompt (currently inline sleep). |
| `INTENTION_MAX_LENGTH` | `4000` | Modal field limit. |
| `PROGRESS_BAR_WIDTH` | `10` | Characters in the progress bar. |
| `STATS_WINDOWS_DAYS` | `(7, 30)` | Plus all-time. |
| `PID_FILE_PATH` | `/tmp/teamode.pid` | Absolute, repo-independent (dev and stable worktrees must collide). |
| `DEFAULT_TIMEZONE` | `America/Los_Angeles` | Fallback when `TEAMODE_TIMEZONE` unset. |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | required | Unchanged. Never logged except redacted to last four. |
| `TEAMODE_DB_PATH` | `./sessions.db` | Unchanged. |
| `TEAMODE_DEV_GUILD_ID` | unset | Unchanged behavior (comma-separated guild IDs; if unset, command registration is skipped with a warning). Must be documented in README. |
| `TEAMODE_TIMEZONE` | `DEFAULT_TIMEZONE` | New. IANA name, parsed with stdlib `zoneinfo`. Used for voice status HH:MM, embed "Started at", daily cap midnight reset, and streak day boundaries. Invalid value → log WARNING and fall back to default. |

Add `TEAMODE_TIMEZONE` to `.env.example` (stub value only).

## Session Flow Changes

- **Shared session start.** The body of the current `/teamode` handler is extracted into one shared function taking an `Interaction`. Both the `/teamode` command and the Go again button call it. All guards (voice-channel text chat, invoker in voice, no active session in channel) plus rate limiting run inside it, so Go again behaves exactly like typing `/teamode`, including counting toward both limits. Whoever triggers it becomes facilitator.
- **Rate limiting** (`TODO.md` §Next Patch "Per-user rate limiting (Option C)"): checked at the top of the shared start function, before session creation. Per-user sliding window (`RATE_LIMIT_ALLOWANCE` per `RATE_LIMIT_WINDOW_SECONDS`), refusal shows seconds remaining. Per-guild daily cap `GUILD_DAILY_CAP`, resets at midnight in `TEAMODE_TIMEZONE`. In-memory; resets on restart (accepted). Refusals are ephemeral refusal embeds.
- **Pending-session expiry.** A session still `pending` after `PENDING_TIMEOUT_SECONDS` (duration never picked, or modal dismissed) is marked `cancelled`; the welcome message is edited to show the expired line with its buttons disabled; the voice status becomes the expired status. The expiry timer is cancelled when the session advances past `pending`.
  - Expiry is the one terminal path that does not auto-delete the welcome and Set Intention messages: the edited welcome remains as the visible record, and both are removable via `/teamode-clear`.
- **Duration validation.** A timer-pick custom_id whose minutes value is not in `DURATIONS_MINUTES` is refused (stale-button refusal).
- **Wrap-up nudge** (`TODO.md` §Next Patch "Wrap-up nudge"): for sessions with `duration_minutes ≥ NUDGE_MIN_DURATION_MINUTES`, post one channel message when `WRAP_UP_MINUTES` minutes remain. Never fires if the session is no longer `active` (re-check state at fire time). Guard durations shorter than the trigger.
- **Mentions in the timer message:** the initial timer send includes the same @-mention set as the Set Intention prompt (non-bot voice members, excluding the bot), snapshotted at modal submit. Edits do not re-ping.
- **Handoff interaction:** embed Facilitator field reflects the current (in-memory) facilitator on the next edit. Voice status, nudge and wrap-up phase are unaffected. The DB keeps the original `facilitator_id`; `mark_handoff` writes only `handoff_facilitator_id` in SQLite.

## Timer Presentation

A single timer message per session, sent via `channel.send` and edited in place every `EDIT_INTERVAL_SECONDS`. It carries both an embed and a plain-text content line (fallback for users with embeds disabled).

Embed layout (modeled on `FocusTimerWidget`: title → fields → phase label → countdown → progress bar):

| Element | Content |
|---|---|
| Title | `TIMER_EMBED_TITLE` (see Copy) |
| Fields | Intention, Facilitator, Started at (HH:MM in `TEAMODE_TIMEZONE`) |
| Phase | Deep focus until the last `WRAP_UP_MINUTES` minutes, then Wrap up (all durations) |
| Countdown | `{MM:SS} remaining` |
| Progress | Unicode bar of `PROGRESS_BAR_WIDTH` chars + percentage, e.g. `█████░░░░░ 50%` |
| Accent | Matcha sage `#7B9D6F`; oolong amber `#C97B53` during Wrap up |

Content line: `⏳ {MM:SS}` with the @-mentions on the following line (mentions present on the initial send; edits keep the same content text).

Existing plain-text `_ACTIVE_TIMER_FMT` path is replaced by this message (the plain countdown survives as the content line). UI-ADR's "Embed + unicode progress bar is v2 polish — do not preempt" is superseded and must be updated.

Solo-grace cancellation keeps its existing text (`Session ended — facilitator did not return.`), shown as the timer message's final state.

## Timer Robustness

- The 429 backoff floor must actually delay subsequent edits (today it is computed but ignored). Edits skip until the floor elapses; floor doubles on 429 up to cap and resets after a successful edit.
- Every background task (countdown/end-of-session, watchdogs, solo grace, pending expiry, break, Go again timeout) catches and logs unexpected exceptions with `logger.exception` so failures are never silently dropped; a failure after the countdown must not leave a session stuck without logging.

## Chained Sessions and Breaks

- After the facilitator answers ✅ or ⛔ on Reflect, Ocha posts the chaining prompt with two buttons: Go again and Take a 5-minute break. Not offered after follow-up timeout. Any voice-channel member may click.
- **Go again** → calls the shared session start (see Session Flow Changes). Counts toward rate limits.
- **Break** → in-memory only, not a DB row. Posts the break-started message; sets voice status to the break status. `/teamode` (or Go again) in that channel during a break cancels the break and edits the break message to the break-cancelled line. When `BREAK_MINUTES` elapse: bot joins voice, plays reverie, disconnects, posts the break-over message with a Go again button. If nobody clicks within `GO_AGAIN_TIMEOUT_SECONDS`, the button is disabled (no new text).
- custom_ids follow the UI-ADR namespace (e.g. `teamode:<session_id>:again`, `teamode:<session_id>:break`).
- Go again after a break reconnects to voice through the normal flow; voice reconnection is a known fragile area from the MVP.

## Messages and Cleanup

- **Send/delete rule:** any message that will later be edited or deleted is sent with `channel.send` (or its ID captured via `interaction.original_response()` / `followup.send(wait=True)`) and later edited/deleted through the channel (`channel.get_partial_message(id)`), never through the interaction webhook (tokens expire after 15 minutes). The bot can delete its own messages without Manage Messages.
- **Automatic cleanup at terminal states:** when a session reaches `completed`, `followup_timeout`, or `cancelled` via solo grace or voice-connect failure, delete its welcome message and Set Intention prompt. Timer, Time's up and Reflect messages remain. Pending expiry is the exception: it edits the welcome instead (see Session Flow Changes).
- **Previous Time's up deletion:** the last Time's up message ID per text channel is kept in memory; when a new session starts in that channel, that message is deleted. Lost on restart (accepted).
- **Deletion failures** (`NotFound`, `Forbidden`, `HTTPException`) are logged at WARNING and never break the session flow.

## Commands

### `/teamode-stats`

Ephemeral embed with two sections, "You" and "This server", each with rows Last 7 days / Last 30 days / All time showing sessions, focus minutes, and completion rate, plus a personal streak.

| Metric | Definition |
|---|---|
| Sessions | Rows whose session reached follow-up (status `completed` or `followup_timeout`). |
| Focus minutes | Sum of `duration_minutes` over those rows. |
| Completion rate | ✅ answers ÷ (✅ + ⛔ answers), i.e. `completed_intention = 1` over rows where `completed_intention` is not NULL. Timeouts and cancellations excluded. Show `—` when the denominator is 0. |
| Streak | Consecutive days (in `TEAMODE_TIMEZONE`, ending today or yesterday) with ≥1 session reaching follow-up. Personal only. |
| "You" | Rows where `facilitator_id` = invoker (original facilitator; handoffs don't move credit). |
| "This server" | Rows where `guild_id` = current guild. |
| Windows | Based on `started_at` (UTC ISO) relative to now. |

Requires new read helpers in `app/db.py` (none exist today). Queries run on the shared synchronous connection; volume is small.

### `/teamode-clear`

- Invoker must have Manage Messages permission in the channel; otherwise ephemeral refusal.
- Scans the last `CLEAR_SCAN_LIMIT` messages in the channel; deletes bot-authored messages that are: welcome embeds, Set Intention prompts, Time's up messages, Reflect/follow-up messages (including the ⛔ follow-up line), wrap-up nudges, chaining prompts, and break messages.
- Keeps: timer messages (they hold the facilitator intention), handoff notices, and every message belonging to a currently active session or break.
- Deletes one at a time (no bulk delete, which would need Manage Messages for the bot); respects Discord rate limits (~5 deletes / 5 s per channel) via discord.py's built-in handling. Defers the interaction ephemerally and replies with the count when done.
- Requires Read Message History (already needed for Reflect reactions).

## Voice Channel Status

Set via `VoiceChannel.edit(status=...)` (discord.py routes a status-only edit to `PUT /channels/{id}/voice-status`, `discord/abc.py:568`). Requires the "Set Voice Channel Status" permission; on `Forbidden`/`HTTPException`, log WARNING and continue.

**Unverified permission risk:** Discord may additionally require Manage Channels when the bot is not connected to the voice channel. Most statuses (Starting, Finished, terminal, Break, startup crashed reset) are set while the bot is out of voice; only Timer is set while connected. The first voice-status Discord smoke test must explicitly confirm whether out-of-voice status edits succeed. If they fail with `Forbidden`, the User chooses between granting Manage Channels on the voice channels or restricting status updates to while-connected only.

**Required bot permissions** (for README and invite URL): View Channels, Send Messages, Embed Links, Read Message History, Add Reactions, Connect, Speak, Use Application Commands (labelled "Use Slash Commands" in the Developer Portal), Set Voice Channel Status. Invite integer `281477127425088` (previous `2150714432` + bit 48). OAuth2 scopes `bot` + `applications.commands`. No privileged intents. The bot needs no Manage Messages (it deletes only its own messages); `/teamode-clear` checks the invoker's Manage Messages. Existing servers need the permission added to the bot role (and to per-channel overrides on private voice channels).

| Moment | Status constant |
|---|---|
| `/teamode` launched | Starting |
| Timer running (after modal submit / `mark_active`) | Timer, with end time HH:MM |
| Session completed (follow-up reached) | Finished, with completion time HH:MM |
| Cancelled / expired / crashed | Matching terminal status |
| Break running | Break, with end time HH:MM |

On startup, after reconciliation marks sessions `crashed`, set the crashed status on those sessions' voice channels (IDs in `voice_channel_id`) once the gateway is ready. Reconcile must return or expose the affected voice channel IDs.

## Reliability and Operations

- **PID lock** (`TODO.md` §Next Patch "PID file lock"): in `teamode.py` before `init_db`. If `PID_FILE_PATH` exists and that PID is alive → log ERROR and exit cleanly (non-zero); if stale → overwrite. Remove via `atexit` on clean shutdown. No new dependencies.
- **ffmpeg probe** (`TODO.md` §Next Patch "`ffmpeg` startup probe"): `shutil.which("ffmpeg")` at startup; if missing, log the WARNING text from TODO.md verbatim. Non-fatal. (Log output, not Discord copy.)
- **Restarts:** all new in-memory state (rate-limit windows, daily counter, last Time's up IDs, breaks, Go again buttons) resets on restart — accepted. Buttons from before a restart (duration, Go again, Break, chaining) reply with the stale-button refusal and do nothing. Startup order stays `init_db → reconcile → gateway`.
- **Logging:** stdout only, INFO default. INFO for lifecycle events (session start/end with state, break start/end/cancel, rate-limit and cap refusals, `/teamode-clear` counts); WARNING for degraded operation (missing permission, ffmpeg missing, 429, failed delete, invalid timezone); `logger.exception` in background task error handlers.

## Art Assets

- Generated by a one-off script in `scripts/` using Pillow. Pillow goes in a new `requirements-dev.txt` (dev-only; not a runtime dependency; runtime `requirements.txt` unchanged apart from existing pins).
- Outputs to `assets/`: application icon 1024×1024 (1:1), application banner 680×240 (17:6), bot avatar (1024×1024). PNG, ≤ 10 MB. Style: matcha sage / steeping forest palette per `.project-meta/UI-ADR.md` §"Color palette"; teacup/kettle/steam motif.
- User reviews the PNGs and uploads them via the Discord developer portal (no code sets the avatar).

## ASCII Teacup Banner

Shown on the welcome message, inside a code block. Canonical art (candidate #2, generated during planning and explicitly approved by the User as an exception to the no-AI-generated-runtime-text rule; record this exception in UI-ADR):

```
     )  )
    (  (
   _______
  |       |__
  | TEA   |  )
  |  MODE |_/
   \_____/
  '-------'
```

Stored in `app/constants.py` as `TEACUP_BANNER`.

## Typing and Tooling

- **Type hints:** parameters and return types on every function in `app/` and `teamode.py` (retrofit existing code). Annotate locals only where they communicate information (values that can be missing or have multiple types, non-obvious container shapes). Enforced by Ruff `ANN` rules for `app/` and `teamode.py`; `tests/` exempt.
- **`cast()` / `# type: ignore`:** remove all 12 existing occurrences (`app/bot.py` :150, :184, :196, :200, :330, :569, :661, :854, :929, :968; `app/db.py:90`; `app/voice.py:28`) using `isinstance` / `None` narrowing, `interaction.channel_id`, and `connect(cls=discord.VoiceClient)` or an `isinstance` check. Convention becomes: banned, except for upstream stub bugs, which require a specific error code (`# type: ignore[code]`) and a one-line justification comment.
- **pyright config** (`[tool.pyright]` in `pyproject.toml`): `venvPath = "."`, `venv = ".venv"`; exclude `.venv`, `**/__pycache__`, `.apm`, `.claude`, `.ruff_cache`; disable checks Ruff already covers (e.g. `reportUnusedImport`, `reportUnusedVariable`, and other unused-symbol reports) so warnings are not duplicated; import organization left to Ruff. Plain `pyright` must run clean.
- **Ruff config** (`[tool.ruff]` in `pyproject.toml`): enable `ANN` for `app/` and `teamode.py` via per-file ignores exempting `tests/`; keep existing rules passing.
- **Dependencies:** discord.py stays `2.7.1`. PyNaCl stays `1.5.0` (discord.py 2.7.1 pins `PyNaCl<1.6`; `pip install discord.py[voice]==2.7.1 PyNaCl==1.6.2` is `ResolutionImpossible`; upstream `master` at `2.8.0a` already requires `PyNaCl>=1.6.0,<1.7`). Document `PYSEC-2026-1448` and `PYSEC-2026-3002` in `changelog.md` Known issues with "resolves when discord.py 2.8 ships"; run `pip-audit` with documented `--ignore-vuln` flags for those two IDs; add a `TODO.md` §Future item to bump when 2.8 releases. New deps: Pillow (dev only). Stdlib `zoneinfo` (no dep). Python 3.12 has system tzdata on WSL; if `ZoneInfoNotFoundError` occurs, fall back to UTC with a WARNING rather than adding `tzdata`.

## Documentation

| Document | Changes |
|---|---|
| `README.md` | New commands (`/teamode-stats`, `/teamode-clear`), chained sessions/breaks, env vars (`TEAMODE_DEV_GUILD_ID`, `TEAMODE_TIMEZONE`), full permission list and invite integer per Voice Channel Status §"Required bot permissions" (plus Manage Messages note for `/teamode-clear` invokers and how to add Set Voice Channel Status to an existing bot role), ffmpeg install line in Requirements, correct guild-sync behavior (unset `TEAMODE_DEV_GUILD_ID` skips registration), session diagram matching real copy. |
| `.project-meta/UI-ADR.md` | Canonical copy below; embed timer spec; chaining/break surfaces; supersede "do not preempt" note; resolve "Pending UI decisions"; teacup AI-art exception; note that copy lives in `app/constants.py`. |
| `docs/sqlite-schema.md` | Correct timestamp format (`+00:00`, not `Z`); document read helpers used by stats. |
| `.project-meta/conventions.md` | Type-hint rule; `cast`/ignore escape hatch; copy and tunables live in `app/constants.py`; package layout; channel-send rule. |
| `AGENTS.md` | Architecture and project structure for `app/discord_bot/` and new modules; key files; env vars. Preserve the "Working Preferences" section. |
| `changelog.md` | `v26Q3.0.0.0` entry; Known issues (both PyNaCl IDs). |
| `TODO.md` | Remove shipped items; remove the "rename bot.py" Future item; add discord.py 2.8 bump item; keep the User's other entries. |
| `.env.example` | Add `TEAMODE_TIMEZONE`. |
| Stale code comments | `_ACTIVE_TIMER_FMT` "two spaces" comment, durations docstring ("10 / 25 / 50"), duplicated Set Intention prompt text (`_MSG_PARTICIPANT_PROMPT` vs inline f-string) — resolved by moving copy to constants. |

## Canonical Copy

All strings below are User-approved and must be used verbatim (placeholders in `{braces}`). Existing strings currently in `app/bot.py` move to `app/constants.py` unchanged.

### Voice channel status

| Key | Text |
|---|---|
| `VOICE_STATUS_STARTING` | `🍵 Starting TeaMode` |
| `VOICE_STATUS_TIMER` | `⏳ to {hhmm}` |
| `VOICE_STATUS_FINISHED` | `✨ Finished TeaMode at {hhmm}` |
| `VOICE_STATUS_CANCELLED` | `🍵 Cancelled` |
| `VOICE_STATUS_EXPIRED` | `🍵 Expired` |
| `VOICE_STATUS_CRASHED` | `🍵 Crashed` |
| `VOICE_STATUS_BREAK` | `⏸️ Break until {hhmm}` |

### Embed timer

| Key | Text |
|---|---|
| `TIMER_EMBED_TITLE` | `🍵 TeaMode • {duration} min session` |
| Field names | `Intention`, `Facilitator`, `Started at` |
| `PHASE_DEEP_FOCUS` | `Deep focus` |
| `PHASE_WRAP_UP` | `Wrap up — finish your current task` |
| `TIMER_REMAINING` | `{mmss} remaining` |
| Progress line | `{bar} {percent}%` (e.g. `█████░░░░░ 50%`) |
| `TIMER_CONTENT` | `⏳ {mmss}` (mentions on the next line on initial send) |
| Solo-grace final | `Session ended — facilitator did not return.` (existing) |

### Chaining and breaks

| Key | Text |
|---|---|
| `CHAIN_PROMPT` | `Go again? / Take a 5-minute break?` |
| `BUTTON_GO_AGAIN` | `Go again` |
| `BUTTON_BREAK` | `Take a 5-minute break` |
| `BREAK_STARTED` | `⏸️ Break started — back at {hhmm}` |
| `BREAK_OVER` | `⏸️ Break is over` (with Go again button) |
| `BREAK_CANCELLED` | `⏸️ Break cancelled by /teamode` |
| Go again expiry | Button disabled; no new text. |

### Refusals, nudge, expiry

| Key | Text |
|---|---|
| `MSG_RATE_LIMIT_USER` | `Per-user rate limit — try again in {seconds} seconds.` |
| `MSG_RATE_LIMIT_GUILD` | `Daily server limit reached ({cap} sessions per day) — resets at midnight.` |
| `MSG_WRAP_UP_NUDGE` | `⏰ Wrap-up nudge — {minutes} minutes left.` |
| `MSG_PENDING_EXPIRED` | `🍵 Expired` (edited onto the welcome; buttons disabled) |
| `MSG_SESSION_INACTIVE` | `This session is no longer active.` (existing; used for all stale buttons) |

### `/teamode-stats`

| Key | Text |
|---|---|
| Command description | `Show TeaMode stats for you and this server.` |
| `STATS_TITLE` | `🍵 TeaMode stats` |
| Section names | `You`, `This server` |
| Row labels | `Last 7 days`, `Last 30 days`, `All time` |
| Row value | `{n} sessions · {minutes} min · {rate}% completed` |
| `STATS_STREAK` | `🔥 Streak: {days} days` |
| `STATS_EMPTY` | `No sessions yet — run /teamode to start one.` |

### `/teamode-clear`

| Key | Text |
|---|---|
| Command description | `Delete past TeaMode messages in this channel (keeps timers).` |
| `CLEAR_DONE` | `🧹 Cleared {n} messages.` |
| `CLEAR_NOTHING` | `Nothing to clear.` |
| `CLEAR_NO_PERMISSION` | `You need the Manage Messages permission to run /teamode-clear.` |

### Welcome banner

`TEACUP_BANNER` — see ASCII Teacup Banner.

Any string not listed here that a feature turns out to need must be requested from the User (no agent-authored runtime copy).
