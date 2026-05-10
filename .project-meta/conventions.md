# Project Conventions — TeaMode

Project-specific conventions for TeaMode (Ocha bot). Adopts most of the
patterns from sibling repos `dlqa` and `dawa` while tailoring to
TeaMode's stack: Python 3 + discord.py + asyncio + SQLite.

When a rule is identical to dlqa/dawa, it is restated here so this file
is self-contained — agents read this without needing the sibling repo's
conventions.

---

## Development Philosophy

- Build what's good enough for the use case — don't chase ghosts or
  optimize for hypothetical requirements.
- Either take action or change expectations. If something isn't working,
  fix it or adjust the target.
- Build at the right layer: 1. the project → 2. project meta
  (`AGENTS.md`, conventions, USEE) → 3. the tools that build the project
  (APM, LLMAO).

---

## Naming

**Functions:** verb + object — `start_session`, `end_session`,
`refuse_invocation`, `select_handoff_facilitator`. Name for what it
*does*, not what it *is*.

**Variables/parameters:** `snake_case`. Module-level constants:
`UPPER_CASE`.

**Classes:** `PascalCase`. Mixins: suffix `Mixin`.

**Files/modules:** `snake_case`. Entry point is thin
(`teamode.py`); business logic lives in a separate package
(`teamode/` with `bot.py`, `session.py`, `db.py`, `voice.py`).

**Branches:** `type/short-description` — `feat/follow-up-buttons`,
`fix/voice-reconnect`, `refactor/session-state`.

**Config keys:** `PascalCase` for top-level keys. Reflects structure,
not Python style. (For TeaMode this mostly applies to env-var names —
`DISCORD_BOT_TOKEN`, `TEAMODE_DB_PATH`.)

**Discord `custom_id` namespace:** `teamode:<session_id>:<purpose>[:<value>]`.
See `.project-meta/UI-ADR.md` § "Custom_id namespace."

---

## Architecture

**Separation of concerns:** Discord interaction handlers and the entry
point stay in `teamode.py` (or `teamode/bot.py`). Business logic
(session state machine, SQLite I/O, handoff selection) is importable,
testable, and Discord-agnostic.

**Imports:** Relative imports inside the package
(`from .session import …`). Absolute imports from entry points and tests
(`from teamode.session import …`). No circular imports.

**Async vs sync:** Discord interaction handlers are coroutines. SQLite
writes happen synchronously inside coroutines (sqlite3 is fast for our
write volume; introducing `aiosqlite` is premature). If a write becomes a
bottleneck, revisit then.

**Voice handling:** All voice connection logic lives in `voice.py`. Bot
join/leave, audio playback, reconnect retry — single source of truth.

**Layered escalation (Discord features):**
1. Direct discord.py call — first choice.
2. Raw HTTP via `discord.http` — only when discord.py doesn't expose a
   feature we need.
3. Custom WebSocket / gateway code — never (no current need).

---

## Python Style

- 4-space indentation. Follow the file you're in.
- Type-annotate new functions. `pyright` is a hard gate — zero errors
  before committing.
- No `# type: ignore` shortcuts. Narrow with `isinstance` guards
  instead.
- No `cast()` unless truly unavoidable.
- `ruff format` + `ruff check` clean before every commit.

---

## Testing

- `pytest` is the runner. `pytest-asyncio` for coroutines.
- Test file per module: `test_session.py`, `test_db.py`, `test_voice.py`.
- Test at boundaries (slash command interaction, button click handler,
  SQLite writes). Trust internal code.
- No mocks for SQLite — exercise the real query path with `:memory:`.
- No live Discord gateway in any test.
- Patch with `patch.object(module, "attr", …)` — not attribute
  reassignment — when a module captures a reference at import time.
- Patch where the function is *used*, not where it's defined.
- Use `AsyncMock` for awaitables; `MagicMock` silently breaks async paths.

**Test invariants, not implementations.** A test that asserts
"function X calls Y with Z" mirrors the implementation. A test that
asserts "the side effect Y must occur regardless of internal routing"
captures the contract. The latter survives refactors.

For full discord.py / asyncio testing patterns, see
`.LLMAO/test-patterns.md`.

---

## Version Control

