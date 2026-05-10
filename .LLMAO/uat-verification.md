# UAT / Verification Phase

## What This Is

A structured user acceptance walkthrough run **after** APM implementation completes. Automated checks (pytest, ruff, pyright) verify code correctness. UAT verifies that the feature *works the way you expected*.

This bridges the gap between "tests pass" and "I can actually use this."

## When to Use

- After every APM stage or project that delivers user-facing functionality
- After any change to slash command shape, embeds, button rows, modals, or voice playback
- Before any release tag

**Skip for:** Pure refactors with no behavior change, documentation-only changes, or test-only additions.

## How to Run

### 1. Extract testable deliverables

Read the APM Implementation Plan (`.apm/plan.md`) and extract what the user should now be able to do. Each deliverable is a concrete, verifiable action — not a code change.

**Good deliverables:**
- "Run `/teamode` from a voice-channel text chat and see the welcome embed with timer-pick buttons"
- "Run a 10-minute session end-to-end and confirm reverie.wav plays in voice at zero"
- "Invoke `/teamode` twice in the same channel and confirm the second invocation receives the friendly refusal"

**Bad deliverables:**
- "session.py has a new function" (code-level, not user-level)
- "Tests pass" (already covered by automated checks)

### 2. Walk through one at a time

Present each deliverable as a numbered question:

```
[1/4] Can you run `/teamode` from a voice-channel text chat and see the welcome embed?

      Smoke test: cd ~/WSL/github.com/jonathan-fang/teamode && source .venv/bin/activate && python3 teamode.py

      In Discord: join a voice channel, then run `/teamode` in that voice channel's text chat.
      Expected: matcha-sage embed posts with timer-pick button row (10 / 25 / 50).
```

Wait for the user's response before proceeding to the next item.

### 3. Record results

For each deliverable, record: PASS, FAIL + description, or DEFERRED + reason.

```markdown
## UAT Results — [Phase/Stage Name]

| # | Deliverable | Result | Notes |
|---|-------------|--------|-------|
| 1 | Welcome embed posts on `/teamode` | PASS | |
| 2 | Reverie plays in voice at zero | FAIL | Voice connection times out before playback |
| 3 | Same-channel concurrent invocation refused | PASS | |
```

### 4. Diagnose failures

For each FAIL:

1. Spawn a debug agent with the failure description and relevant file paths
2. The agent investigates root cause and proposes a fix
3. Present the fix for approval
4. Apply the fix and re-run the specific UAT item

Do not re-run the entire UAT — only the failed items.

### 5. Cross-environment UAT (when applicable)

For changes that need verification beyond the facilitator's primary
server (e.g. V2 distribution, hosting migration to VPS):

```
Cross-environment UAT:
1. git fetch && git checkout <branch> && git pull
2. pip install -r requirements.txt  (if deps changed)
3. DISCORD_BOT_TOKEN=... python3 teamode.py
4. In Discord: [specific steps in target server]
5. Expected: [specific behavior]
6. Report: PASS / FAIL + description
```

## UAT Document Template

Save results to `.apm/uat-[stage].md` or include in the stage completion report:

```markdown
# UAT — [Stage/Phase Name]

**Date:** YYYY-MM-DD
**Branch:** feature/xyz
**Automated checks:** All passing

## Deliverables

| # | Deliverable | Smoke test | Expected | Result |
|---|-------------|------------|----------|--------|
| 1 | ... | `python3 teamode.py` then `/teamode` in voice | ... | PASS |
| 2 | ... | run a 10-min session end-to-end | ... | FAIL |

## Failures

### [2] Reverie plays at zero
**Observed:** Voice client connects, but playback never fires
**Root cause:** `FFmpegPCMAudio` source path resolved before chdir
**Fix:** [description or link to fix commit]
**Re-test:** PASS after fix

## Environment UAT

- WSL (facilitator's laptop): PASS
- Second server (V2): N/A
```

## Relationship to Existing Checks

| Layer | What it catches | Tool |
|-------|----------------|------|
| Formatting | Style violations | `ruff format` |
| Linting | Code smells, unused imports | `ruff check` |
| Type safety | Type mismatches | `pyright` |
| Unit tests | Logic regressions | `pytest` |
| Shell checks (if scripts) | Script errors | `shellcheck`, `shfmt` |
| **UAT** | **Feature doesn't work as intended** | **This document** |
| Injection scan | Prompt injection in artifacts | `scan_injection.sh` |

UAT is the only layer that catches "code is correct but feature is wrong."
