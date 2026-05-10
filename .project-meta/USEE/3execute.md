# 3. Execute

Phase 3 of USEE. The active build phase — sessions in flight, what's
landed, what's next. Updated during the APM Implementation Phase.

When TeaMode is in active development, this file is the dashboard. Each
APM session updates the "Currently in flight" section and adds to "What's
landed" once the session closes.

---

## Currently in flight

_None — pre-implementation. APM Manager will populate this once the
Implementation Phase begins._

## What's landed

_Empty — repo is greenfield as of 2026-05-09._

## Next session targets

The Spec / Plan in `.apm/` is authoritative. Strategic sketch from
`2form-strategy.md`:

1. Foundation
2. Slash command + welcome
3. Timer pick + intention modal
4. Countdown loop + voice connect
5. End-of-session + reverie + follow-up
6. Edge cases
7. Cleanup + release

## Validation cadence

Per `.project-meta/conventions.md` and `AGENTS.md`:

- Blocking checks before each commit: `ruff format --check`,
  `ruff check`, `pytest`, `pyright`, `scan_injection.sh .apm`.
- Manual Discord smoke test for any user-visible change. Smoke test
  command included in commit-approval request.
- UAT walkthrough at the end of each stage that delivers user-facing
  functionality, per `.LLMAO/uat-verification.md`.

## Active blockers / external dependencies

_None._

When a blocker appears, list it here with: what it is, why it blocks
progress, who/what is needed to unblock, and the date logged.
