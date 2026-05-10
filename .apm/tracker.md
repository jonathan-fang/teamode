---
title: TeaMode
---

# APM Tracker

## Task Tracking

**Stage 1:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 1.1 | Ready | core | |
| 1.2 | Waiting: 1.1 | core | |

## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| teamode | main | `type/short-description` per dispatch unit, off `main`; no force-push to `main` | Conventional Commits `type(scope): description`, 50/72 rule, imperative subject; no Co-Authored-By or AI-attribution trailers; remote push gated on User approval |

## Working Notes

- `.venv/` exists at repo root (Python 3.12.3) — Task 1.1 should `pip install -r requirements.txt` into it rather than recreating.
- `.apm/`, `.claude/`, `.project-meta/`, `.LLMAO/` are intentionally tracked on `main` per `.project-meta/conventions.md` § "Session artifacts on main" — do not gitignore.
- Dispatch mode: foreground only (User has not configured permissions for background subagents).
- Holistic verification points flagged by Planner: end of Stages 2, 3, 4, 5, 6 — assess at each Stage close.

