---
title: TeaMode
completed_at: 2026-05-11T12:13:30Z
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:** Complete

**Stage 3:** Complete

**Stage 4:** Complete

**Stage 5:** Complete

**Stage 6:** Complete — V1 tagged as `v26Q2.0.0` and pushed to `origin/main`.

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
- T3.3 scope drift carry-over: the worker added `voice_client.disconnect()` after `mark_followup` (around `app/bot.py:182`). Per Spec § Voice, disconnect should happen *after* `play_reverie_then_disconnect` in T4.1, not before. T4.1 prompt must explicitly remove this premature disconnect and replace with the proper sequence. (Resolved by T4.2 initial implementation.)
- Stage 5 T5.1 scope: User-approved expansion to include manual facilitator handoff command. Command name is **`/handoff @user`** (NOT `/lead @user` — User renamed before dispatch). T5.1 should still also implement the automatic RNG handoff on voice-state-update per the existing Spec. Capture both behaviours in the T5.1 prompt. **(Done — merged via `a81f725`.)**
- T5.1 deferred smoke paths (User direction): only step 1 of the smoke checklist (slash command sync — `/handoff` appears) was confirmed; manual `/handoff` happy path + refusal branches, automatic RNG handoff, and solo-leave passthrough deferred to V1 monitoring. Track these for Stage 6 UAT planning alongside Stage 4's deferred non-facilitator and 3-min-timeout paths.
- Stage 5 close (User direction): full Stage-close smoke bundle deferred to V1 monitoring. Six paths queued for Stage 6 UAT — T5.1 manual `/handoff` happy path, T5.1 manual `/handoff` refusal (any branch), T5.1 auto RNG handoff, T5.2 solo-grace rejoin cancel, T5.2 solo-grace 5-min timeout, T5.4 wifi-drop reconnect tolerance. Combined with the Stage 4 deferrals (non-facilitator reaction logged-only, 3-min followup timeout), Stage 6's UAT covers eight live-Discord paths total.

