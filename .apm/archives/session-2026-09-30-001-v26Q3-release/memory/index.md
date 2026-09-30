---
title: TeaMode v26Q3.0.0.0
---

# APM Memory Index

## Memory Notes

- User approves in terse replies ("y"). Every merge into `main` needs an explicit User "y" after seeing commits + changed files; Workers commit freely on feature branches. Task Prompts should state "commit freely on your branch" explicitly — one Worker misread the Rules and withheld a commit.
- Dispatch is foreground and sequential (User preference; parallel worktrees were costly in the MVP). Agent calls nonetheless run as background tasks in this environment — wait for the completion notification before reviewing.
- `ruff` and `pyright` live only in `.venv/bin`; Task Prompts must tell Workers to `source .venv/bin/activate` first.
- `app/discord_bot/` uses mixin composition: `TeaModeBot(CommandsMixin, ViewsMixin, TimerMixin, LifecycleMixin, BreakMixin, ClearMixin)` in `client.py`. Each mixin declares the `self` attributes it reads as type-only class annotations; cross-mixin typing uses structural Protocols (e.g. `_ModalBot` in `views.py`) with `TYPE_CHECKING`-guarded stubs — never `cast()`.
- Test fakes for channels must be spec'd (`AsyncMock(spec=discord.TextChannel)` / `MagicMock(spec=discord.VoiceChannel)`) because production code now narrows with `isinstance`; unspec'd mocks silently fail narrowing. Interaction fakes must set `channel_id` explicitly.
- All Discord copy and tunables live in `app/constants.py` (all canonical copy for later features already present, verbatim). Old private `_MSG_*` / `_*_SECONDS` names no longer exist; tests import from `app.constants`.
- Rate limit decision: allowance 3 per 300 s window, 4th refused (User confirmed over TODO.md wording).
- Discord smoke tests: shortest testable duration is 1 minute (`DURATIONS_MINUTES` must be ints — custom_id parsed with `int()`); lower `PENDING_TIMEOUT_SECONDS` for expiry checks. The User edits `app/constants.py` in place for smoke tests and may leave comments — commit those on request, run `ruff format` (inline comments need two spaces). Disabled Discord buttons cannot be clicked, so stale-button refusals are unit-test-only.
- Key runtime helpers after Stage 2: `CommandsMixin._start_session(interaction)` (shared start: guards → rate limit → create session → previous-session cleanup → welcome); `spawn_logged(coro, name)` in `app/discord_bot/tasks.py` for every background task; async `LifecycleMixin._on_session_terminal(session_id, *, delete_setup_messages=True)` as the single terminal hook (extend it for voice status); `_SetupMessages` per session; `_ChannelCleanup` per text channel (Time's up, Reflect, ⛔ line); `_build_active_timer_content(...)` single timer-content builder; `_build_timer_view(session_id, *, disabled=False)`.
- Session flow as shipped: duration buttons stay enabled while pending (re-pick allowed, latest wins); intention submit disables them and cancels pending expiry; modal double-submit refused with `MSG_SESSION_INACTIVE`. At next session start: previous Time's up and ⛔ line deleted, previous Reflect embed stripped (content kept). `/teamode-clear` must classify Reflect with or without embed.
- Planning-doc accuracy: Manager-authored prompt details can contradict the Spec (pending-expiry cancel point) — cross-check Task Prompt instructions against Spec wording for state-machine behavior before dispatch.
- The User keeps smoke-test values uncommitted in `app/constants.py` for long stretches and edits copy there directly. Never let Workers stage that file; commit User-requested lines via backup → edit to HEAD + change → commit → restore; stash that one file around branch switches. Tell Workers to run pytest against `git show HEAD:app/constants.py` and restore.
- Voice channel status is set only while Ocha is connected (Discord needs Manage Channels otherwise; User chose not to grant it): Timer, Finished (`✨ Done at {hhmm}`), solo-grace Cancelled (set before disconnect). Break start/over statuses are set while Ocha stays in voice during breaks. No Starting/Expired/Crashed status. Helper: `LifecycleMixin._set_voice_status(channel_or_id, status)`.
- Timer surface after Stage 3: `_build_timer_message(...)` returns `(content, embed)`; `_EditState.started_at` / `nudge_sent`; fields Intention / Facilitator / Range (`{start} to {end}`); content `⏳ MM:SS remaining`; nudge threshold 10 min with singular/plural copy, wind chime via `voice.play_wind_chime`, nudge ID on `_SetupMessages` deleted at terminal cleanup.
- Sound credits for README: wind chime by GnoteSoundz (CC0); reverie by Seemant Chandra (Instagram: piyush.x_x) — do not mention or link the source project. Repo is private.
- Auto-handoff (random among remaining humans) exists from the MVP but is still unverified live; needs a second account.
- The User may postpone individual smoke-test steps "to production"; record each postponed check as an entry in `TODO.md` § Notes (User wants them there) and commit it with the Stage's APM artifacts.
- `scripts/teamode_launcher.sh` dev mode runs whatever branch is checked out in the repo dir: keep a branch under User test checked out until tested; run concurrent Workers in a worktree under `.apm/worktrees/` (symlink `.venv`; never stage it). Worktrees under `.apm/` trip the injection scan with false positives from repo docs.
- The User is token-budget conscious late in sessions; keep reports terse.
- Discord API pacing: prefer proactive pacing (tunable interval in `app/constants.py`) over relying on discord.py 429 retries for loops of API calls — the User reads the terminal and treats 429 WARNINGs as defects.

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

### Stage 3 - Embed Timer and Voice Channel Status

Stage 3 grew from two to three Bot Engineer Tasks and landed in two merges (`0970a4d` embed timer, `92e8d24` voice status). Task 3.1 added pure `app/timer_format.py` and replaced the plain-text timer with an embed + `⏳` content fallback, Deep focus → Wrap up phase (sage → amber), one-time wrap-up nudge, and a frozen muted-red solo-grace final state (`5fc3279`, `d86fce3`). The Worker committed a mid-task User edit of `NUDGE_MIN_DURATION_MINUTES` (20 → 10), which the User then confirmed. The 3.1 smoke test passed on desktop, mobile and with embeds disabled, and produced Task 3.3 (User decisions): singular/plural nudge copy, a wind chime (`assets/wind-chime.wav`, CC0 by GnoteSoundz) played in voice with the nudge, nudge deletion at terminal cleanup, and `⏳ MM:SS remaining` (`dd0f517`, `ebf82f2`, `18800b5`). The Manager then added the User-specified `Range` field (`HH:MM to HH:MM`, `e06bc57`, `d1d0bb3`) and committed User constant comments. Task 3.2 set statuses at every moment (`e1716a9`, `f712ce1`); the smoke test confirmed Discord refuses out-of-voice status edits without Manage Channels, and the User chose option B — status only while connected — so a follow-up (`f6b1010`) kept Timer, Finished and solo-grace Cancelled (reordered before disconnect), removed Starting/Expired/Crashed plumbing, and dropped Break status from Stage 4. The Manager removed the unused status copy (`ec726a9`) and committed the User's `✨ Done at {hhmm}` wording (`34a6e2c`). Suite at 238 tests. Working pattern established: the User keeps smoke values uncommitted in `app/constants.py`; Manager commits requested lines via backup/edit/restore and stashes around merges. The auto-mode shell classifier had transient outages; file tools and shorter commands worked around them.

**Task Logs:**
- task-03-01.log.md
- task-03-02.log.md
- task-03-03.log.md

### Stage 4 - Chained Sessions, Breaks and Channel Clear

Stage 4 grew from two to three Bot Engineer Tasks and landed in two merges. Task 4.1 added `app/discord_bot/breaks.py` (`BreakMixin`, `_ChainState`, `_BreakState`): the post-✅/⛔ chaining prompt, Go again through the shared `_start_session`, and an in-memory 5-minute break with reverie, post-break Go again button and timeout (`3a65017`, `e126814`). Its smoke test passed 5/5 and produced Task 4.3 (User decisions): a long-break streak offer after ≥ 2 chained ≥ 25-minute sessions (`chain_streak` prompt kind, `teamode:<sid>:break:long`) and Ocha staying in voice during breaks with `⏸️ to {hhmm}` / `✨ Break over at {hhmm}` statuses (`a3fcfce`, `46ed2f6`); the User postponed the 4.3 re-check to production and both merged as `ab3711a`. A Manager Handoff (1 → 2) occurred before 4.2. Task 4.2 added pure `app/cleanup.py` (matchers derived from constants via a format-template-to-regex helper, timers checked first) and `ClearMixin` in `app/discord_bot/clear.py`, protecting the live session's messages (including a follow-up Reflect), live chain prompts and breaks, and clearing consumed `_channel_cleanup` IDs (`f12ddeb`). Review found the Worker filtered by `author.bot` rather than Ocha's own id; the Manager fixed it (`2121363`). The User's smoke passed (steps 1, 4, 5; clear without a prior `/teamode` is intended; no-permission refusal postponed to production) but showed discord.py 429 retries, so the Manager added `CLEAR_DELETE_INTERVAL_SECONDS = 1.0` pacing at the User's request (`6194eeb`); merged as `e244097`. Both postponed checks are recorded in `TODO.md` § Notes. Suite at 308 tests.

**Task Logs:**
- task-04-01.log.md
- task-04-02.log.md
- task-04-03.log.md

### Stage 5 - Extras: Stats, Teacup Banner, Art Assets

Stage 5 ran as a Bot Engineer batch (5.1 + 5.2) and an Asset Designer Task (5.3). Before dispatch the User settled three stats copy gaps (`— completed` when no answers, singular `1 session` / `1 day`, zero streak hidden); the Manager pre-added those constants plus `WELCOME_BANNER_BLOCK` (`27a5116`). The batch added db read helpers, pure `app/stats.py`, `StatsMixin` for `/teamode-stats`, and the teacup banner at the top of the welcome embed (`89fe281`, `60c1891`, `ca3035a`); the User confirmed both in Discord and it merged as `ca9c6bd`. The Manager had switched the repo dir to the art branch before the User tested, so the launcher ran code without `/teamode-stats`; restored by checking the stats branch back out — later Worker runs used a worktree to keep the repo dir stable. 5.3's first design had a detached handle and floating cup; the User asked for three candidates per image in `.debug-images/` (`c12dca6`: fixed cup, kettle pouring, monoline badge) and chose candidate 1 for all three, committed as `app-icon.png`, `app-banner.png`, `app-avatar.png` (`3965d58`); merged as `3f4122a`. Suite at 330 tests.

**Task Logs:**
- task-05-01.log.md
- task-05-02.log.md
- task-05-03.log.md

### Stage 6 - Documentation and Release Prep

With the User's go-ahead, 6.1 was dispatched while 5.3 awaited the art pick. The Docs Writer synced README (commands, env vars, permissions and invite integer `281477127425088`, ffmpeg, `~/.teamode-secrets` launcher sample, sound credits without the reverie's source project), UI-ADR, conventions, schema doc, AGENTS.md (APM_RULES and Working Preferences unchanged), a `v26Q3.0.0.0` changelog entry with both PyNaCl PYSEC IDs, and TODO (`8f1c26a`, `523f2e0`). The Manager recorded the chosen art as shipped (`0a31e0c`, after catching and redoing an over-broad TODO edit); merged as `07227a8`. Tag and push await User approval.

**Task Logs:**
- task-06-01.log.md

