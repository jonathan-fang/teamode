---
title: TeaMode
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:** Complete

**Stage 3:** Complete

**Stage 4:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 4.1 | Done | core | |
| 4.2 | Active | discord | feat/end-of-session-followup |

## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| teamode | main | `type/short-description` per dispatch unit, off `main`; no force-push to `main` | Conventional Commits `type(scope): description`, 50/72 rule, imperative subject; no Co-Authored-By or AI-attribution trailers; remote push gated on User approval |

## Working Notes

- `.venv/` exists at repo root (Python 3.12.3) — workers should use it via `.venv/bin/python -m pip install -r requirements.txt`, not recreate.
- `.apm/`, `.claude/`, `.project-meta/`, `.LLMAO/` are intentionally tracked on `main` per `.project-meta/conventions.md` § "Session artifacts on main" — do not gitignore.
- Dispatch mode: foreground only (User has not configured permissions for background subagents).
- Holistic verification points flagged by Planner: end of Stages 2, 3, 4, 5, 6 — assess at each Stage close.
- Worker false-positive note: in Task Prompts, name the package as "`app/`" explicitly. The repo root directory is also named `teamode/` on disk (per AGENTS.md tree diagram), and a worker re-reading AGENTS.md may conflate the two.
- T3.3 scope drift carry-over: the worker added `voice_client.disconnect()` after `mark_followup` (around `app/bot.py:182`). Per Spec § Voice, disconnect should happen *after* `play_reverie_then_disconnect` in T4.1, not before. T4.1 prompt must explicitly remove this premature disconnect and replace with the proper sequence.

