---
title: TeaMode
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:** Complete

**Stage 3:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 3.1 | Active | core | feat/voice-plumbing |
| 3.2 | Active | discord | feat/timer-intention |
| 3.3 | Waiting: 3.1, 3.2 | discord | |

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