**Commits:** Conventional Commits — `type(scope): description`.
Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`,
`perf`. One feature or one risky operation per commit. No batching
unrelated changes.

**Subject and body formatting (50/72 rule):**
- Subject line: ≤ 50 characters, imperative mood, no trailing period.
- Blank line between subject and body.
- Body lines: hard-wrapped at 72 characters.

**Versioning:** Quarter-prefixed semantic versioning —
`vYYQN.MAJOR.MINOR.PATCH`. The quarter prefix (`vYYQN`, e.g. `v26Q2`)
indicates the release cycle; the trailing three numerics follow SemVer
within that cycle. Matches `dlqa` / `dawa` for repo-family cohesion.

- **Patch** bump (`vYYQN.M.N.P+1`) — bug fixes only.
- **Minor** bump (`vYYQN.M.N+1.0`) — new features, backwards-compatible.
- **Major** bump (`vYYQN.M+1.0.0`) — significant feature wave or
  breaking change within a quarter.
- **Quarter** rollover (`vYY(Q+1).0.0.0`) — at the start of a new
  calendar quarter, reset to `.0.0.0` and increment the prefix.

Trailing zero PATCH may be omitted (`v26Q2.2.0` is shorthand for
`v26Q2.2.0.0`).

**Release type rule:**
- A patch release may not bundle features or refactors that weren't
  already on the branch when the bug was identified. Hotfixes are
  bug-fix-only.
- A minor release may bundle multiple features only if they fit a 1–2
  day APM project target and share no scope.

**Branches:** Feature branch per task off `main`. No force-push to
`main`.

**Session artifacts on `main`:** `.apm/`, `.claude/`, `.project-meta/`,
and `.LLMAO/` are tracked on `main` so APM planning artifacts,
Claude Code configuration, project conventions, LLMAO workflow docs, and
USEE knowledge live in version control. They are not in `.gitignore`. If
a stable-private promotion is added later, remove them from the index
before merging:
```bash
git rm -r --cached .apm/ .claude/ .project-meta/ .LLMAO/
```

**Approval gates:** Explicit approval before any file edit and before
any commit.

---

## Code Hygiene

**YAGNI:** Don't build for hypothetical future requirements. Three
similar lines of code is better than a premature abstraction.

**No speculative abstractions:** Extract when there are three or more
real call sites, not before.

**Dead code:** Remove it. Don't comment it out.

**Error handling:** Only at system boundaries (slash command handlers,
SQLite I/O, voice connection, network calls). Don't add fallbacks for
things that can't fail internally.

**Redundant calculations:** Capture expensive or time-sensitive calls
once at method entry and reuse. Examples: `datetime.now(timezone.utc)`
called once per coroutine entry, not per branch.

**File splitting:** The hard commit limit is 1000 lines per file. When a
file approaches the limit, split it into cohesive units — extract a
group of related functions by shared responsibility into a new module.
Do not cherry-pick a single new feature into its own file while leaving
everything else in place. After any split, update all imports and test
`patch.object` targets to reference the new module location.

**Inline lint suppressions (`# noqa`):** Minimize use. When one is
genuinely needed, always specify the error code (`# noqa: F401`, not
bare `# noqa`) and add a comment explaining why.

**Runtime output:** No AI-generated or LLM-written text in application
output (anything Ocha sends to a Discord channel).

---

## Anti-Pattern Audit

Run an audit at the start of every cleanup stage (before the release
commit) and whenever a module approaches the 1000-line cap.

### What to look for

- **Shotgun surgery** — a single logical operation copy-pasted at
  multiple call sites with minor inconsistencies. Fix: extract a single
  helper.
- **Magic string sentinels** — using a string like `"None"` instead of
  `None`. Fix: use `None` or a dedicated constant.
- **Magic numbers** — raw literals for domain-significant thresholds
  used in 2+ places with no named constant. Fix: one `UPPER_CASE`
  constant at module level.
- **Inline duplication of logic blocks** — the same if/elif chain
  copy-pasted with different threshold values. Fix: extract a helper
  parameterised by the differing values.
- **Primitive obsession on dict shapes** — a dict with a known fixed
  set of string keys constructed at 3+ call sites. Fix: a `TypedDict`
  or `dataclass`.
