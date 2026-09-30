---
title: TeaMode v26Q3.0.0.0
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 2.1 | Active | bot-engineer | feat/startup-ops-and-rate-limits |
| 2.2 | Active | bot-engineer | feat/startup-ops-and-rate-limits |
| 2.3 | Waiting: 2.2 | bot-engineer | |
| 2.4 | Waiting: 2.3 | bot-engineer | |

## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| teamode | main | `type/short-description`, `--no-ff` merge, delete after merge, no push | Conventional Commits `type(scope): desc`, 50/72, no attribution trailers |

## Working Notes

- Planned batches remaining: 2.1+2.2 (active), 2.3+2.4, 3.1, 3.2, 4.1, 4.2, 5.1+5.2, 5.3, 6.1.
- Stage 2 end (after 2.4): User Discord smoke pass — pending expiry, 4th-invocation rate limit, full 5-min session with cleanup + Time's up deletion, timer mentions, PID lock with a second instance.
- 5.1 becomes Ready once 2.1 is Done; 5.2 already Ready (dep 1.3) — both held for slip priority (Stage 5).
- `.claude/` left untracked (pre-existing state).
