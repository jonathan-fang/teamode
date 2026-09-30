---
title: TeaMode v26Q3.0.0.0
---

# APM Memory Index

## Memory Notes

- User approves in terse replies ("y"). Every merge into `main` needs an explicit User "y" after seeing commits + changed files; Workers commit freely on feature branches. Task Prompts should state "commit freely on your branch" explicitly — one Worker misread the Rules and withheld a commit.
- Dispatch is foreground and sequential (User preference; parallel worktrees were costly in the MVP). Agent calls nonetheless run as background tasks in this environment — wait for the completion notification before reviewing.
- `ruff` and `pyright` live only in `.venv/bin`; Task Prompts must tell Workers to `source .venv/bin/activate` first.
- `app/discord_bot/` uses mixin composition: `TeaModeBot(CommandsMixin, ViewsMixin, TimerMixin, LifecycleMixin)` in `client.py`. Each mixin declares the `self` attributes it reads as type-only class annotations; cross-mixin typing uses structural Protocols (e.g. `_ModalBot` in `views.py`) with `TYPE_CHECKING`-guarded stubs — never `cast()`.
- Test fakes for channels must be spec'd (`AsyncMock(spec=discord.TextChannel)` / `MagicMock(spec=discord.VoiceChannel)`) because production code now narrows with `isinstance`; unspec'd mocks silently fail narrowing. Interaction fakes must set `channel_id` explicitly.
- All Discord copy and tunables live in `app/constants.py` (all canonical copy for later features already present, verbatim). Old private `_MSG_*` / `_*_SECONDS` names no longer exist; tests import from `app.constants`.
- Rate limit decision: allowance 3 per 300 s window, 4th refused (User confirmed over TODO.md wording).
- Discord smoke tests: shortest testable duration is 1 minute (`DURATIONS_MINUTES` must be ints — custom_id parsed with `int()`); lower `PENDING_TIMEOUT_SECONDS` for expiry checks. The User edits `app/constants.py` in place for smoke tests and may leave comments — commit those on request, run `ruff format` (inline comments need two spaces). Disabled Discord buttons cannot be clicked, so stale-button refusals are unit-test-only.
- Key runtime helpers after Stage 2: `CommandsMixin._start_session(interaction)` (shared start: guards → rate limit → create session → previous-session cleanup → welcome); `spawn_logged(coro, name)` in `app/discord_bot/tasks.py` for every background task; async `LifecycleMixin._on_session_terminal(session_id, *, delete_setup_messages=True)` as the single terminal hook (extend it for voice status); `_SetupMessages` per session; `_ChannelCleanup` per text channel (Time's up, Reflect, ⛔ line); `_build_active_timer_content(...)` single timer-content builder; `_build_timer_view(session_id, *, disabled=False)`.
- Session flow as shipped: duration buttons stay enabled while pending (re-pick allowed, latest wins); intention submit disables them and cancels pending expiry; modal double-submit refused with `MSG_SESSION_INACTIVE`. At next session start: previous Time's up and ⛔ line deleted, previous Reflect embed stripped (content kept). `/teamode-clear` must classify Reflect with or without embed.
- Planning-doc accuracy: Manager-authored prompt details can contradict the Spec (pending-expiry cancel point) — cross-check Task Prompt instructions against Spec wording for state-machine behavior before dispatch.

## Stage Summaries

### Stage 1 - Foundation: Tooling, Package Split, Constants, Typing

Stage 1 completed in two Bot Engineer batches, each on its own branch, both merged `--no-ff` after User approval (`14c2c2c` for `refactor/discord-bot-package`, then `refactor/constants-and-typing`). The first batch added explicit pyright/Ruff config (`1d1cb65`) — pyright was in fact already clean before config, contrary to the planning assumption — and split the 1038-line `app/bot.py` into `app/discord_bot/` using mixins (`38a5cef`); pyright's per-mixin analysis required type-only attribute declarations on each mixin. The second batch created `app/constants.py` with every tunable, palette hex value, existing string (inventory larger than planned: handoff copy, Time's up, Reflect, "why" prompt) and all new canonical copy including `TEACUP_BANNER` with an exact-lines test, plus duration-pick validation (`fad6354`); then enabled Ruff `ANN` (no violations — code was already annotated) and removed all 13 cast/ignore occurrences, including one the split introduced, via isinstance narrowing, `channel_id`, a `None` guard on `lastrowid`, and a `_ModalBot` Protocol (`9b5e562`, committed by the Manager because the Worker misread the approval rule). Test fixtures were corrected to spec'd mocks without assertion changes. Suite grew from 122 to 125 tests; all five checks clean. The User ran the end-of-Stage Discord session check on the branch before approving the merge.

**Task Logs:**
- task-01-01.log.md
- task-01-02.log.md
- task-01-03.log.md
- task-01-04.log.md

### Stage 2 - Core Reliability and Session Behavior

Stage 2 grew from four to five Bot Engineer Tasks and landed in two merges. Batch 2.1+2.2 (merged after User approval) added `app/pidlock.py` with the single-instance lock wired before `init_db`, the verbatim ffmpeg WARNING probe, `TEAMODE_TIMEZONE` (`app.config`, falls back to Los Angeles then UTC), and pure `app/rate_limit.py` (per-user 3/300 s window checked before the per-guild 50/day cap at local midnight; refusals record nothing) behind the extracted `_start_session`. Batch 2.3+2.4 added pending expiry, the `spawn_logged` background-task wrapper, real 429 backoff gating (countdown-seconds based), a unified stale-button refusal, the centralized `_on_session_terminal` hook with welcome/Set Intention deletion, previous Time's up deletion, and one-time timer mentions (edits keep the line with `AllowedMentions.none()`). Review found the Manager's own prompt had told the Worker to cancel expiry on duration pick, contradicting the Spec and re-creating the lockout after a dismissed modal; the Manager fixed it directly (`b3583f3`). The User's Stage 2 smoke test passed (PID lock, expiry ×2, rate limit, full session, cleanup, previous Time's up) and prompted new decisions recorded in the Spec and as Task 2.5: re-pickable durations until intention submit with a double-submit guard, and next-start cleanup that deletes the ⛔ line and strips only the Reflect embed (`15b4a99`, `af0375e`). The User re-checked 2.5 in Discord and asked to commit their `app/constants.py` comments (`a762157`, formatted). Stage merged as `a0e5e27`; suite at 183 tests. Known leftover: ~6 harmless "coroutine never awaited" test warnings from mocked `create_task` since `spawn_logged` — candidate cleanup for the docs/TODO Task.

**Task Logs:**
- task-02-01.log.md
- task-02-02.log.md
- task-02-03.log.md
- task-02-04.log.md
- task-02-05.log.md