- **Circular imports** — modules that import each other, worked around
  with deferred imports. Fix: extract shared state into a third module.
- **Long parameter lists on internal functions** — more than 6 params.
  Fix: group related params into a context object.
- **AsyncMock chains in tests** — a test that mounts three levels of
  `AsyncMock.return_value.X` to satisfy library internals signals the
  seam is wrong. Fix: refactor production code so the test exercises a
  smaller surface.

### How to prioritize

1. **Fix before release:** anything already causing or masking a bug.
2. **Log as a TODO:** structural duplication safe today but compounding.
3. **Defer:** pure style issues.

Do not apply YAGNI in reverse — "we'll probably need to fix this later"
is not justification for a premature extraction.

### How to fix

- One commit per anti-pattern fix. Do not bundle with a feature change.
- Label the commit `refactor(scope): description` — it's not a `fix`
  unless the pattern was actively causing a bug.
- After any extraction, run the full validation pipeline.

---

## Documentation

**Agent instructions:** Single authoritative source (`AGENTS.md`).
Entry-point file (`CLAUDE.md`) imports it with `@AGENTS.md`. Never
duplicate across both.

**Changelogs:** Feature-level, user-facing language. No internal task
IDs or framework terminology.

**Comments:** Only where logic isn't self-evident.

**UI reference:** Read `.project-meta/UI-ADR.md` for the current
Discord-surface layout, palettes, identity, and settled decisions. Use
`.LLMAO/ui-decisions-subsection.md` as the template when adding new UI
elements.

**UI-ADR snapshots:** Create a `UI-ADR-YYMMDD.md` snapshot in
`.project-meta/` whenever new UI decisions are finalized in a session.

---

## TeaMode — Project-Specific

**Discord rate-limit hygiene:**
- Edit cycle for the active timer message is **10 seconds**.
- Skip an edit if the previous one is still in flight.
- On `discord.HTTPException` with status 429, exponential backoff with
  a floor of 10s. Do not retry faster than the cycle.

**Custom_id namespace** (load-bearing for multi-session safety):
`teamode:<session_id>:<purpose>[:<value>]`. Always include the session
id so cross-session click delivery cannot corrupt state.

**SQLite write discipline:**
- Write the row at session start (`status = 'active'`).
- Update at every state transition: intention captured, timer ended,
  follow-up answered, follow-up timed out, session crashed/cancelled.
- On bot startup, query for `status = 'active'` rows and mark them
  `crashed` with `ended_at = now()`.

**Voice connection lifecycle:**
- Bot joins voice at session start (timer-pick → intention →
  voice-connect → start countdown).
- Bot stays connected silently through the timer.
- Bot plays `assets/reverie.wav` at zero, then disconnects after a
  short pause.
- On voice connection failure, fall back to a text mention of the
  facilitator. Log the failure to console; do not crash.

**Asset path:** `assets/reverie.wav` — do not hardcode the path inline;
use a `REVERIE_PATH = Path(__file__).parent / "assets" / "reverie.wav"`
constant in the voice module.

**Authorization at the interaction layer:**
- Timer pick / intention modal / follow-up Y/N: facilitator only.
- Unauthorised clicks: ephemeral refusal "Only the facilitator can
  answer."
- Reaction window: anyone in voice channel; reactions are social signal,
  not authoritative.

**Error visibility:** All `discord.HTTPException`,
`discord.ClientException`, and SQLite `OperationalError` paths must log
the cause to console. Don't swallow exceptions silently. If the failure
is user-facing, surface a brief ephemeral message; otherwise log only.

**Environment / deployment:** WSL on the facilitator's laptop for MVP.
Termux is not supported (voice playback path is unverified). VPS
deployment is V2.

---

## LLM Agent Model Selection

When an LLM framework dispatches subagents, assign models by task type
to balance quality and cost:

- **Execution agents** (implement code, write files, run validation):
  use a capable model (e.g. Sonnet). Mistakes here are expensive.
- **Research/exploration agents** (read files, search the codebase,
  gather context): use a cheaper/faster model. Output is advisory.

Always set the model explicitly on each dispatch — do not rely on
inheritance.

