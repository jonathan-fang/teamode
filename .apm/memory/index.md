---
title: TeaMode
---

# APM Memory Index

## Memory Notes

- **`pytest-asyncio` config:** the project uses `pytest-asyncio==0.26.0` without an explicit `asyncio_mode` setting, which emits a deprecation warning every test run. The first task that introduces async tests (T2.1) should add `asyncio_mode = "strict"` to `pyproject.toml` (or `[pytest]` in `pytest.ini`) to silence the warning and pin behavior before the library's default flips.
- **Package vs repo-root naming:** the Python package is `app/`; the repo root directory on disk is also named `teamode/` (visible in `AGENTS.md`'s tree diagram, line 22). When dispatching, refer to the package as "`app/`" explicitly to avoid worker confusion when they re-read `AGENTS.md`. The slash command `/teamode` and entry-point file `teamode.py` are unrelated to either.

## Stage Summaries

### Stage 1 — Foundation

Two Tasks delivered the package skeleton, env loader, and the SQLite layer for the session lifecycle. Both ran sequentially on Sonnet `apm-worker` subagents on dedicated `chore/*` branches; both passed the full validation pipeline (`ruff format`, `ruff check`, `pytest`, `pyright`, `scan_injection`) on first review.

T1.1 (`chore/package-scaffolding`, commit `4139ee2`) created `app/__init__.py`, `app/config.py` with strict `DISCORD_BOT_TOKEN` enforcement (raise on missing/empty, no token logging), `teamode.py` entry stub, `requirements.txt` with exact pins (`discord.py[voice]==2.7.1`, `python-dotenv==1.2.2`, `pytest==8.3.5`, `pytest-asyncio==0.26.0`, `ruff==0.11.13`, `pyright==1.1.398`), `.env.example`, and four `tests/test_config.py` cases via `monkeypatch` + `importlib.reload`. The worker's "important finding" about `app/` vs `teamode/` was a false positive — they conflated the repo-root directory name with the package directory.

T1.2 (`chore/sqlite-schema`) needed one follow-up cycle. Initial commit `764f5ff` implemented the schema and ten write helpers correctly per `docs/sqlite-schema.md`, but flagged that the schema doc's `NOT NULL` constraints on `started_at` and `duration_minutes` conflicted with the lifecycle (those columns are unknown at `pending` insert). Worker worked around it with sentinel values (`_now_utc()` and `0`). Manager surfaced the conflict to User; chose Option A — fix the schema doc. Doc correction (`cfa7572`) relaxed both constraints to nullable and expanded the documented `status` enum to include `pending`, `intention_set`, `followup`. Follow-up worker (`b96b0bd`) revised `app/db.py` to omit those columns at INSERT (true NULL), updated tests to assert NULL on insert and non-NULL after the corresponding transitions. Final state: 29 tests covering every helper plus reconciliation (both branches), no sentinel values in the data path.

Stage verification on `main` post-merge: full pipeline clean, 29 tests green.

**Task Logs:**
- task-01-01.log.md
- task-01-02.log.md

