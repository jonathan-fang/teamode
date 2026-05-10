# LLMAO — TeaMode

LLMAO (Large Language Model Agent Orchestration) is the workflow layer that
wraps APM with phases APM doesn't cover: research before planning,
verification after implementation, UI contracts, feasibility spikes, and
artifact security.

These files are reference documents you point an agent at when the situation
calls for them. They are not skills or commands.

For the end-to-end walkthrough, read `USER-GUIDE.md`.

## Files

| File | Purpose |
|---|---|
| `USER-GUIDE.md` | End-to-end workflow walkthrough; relationship to APM and USEE |
| `pre-plan-research.md` | Parallel research before APM planning |
| `spike-sketch.md` | Throwaway experiment workflow before committing to an approach |
| `ui-decisions-subsection.md` | Discord UI contract template for Implementation Plans |
| `test-patterns.md` | discord.py / asyncio testing patterns for TeaMode |
| `uat-verification.md` | Interactive post-implementation walkthrough |
| `scan_injection.sh` | Prompt injection pattern scanner (validation check) |