**Debug subagents need an execution-class model.** Diagnosis requires
building from concrete signals (grep, blame, runtime traces) and forming
hypotheses only after the evidence pile is large enough. Cheap models
speculate from partial code reading and produce plausible-but-wrong
hypotheses.

### APM agent assignments

- **APM Manager** (coordination, dispatch, review, planning-doc edits):
  Opus or Sonnet.
- **APM Worker** (`apm-worker` subagent — implements code, runs
  validation): Sonnet.
- **APM research/exploration subagents** (Explore agent for codebase
  mapping, debug investigation): Haiku.

---

## Ad-Hoc Session Workflow (LLM-Assisted)

For bug fixes or small features addressed directly in a chat session,
outside of a formal APM project.

**Prompt targeting:** Pin the agent to exact file locations — `In
<file> lines <start>-<end>, look at the <function> function.`

### Session Brief (complete before any planning)

```
## Session Brief
Objective:          [one sentence]
In scope:           [specific files, behaviors, or bugs]
Out of scope:       [what must NOT change]
Constraints:        [implementation rules specific to this session]
Definition of done: [how you know the session is complete]
```

### Steps

1. **Integration check.** Spawn a read-only exploration agent to map
   the relevant code surface. Mandatory for non-trivial changes.
2. **Plan.** State what changes and why. List affected files and
   functions. Include a Potential Pitfalls section.
3. **Cross-check conventions.** Verify the plan does not violate this
   document.
4. **Get explicit approval.** Wait for confirmation before editing.
5. **Execute.** One fix at a time.
6. **Debug escalation (conditional).** If a bug cannot be diagnosed
   within 2 turns, spawn a dedicated debug subagent scoped to
   reproduce and isolate — not fix.
7. **Validation pipeline.** After all edits:
   ```bash
   ruff format teamode/ teamode.py tests/
   .venv/bin/python -m pytest tests/
   ruff check teamode/ teamode.py tests/
   pyright
   ```
8. **Test updates.** If a function signature changed, update tests.
9. **Manual smoke test.** If user-facing Discord behavior changed,
   include a paste-ready launch command and the in-Discord steps.
10. **Commit.** One commit per fix. Conventional Commits format.
11. **Verify against Definition of Done.**

---

## Smoke Test Delivery

When a change affects user-visible Discord behavior, include in the
commit-approval request:

- **Paste-ready launch:**
  ```bash
  cd ~/WSL/github.com/jonathan-fang/teamode && \
  source .venv/bin/activate && python3 teamode.py
  ```
- **In-Discord steps:** which server, which voice channel to join,
  which command to run, what to look for, expected logged-row in
  SQLite (with a paste-ready query).

Reduce friction: every smoke test is either a paste-able command or a
numbered checklist. No ambiguity.

---

## UAT Verification

Automated checks (ruff, pytest, pyright) verify code correctness. UAT
verifies that a feature *works the way the user expected*.

Full UAT procedure: `.LLMAO/uat-verification.md`.

- Run after every Stage or project that delivers user-facing
  functionality.
- Skip for: pure refactors with no behavior change, documentation-only
  changes, test-only additions.

---

## Validation Gate Structure

**Blocking checks** must all pass before a commit is accepted:
1. `ruff format --check` — formatting
2. `ruff check` — linting
3. `pytest` — tests
4. `pyright` — type checking
5. `shellcheck` (if shell scripts) — script linting
6. `shfmt -d` (if shell scripts) — script formatting
7. `.LLMAO/scan_injection.sh .apm` — artifact security

**Warn-only checks** are never blocking gates. None defined for V1.

If a check cannot run reliably in the standard development environment
without side effects, it must not be a blocking gate.

---

## Patch Release Structure

**Feature freeze on the final stage.** The last stage before a release
is documentation and cleanup only — no new features, no optimizations.

**Monitoring section in the backlog.** After a release, not every
observed behavior needs an immediate fix. Maintain a "Monitoring /
Smoke Test" section in the backlog for items to watch over a week of
real usage before deciding whether to act.

**Atomic field renames.** When renaming a config key, env var, or
database column:
- Do the rename in a single commit touching all call sites.
- No compatibility shim unless there are external consumers.
- Update tests, documentation, and migration helpers in the same commit.

