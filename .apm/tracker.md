---
title: TeaMode v26Q3.0.0.0
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:** Complete

**Stage 3:** Complete

**Stage 4:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 4.1 | Active | bot-engineer | feat/go-again-and-break |
| 4.2 | Waiting: 4.1 | bot-engineer | |

## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| teamode | main | `type/short-description`, `--no-ff` merge, delete after merge, no push | Conventional Commits `type(scope): desc`, 50/72, no attribution trailers |

## Working Notes

- Planned dispatches remaining: 4.1 (active, own smoke), 4.2 (own smoke), 5.1+5.2, 5.3, 6.1.
- 4.1 prompt decisions to surface at smoke: chain-prompt buttons valid only while in-memory chain state exists (cleared when a break or new session starts, or on restart → MSG_SESSION_INACTIVE); chain-prompt buttons disabled (not deleted) when a new session starts or a break starts; Break clicker must be in voice (MSG_NOT_IN_VOICE); no break voice status (option B).
- 6.1 extras: README launcher section + `~/.teamode-secrets` sample; sound credits (no Stretchly mention); voice status only while connected; test-warning cleanup optional.
- User smoke values uncommitted in app/constants.py (2-min button, WRAP_UP 1, NUDGE_MIN 1, SOLO_GRACE 10) — never stage; stash around merges.
- 5.1 and 5.2 dependency-Ready, held for slip priority (Stage 5).
- `.claude/` left untracked (pre-existing state).
