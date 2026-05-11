---
title: TeaMode
---

# APM Memory Index

## Memory Notes

- **`pytest-asyncio` config:** the project uses `pytest-asyncio==0.26.0` without an explicit `asyncio_mode` setting, which emits a deprecation warning every test run. The first task that introduces async tests (T2.1) should add `asyncio_mode = "strict"` to `pyproject.toml` (or `[pytest]` in `pytest.ini`) to silence the warning and pin behavior before the library's default flips.
- **Package vs repo-root naming:** the Python package is `app/`; the repo root directory on disk is also named `teamode/` (visible in `AGENTS.md`'s tree diagram, line 22). When dispatching, refer to the package as "`app/`" explicitly to avoid worker confusion when they re-read `AGENTS.md`. The slash command `/teamode` and entry-point file `teamode.py` are unrelated to either.
- **Test environment dependency:** `app/config.py` raises `RuntimeError` at module import time when `DISCORD_BOT_TOKEN` is unset. The whole test suite depends on `tests/conftest.py` calling `os.environ.setdefault("DISCORD_BOT_TOKEN", "test-stub-token")` before any `app.*` import. New test modules inherit this for free; running tests outside pytest (e.g. ad-hoc `python -c "from app import session"`) needs the env var set manually. If this brittleness bites again, a factory pattern (`Config.load()`) is the right refactor — punt until then.
- **discord.py event registration gotcha:** `Client.event(func)` uses `func.__name__` to determine which Discord event the handler responds to. Method names with leading underscores (e.g. `_on_ready`) silently fail to register because no event by that name exists. Always name event handlers with the public `on_<event>` form. Caught the hard way during T2.2 smoke test. Also documented in `docs/discordpy-api/gotchas.md` for visibility next to the offline API reference.
- **discord.py `on_interaction` + `CommandTree` separation:** `on_interaction` fires for every interaction type but the `CommandTree` has already routed `APPLICATION_COMMAND` types via internal `_state._command_tree._from_interaction` before `on_interaction` runs. A custom `on_interaction` listener that wants to handle component clicks must filter to `interaction.type == discord.InteractionType.component` and not attempt to re-dispatch slash commands (no `process_application_commands` method exists). Documented in `docs/discordpy-api/gotchas.md`.
- **discord.py `Label.component` type erasure:** when a `Modal` wraps a `TextInput` in a `Label`, pyright sees `Label.component` as `Item[Unknown]` not `TextInput`, so `.value` access errors. Use `cast(discord.ui.TextInput[discord.ui.Modal], label.component).value` at the read site. Documented in `docs/discordpy-api/gotchas.md`.
- **`interaction.followup.send` over `channel.send` after a modal/interaction.** `interaction.channel.send(...)` and `client.fetch_channel(...)` go through the bot's regular HTTP path and require explicit channel-level View/Send perms. `interaction.followup.send(content, ephemeral=False, wait=True)` reuses the interaction webhook token and skips that gate — it just works wherever the original interaction was accepted. Default to followup for any post-interaction send. Resolve channel objects from `interaction.channel` directly rather than `client.fetch_channel(...)`; for cross-handler use, thread the resolved object through (e.g. `IntentionModal.__init__`) instead of re-fetching by id.
- **Private-channel deployment requires explicit role allow-list.** Discord evaluates role grants → channel overrides → category overrides with denies winning. In a private channel, `@everyone` is denied View Channel by default and role-level grants do not propagate. Bot must be added as an explicit allow on the channel. Documented in `docs/discord-bot-setup.md` § "Private voice channels".
- **Parallel-dispatch overhead can erase the wall-clock win.** Stage 3 ran T3.1 + T3.2 in parallel via worktrees. T3.2's worker engaged with a User mid-dispatch question, never returned a Task Result, and required a recovery dispatch (~75k extra tokens). The wall-clock savings vs sequential were net-negative once recovery was counted. For future parallel opportunities (T5.3 + T5.4), default to sequential unless the User explicitly wants parallel again.
- **Don't message an in-flight worker directly.** Workers receive direct user messages and will engage with them, breaking the apm-worker "no User interaction" contract — they may forget to commit, log, or return a `## Task Result`. User has confirmed: route any mid-dispatch question through the Manager (queue it; Manager answers when worker returns or relays after).

## Stage Summaries

### Stage 3 — Intention + Timer + Voice

Three Tasks delivered the timer-pick handler, intention modal, voice connection plumbing, active timer surface, and the drift-corrected countdown coroutine. T3.1 and T3.2 dispatched in parallel via worktrees; T3.3 sequential after both merged. T3.3 needed three follow-up cycles after smoke testing.

T3.1 (`feat/voice-plumbing`, commit `bcf6940`) added `app/voice.py` — three thin shims (`connect`, `play_reverie`, `disconnect`) over `discord.FFmpegPCMAudio` and `VoiceClient`, with `REVERIE_PATH` resolved at import. Seven tests cover happy paths and exception propagation, all mocking `voice_client.play` so no real `ffmpeg` invocation. Clean first pass.

T3.2 (`feat/timer-intention`, commit `6409d35`) wired the `on_interaction` listener with custom_id dispatch (`teamode:<sid>:timer:<value>` → `_handle_timer_pick` → `set_duration` → `IntentionModal`), the modal with one `discord.ui.TextInput`, the modal-submit chain (`set_intention` → defer → participant prompt). Worker engaged with a User question mid-dispatch (re: `CommandTree`) and never returned a Task Result; recovery worker fixed three pyright errors introduced by the original (notably `CommandTree.process_application_commands` doesn't exist) and committed cleanly.

T3.3 (`feat/active-timer-countdown`, six commits) shipped the `run_countdown` coroutine in `app/session.py` (Discord-independent, dependency-injected `sleep` and `monotonic` for `FakeClock` testing), the `_EditState` per-session holder with 10s edit cadence and 429 exponential backoff, and the post-intention flow chain (voice connect → mark_active → active timer post → countdown task → mark_followup). Three follow-up cycles after smoke testing: (a) `interaction.channel.send` 403'd because the bot lacked direct channel-send perms in the dev server's voice channel — switched to `interaction.followup.send(ephemeral=False, wait=True)` (commit `588dced`); (b) `client.fetch_channel(voice_channel_id)` 403'd similarly via the REST permission gate — User chose Option A: thread the resolved `discord.VoiceChannel` through `IntentionModal.__init__`, dropping the REST call (commit `b4e0693`); (c) timer message format refreshed to a three-line layout (`Facilitator's Intention` / `<duration> min session` / `⏳ MM:SS`) per User direction (commit `758d3a1`); plus participant prompt bolded `**[Set Intention]**`. User-side companion fix: explicit channel overrides on the voice channel for the TeaMode role.

Stage verification: full pipeline clean on `main` post-merge (84 tests pass, ruff clean, pyright 0 errors, scan clean) plus manual Discord smoke test in dev guild — facilitator submitted intention, Ocha auto-joined voice, three-line timer ticked correctly to zero with 10s edits, SQLite reached `status='followup'`. Reverie not yet played (T4.1 scope).

**Scope drift to address in T4.1:** the T3.3 worker added `voice_client.disconnect()` immediately after `mark_followup` (around `app/bot.py:182`), causing the bot to leave voice before reverie can play. T4.1's prompt explicitly removes this premature disconnect and reorders the post-followup sequence per Spec § Voice.

Documentation added: `docs/state-machine.md`, `docs/discord-bot-setup.md`, `docs/discordpy-api/{api,interactions-api,ext-commands-api,ext-tasks}.html` (offline reference), `docs/discordpy-api/gotchas.md`, `docs/fake-clock.md`, `docs/sqlite-schema.md` § "Viewing the database". TODOs added: app icon + banner (v1.x), `app/bot.py` rename (v1.x deferred), modal `required=False` + empty-intention display (v1.x), three-minute wrap-up nudge (v1.x), embed timer with progress bar + phase labels inspired by dlqa's `FocusTimerWidget` (v2). Spec § "Visual fidelity tier" updated. UI-ADR welcome embed copy synced.

**Task Logs:**
- task-03-01.log.md
- task-03-02.log.md
- task-03-03.log.md

### Stage 2 — Invocation + Welcome

Two Tasks delivered the session state machine and the Discord-facing slash command + invocation guard + welcome surface. T2.1 ran clean; T2.2 needed two follow-up adjustments after first delivery.

T2.1 (`feat/session-state-machine`, commit `972e289`) shipped `app/session.py` with the `SessionState` enum, `Session` dataclass, `SessionRegistry` orchestrator (in-memory + SQLite in lockstep, channel-exclusivity invariant), 19 new tests covering happy path, refusals from each state, parallel-channel safety, channel exclusivity, handoff, and registry lookups. Also pinned `pytest-asyncio` to `strict` mode in `pyproject.toml` (silencing the deprecation warning carried over from Stage 1) and added `tests/conftest.py` with a stub-token fixture so the suite runs without a live `DISCORD_BOT_TOKEN`.

T2.2 (`feat/slash-command-welcome`, six commits) shipped `app/bot.py` with `discord.Client` + command tree, the cumulative invocation guard (channel-type → in-voice → no-active-session), the welcome embed with timer-pick button row using the `teamode:<session_id>:timer:<value>` namespace, and full entry-point wiring in `teamode.py` (config → init_db → reconcile → registry → bot). Also extended `app/config.py` with `TEAMODE_DEV_GUILD_ID` for guild-scoped command registration. Three follow-ups during review: (1) worker-invented welcome copy violated the "no LLM-generated runtime output" rule — User wrote canonical copy, added to UI-ADR § "Welcome embed copy"; (2) bug in event handler registration (`_on_ready` vs `on_ready` — `client.event` uses `__name__`, leading underscore meant the handler never fired and slash commands never synced) caught during smoke test, fixed in commit `006694f`; (3) User reformatted the welcome copy as a bullet list in commit `87ef94e`, UI-ADR synced. Also added `docs/discord-bot-setup.md` (developer-portal walkthrough with intent/permission table, OAuth scopes, perms integer `2150714432`).

Stage verification: full validation pipeline clean on `main` post-merge (56 tests pass, ruff clean, pyright 0 errors, scan clean) **plus** manual Discord smoke test in dev guild — all four guard cases (wrong-channel, not-in-voice, guard-pass, session-already-active) confirmed by User.

**Task Logs:**
- task-02-01.log.md
- task-02-02.log.md

### Stage 1 — Foundation

Two Tasks delivered the package skeleton, env loader, and the SQLite layer for the session lifecycle. Both ran sequentially on Sonnet `apm-worker` subagents on dedicated `chore/*` branches; both passed the full validation pipeline (`ruff format`, `ruff check`, `pytest`, `pyright`, `scan_injection`) on first review.

T1.1 (`chore/package-scaffolding`, commit `4139ee2`) created `app/__init__.py`, `app/config.py` with strict `DISCORD_BOT_TOKEN` enforcement (raise on missing/empty, no token logging), `teamode.py` entry stub, `requirements.txt` with exact pins (`discord.py[voice]==2.7.1`, `python-dotenv==1.2.2`, `pytest==8.3.5`, `pytest-asyncio==0.26.0`, `ruff==0.11.13`, `pyright==1.1.398`), `.env.example`, and four `tests/test_config.py` cases via `monkeypatch` + `importlib.reload`. The worker's "important finding" about `app/` vs `teamode/` was a false positive — they conflated the repo-root directory name with the package directory.

T1.2 (`chore/sqlite-schema`) needed one follow-up cycle. Initial commit `764f5ff` implemented the schema and ten write helpers correctly per `docs/sqlite-schema.md`, but flagged that the schema doc's `NOT NULL` constraints on `started_at` and `duration_minutes` conflicted with the lifecycle (those columns are unknown at `pending` insert). Worker worked around it with sentinel values (`_now_utc()` and `0`). Manager surfaced the conflict to User; chose Option A — fix the schema doc. Doc correction (`cfa7572`) relaxed both constraints to nullable and expanded the documented `status` enum to include `pending`, `intention_set`, `followup`. Follow-up worker (`b96b0bd`) revised `app/db.py` to omit those columns at INSERT (true NULL), updated tests to assert NULL on insert and non-NULL after the corresponding transitions. Final state: 29 tests covering every helper plus reconciliation (both branches), no sentinel values in the data path.

Stage verification on `main` post-merge: full pipeline clean, 29 tests green.

**Task Logs:**
- task-01-01.log.md
- task-01-02.log.md