---

## Waiting Period for Non-Critical Improvements

When you observe something that *could* be better — a UX friction, a
"would be nicer if" feature, a small inefficiency — log it to
`TODO.md → Notes` and **wait 7 days of real usage** before deciding
whether to act.

Why: most "could be better" observations don't survive a week. Either
the pattern recurs (worth fixing) or it stopped mattering.

Exemptions (fix immediately):
- Bug fixes (incorrect behavior, crash, stuck state).
- Force-majeure-class operational issues.

---

## Backlog & Release Scoping

`TODO.md` has three release-target queues plus two holding sections:

- **Next Patch** (`vYYQN.M.N.P+1`) — bug fixes only.
- **Next Minor** (`vYYQN.M.N+1.0`) — features + fixes for the next
  minor release.
- **Next Major** (`vYYQN.M+1.0.0`) — items requiring a major bump.
- **Future** — valid ideas blocked on an external trigger.
- **Notes** — loose observations. Inbox; nothing lives there
  permanently.

### APM Project Sizing

Each APM project targets **1–2 days** of work. For efforts that would
span 1–2 weeks, split across multiple APM projects.

A feature is **big** if it touches more than 3 source files (excluding
tests, docs, changelog), or spans more than one subsystem (e.g.,
session state + voice + DB).

**Pre-planning:** Calibrate the full workload and split into APM
sessions *before* starting, not mid-project.

---

## APM Session Hygiene

**Extended breaks (> 1 day).** Before any planned interruption longer
than a day:
1. **Bookkeep `.apm/` files.** Commit `.apm/tracker.md` updates and
   any new task logs.
2. **Run a Manager handoff.** Invoke `apm-3-handoff-manager` to
   produce a handoff log.

For breaks under a day, neither is required.

---

## Stage Sequencing

**Breaking bugs → easy wins → high-impact changes → new features →
testing & docs.** This ordering ensures regressions from big changes
are caught early and documentation reflects what actually landed.

---

## Debug Escalation

**Error visibility is a prerequisite for diagnosis.** Before
investigating a runtime bug, confirm that errors are visible. If the
bot swallows crashes silently, fix that first.

**Stop after two turns without root cause.** Spawn a dedicated debug
agent scoped to reproduce, isolate, and return a findings report — not
fix.

**Grep before theorize.** First move is `grep` / `git blame` / `git
log -S` against the symptom string, not theorizing from code reading.

**Read the introducing commit.** When `git blame` identifies the
buggy commit, read its message — it often names the bug.

**Runtime traces beat static analysis** for async and threading bugs.

---

## Error Surface Requirement

External-process and external-service calls must surface failure
information. Anti-pattern:

```python
# Anti-pattern: stderr captured and discarded
result = subprocess.run(["tool", "arg"], capture_output=True)
```

Preferred: surface `result.stderr` in the failure branch. The same
applies to `discord.HTTPException`, SQLite errors, and voice connection
errors — log the cause; never swallow.

---

## Release Process

**Feature freeze:** The final stage before release is cleanup only.

**Pre-release checklist:**
- Update `PLAN.md` (or `.apm/plan.md`) — reflect completed tasks.
- Update `changelog.md` — user-facing, no internal IDs.
- Update `TODO.md` — remove completed, carry forward deferred.
- Update `README.md` — setup, features, status match current code.
- Audit docs — verify accuracy.
- Add tests for features added this cycle.
- Scan for dead code; remove.
- Run `pip-audit -r requirements.txt`; fix all high/critical findings.

**Branch hygiene:** Verify the working tree is clean. Delete merged
feature branches.

**Remote push:**
```bash
git push origin main
git push origin <tag>
```

Push only after the tag is confirmed clean. Never force-push `main`.

---

## Dependency Maintenance

**Pre-release (blocking):** Run `pip-audit` against `requirements.txt`
before every release. Fix all high/critical findings before tagging.

**Monthly cadence (non-blocking):** Run `pip list --outdated` every
month or two. Manually review and bump meaningful packages —
discord.py updates, security patches.

**Pinning:** Pin exact versions in `requirements.txt` (e.g.
`discord.py==2.4.0`, not `discord.py>=2.4`). Upgrades are intentional.
