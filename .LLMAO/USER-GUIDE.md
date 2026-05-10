# LLMAO User Guide — TeaMode

**LLMAO** (Large Language Model Agent Orchestration) is the workflow layer
that sits around APM. It covers the phases APM doesn't — research before
planning, verification after implementation, UI contracts, feasibility
spikes, and artifact security. These are not skills or commands. They are
reference documents you point an agent at when the situation calls for them.

This guide describes the end-to-end workflow from problem to shipped code,
showing where each LLMAO document fits relative to APM's Planner → Manager →
Worker pipeline.

---

## End-to-End Walkthrough

### The full cycle

```
 Problem
   │
   ▼
 [SPIKE]  ─── uncertain? ──→  spike-sketch.md (worktree experiment)
   │                              │
   │◄─────── verdict ────────────┘
   ▼
 [RESEARCH]  ─── unfamiliar? ──→  pre-plan-research.md (parallel Explore agents)
   │                                  │
   │◄─────── findings ───────────────┘
   ▼
 APM PLANNER  ─── plan.md
   │               ├── references research findings
   │               ├── includes UI Decisions subsection (ui-decisions-subsection.md)
   │               └── includes deliverables for UAT
   ▼
 APM MANAGER  ─── dispatches workers per stage
   │
   ▼
 APM WORKER(S)  ─── implement, test, report
   │
   ▼
 VALIDATION  ─── blocking checks (AGENTS.md)
   │               ├── ruff format
   │               ├── ruff check
   │               ├── pytest
   │               ├── pyright
   │               └── scan_injection.sh  ◄── artifact security
   ▼
 [UAT]  ─── uat-verification.md (interactive walkthrough)
   │          ├── extract deliverables from plan
   │          ├── walk through one-by-one
   │          ├── diagnose failures → debug agent
   │          └── record PASS / FAIL / DEFERRED
   ▼
 COMMIT + SHIP
```

### What's optional

Not every task needs every phase. Most bug fixes go straight to APM
planning. The decision tree:

| Question | If yes | If no |
|----------|--------|-------|
| Am I unsure if this approach is feasible? | Run a **spike** | Skip to research or planning |
| Am I working with unfamiliar Discord API surface? | Run **pre-plan research** | Skip to planning |
| Does the task touch user-visible Discord components (slash command shape, embeds, buttons, modals)? | Include **UI Decisions** subsection in plan | Normal plan |
| Does the task deliver user-facing functionality? | Run **UAT** after implementation | Commit after validation checks pass |

---

## Phase 1: Spike (Optional)

**When:** You don't know if the approach will work.

**Document:** `spike-sketch.md`

**TeaMode example:**
```
Hypothesis: discord.py can edit a single message every 10s for a 50-minute
            session without hitting per-route rate limits
Verdict:    PARTIAL — edits succeed, but a 429 surfaces under abuse;
            production cadence of 10s with backoff is safe
Carry forward: Plan should include exponential backoff on edit failures
```

---

## Phase 2: Pre-Plan Research (Optional)

**When:** The task involves unfamiliar territory — a Discord API surface
you haven't used (e.g. modals, voice playback, application emoji), an
architectural question with multiple viable answers.

**Document:** `pre-plan-research.md`

**Cost:** Token-intensive. Skip for tasks in well-understood code.

**Output:** A research summary the Planner reads before proposing phases.
Prevents plans that hit dead ends.

---

## Phase 3: APM Planning

**Document:** APM's own `apm-1-initiate-planner` skill.

**What LLMAO adds:** If the task touches user-visible Discord surface, the
Implementation Plan must include a **UI Decisions** subsection.

**Document:** `ui-decisions-subsection.md`

**What the subsection locks down:**
- Where the element appears (text channel, embed, modal, button row)
- Exact display text and empty states
- Interaction model (button labels, custom_id namespace, ephemeral flag)
- Colors, emoji, embed accents — inherit from `.project-meta/UI-ADR.md` or override
- Mobile rendering considerations (Discord mobile clip embed widths)

**Why:** Without this, the worker agent makes visual judgment calls. Those
calls are often wrong. Locking decisions before implementation eliminates
"that's not what I wanted" rework.

---

## Phase 4: APM Execution

Standard APM flow: Manager dispatches Workers, Workers implement and report,
Manager reviews. No LLMAO additions at this phase.

---

## Phase 5: Validation

**Document:** `AGENTS.md`, Validation Protocol section.

Blocking checks must pass before commit approval:

