---
title: TeaMode
---

# APM Memory Index

## Memory Notes

- **`pytest-asyncio` config:** the project uses `pytest-asyncio==0.26.0` without an explicit `asyncio_mode` setting, which emits a deprecation warning every test run. The first task that introduces async tests (T2.1) should add `asyncio_mode = "strict"` to `pyproject.toml` (or `[pytest]` in `pytest.ini`) to silence the warning and pin behavior before the library's default flips.
- **Package vs repo-root naming:** the Python package is `app/`; the repo root directory on disk is also named `teamode/` (visible in `AGENTS.md`'s tree diagram, line 22). When dispatching, refer to the package as "`app/`" explicitly to avoid worker confusion when they re-read `AGENTS.md`. The slash command `/teamode` and entry-point file `teamode.py` are unrelated to either.
- **Test environment dependency:** `app/config.py` raises `RuntimeError` at module import time when `DISCORD_BOT_TOKEN` is unset. The whole test suite depends on `tests/conftest.py` calling `os.environ.setdefault("DISCORD_BOT_TOKEN", "test-stub-token")` before any `app.*` import. New test modules inherit this for free; running tests outside pytest (e.g. ad-hoc `python -c "from app import session"`) needs the env var set manually. If this brittleness bites again, a factory pattern (`Config.load()`) is the right refactor — punt until then.
- **discord.py event registration gotcha:** `Client.event(func)` uses `func.__name__` to determine which Discord event the handler responds to. Method names with leading underscores (e.g. `_on_ready`) silently fail to register because no event by that name exists. Always name event handlers with the public `on_<event>` form. Caught the hard way during T2.2 smoke test. Also documented in `docs/discordpy-api/gotchas.md` for visibility next to the offline API reference.

## Stage Summaries

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

