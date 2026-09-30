---
title: TeaMode v26Q3.0.0.0
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:** Complete

**Stage 3:** Complete

**Stage 4:** Complete

**Stage 5:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 5.1 | Ready | bot-engineer | |
| 5.2 | Ready | bot-engineer | |
| 5.3 | Ready | asset-designer | |

**Stage 6:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 6.1 | Waiting: 5.1, 5.2, 5.3 | docs-writer | |

## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| teamode | main | `type/short-description`, `--no-ff` merge, delete after merge, no push | Conventional Commits `type(scope): desc`, 50/72, no attribution trailers |

## Working Notes

- Planned dispatches remaining: 5.1+5.2 batch (Bot Engineer), 5.3 (Asset Designer), 6.1 (Docs Writer).
- Cleanup candidate (6.1/TODO): 5 background coroutines catch asyncio.CancelledError and `return` instead of re-raising (MVP pattern in watchdog/solo grace, copied in expiry/break/go-again timeout).
- 6.1 extras: README launcher section + `~/.teamode-secrets` sample; sound credits (do not mention the source project); voice status only while connected; `/teamode-clear` delete pacing (`CLEAR_DELETE_INTERVAL_SECONDS`) and own-messages-only; ~6–12 "coroutine never awaited" test warnings cleanup optional.
- Postponed-to-production checks recorded in TODO.md § Notes: 4.3 break/streak re-check; `/teamode-clear` no-Manage-Messages refusal.
- User smoke values uncommitted in app/constants.py (lines tagged `# smoke`: 2-min button, WRAP_UP 1, NUDGE_MIN 1, BREAK 1, LONG_BREAK 2, LONG_BREAK_MIN_SESSION 2, GO_AGAIN 30, SOLO_GRACE 10) — never stage; stash around merges; Workers run pytest against `git show HEAD:app/constants.py`.
- `.claude/` left untracked (pre-existing state).