| # | Check | What it catches |
|---|-------|-----------------|
| 1 | `ruff format --check` | Formatting violations |
| 2 | `ruff check` | Lint errors, unused imports |
| 3 | `pytest` | Logic regressions |
| 4 | `pyright` | Type mismatches |
| 5 | `shellcheck` (if scripts) | Shell script errors |
| 6 | `shfmt` (if scripts) | Shell formatting |
| 7 | `scan_injection.sh .apm` | Prompt injection in artifacts |

Check #7 is the security layer. It scans `.apm/` markdown, YAML, and JSON
artifacts for known injection patterns. False positives are possible in
documentation *about* injection — review manually.

**Script:** `scan_injection.sh`

---

## Phase 6: UAT (Post-Implementation)

**When:** The task delivered user-facing functionality.

**Document:** `uat-verification.md`

**TeaMode UAT example:**

```
[1/3] Run /teamode in a voice-channel text chat — does the timer-pick
      button row appear and respect the in-voice-channel guard?

      Smoke test:
      cd ~/WSL/github.com/jonathan-fang/teamode && \
      source .venv/bin/activate && python3 teamode.py

      Expected: Bot posts welcome embed; if you're not in voice, refuses
      with "join a voice channel first."

      → PASS / FAIL / DEFERRED?
```

```
[2/3] Run a 10-minute session and confirm reverie.wav plays at zero in
      the voice channel.

      → PASS / FAIL / DEFERRED?
```

```
[3/3] Run two /teamode invocations in the same text channel back-to-back
      while one is active — does the second receive the friendly refusal?

      → PASS / FAIL / DEFERRED?
```

---

## Quick Reference

### File Index

| File | Purpose | When to use |
|------|---------|-------------|
| `pre-plan-research.md` | Parallel research before APM planning | Unfamiliar Discord surface or architectural questions |
| `uat-verification.md` | Interactive post-implementation walkthrough | After any user-facing feature lands |
| `ui-decisions-subsection.md` | Discord UI contract template for Implementation Plans | Any task touching command shape, embeds, buttons, modals |
| `spike-sketch.md` | Throwaway experiment workflow | Uncertain feasibility before committing to an approach |
| `test-patterns.md` | discord.py / asyncio testing patterns | Writing or reviewing tests in this repo |
| `scan_injection.sh` | Prompt injection pattern scanner | Runs as a validation check on every commit |

### How to reference these in a session

Point the agent at the document by path:

> "Before planning, follow the research protocol in `.LLMAO/pre-plan-research.md`."

> "This task touches user-visible Discord surface. Include a UI Decisions subsection per `.LLMAO/ui-decisions-subsection.md`."

> "After implementation, run UAT per `.LLMAO/uat-verification.md`."

> "I'm not sure this will work. Run a spike per `.LLMAO/spike-sketch.md` first."

### Relationship to APM

LLMAO does not replace APM. It wraps APM with phases that APM doesn't cover:

```
LLMAO: spike → research →
                           APM: plan → execute →
                                                  LLMAO: validate (scan_injection) → UAT
```

APM handles the core planning and execution loop. LLMAO handles everything
before and after.

### Relationship to USEE

USEE (Understand, Strategize, Execute, Evaluate) is the project knowledge
framework — the *what* and *why* of TeaMode. LLMAO is the development
workflow framework — the *how* of building it. They're complementary:

| Framework | Scope | Files |
|-----------|-------|-------|
| **USEE** | Project knowledge and strategy | `.project-meta/USEE/1understand-criteria.md`, `2form-strategy.md`, `3execute.md`, `4evaluate.md` |
| **LLMAO** | Development workflow and agent coordination | `.LLMAO/` |
| **APM** | Structured implementation pipeline | `.apm/` |

---

## Design Principles

These principles shaped the workflow. They explain *why* it works this way,
not just *what* to do.

**Research prevents dead ends.** One pre-plan research session costs tokens
but saves multiple failed implementation cycles. The tradeoff is worth it
for unfamiliar territory, not for routine work.

**Lock UI decisions before implementation.** Agent judgment on visual design
is unreliable. A 5-minute decision table before implementation prevents 30
minutes of rework after.

**Tests pass ≠ feature works.** Automated validation catches code errors.
UAT catches "the code is correct but the feature is wrong." Both layers
are necessary; neither is sufficient alone.

**Spikes are disposable; verdicts are not.** The throwaway code doesn't
matter. The finding — "this works," "this doesn't work," "this works with
caveats" — shapes every downstream decision.

**Security is a scan, not a ceremony.** A grep-based injection check in the
validation pipeline catches the obvious cases with zero workflow friction.
It's a minimum safety net for markdown artifacts that become agent prompts.
