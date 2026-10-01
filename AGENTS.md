# Repository Guidelines

## What This Project Is

**TeaMode** is a self-hosted Discord bot that runs FLOWN/Groove-style
guided co-working sessions in voice channels. The bot user is named
**Ocha**. Stack: Python 3 + discord.py + asyncio + SQLite. Runs on WSL
(MVP); VPS for V2 distribution.

The single command is `/teamode`, invoked from the text chat attached
to a voice channel. The bot walks the facilitator through duration
pick → intention → countdown → reverie ring → follow-up.

**When picking up work in a new session, read these files first:**
- `.project-meta/USEE/3execute.md` — current status, what's done, what's next
- `TODO.md` — actionable backlog (created at first APM project)
- `.project-meta/conventions.md` — project conventions reference

## Project Structure & Module Organization

```
teamode/                      ← repo root
├── teamode.py                ← entry point (thin): PID lock, ffmpeg probe, startup order
├── app/                      ← package
│   ├── __init__.py
│   ├── discord_bot/          ← Discord wiring only (mixins composed in client.py)
│   │   ├── client.py         ← discord.Client + CommandTree + event handlers
│   │   ├── commands.py       ← /teamode and /handoff registration + handlers
│   │   ├── views.py          ← buttons, modal, welcome/timer embeds
│   │   ├── timer.py          ← active timer edit loop
│   │   ├── lifecycle.py      ← end-of-session, Reflect, solo grace, message cleanup
│   │   ├── breaks.py         ← chaining and break flow
│   │   ├── clear.py          ← /teamode-clear
│   │   ├── stats.py          ← /teamode-stats
│   │   └── tasks.py          ← background-task helpers
│   ├── constants.py          ← every tunable + every Discord-facing string
│   ├── config.py             ← env var loading (no discord import)
│   ├── session.py            ← session state machine (Discord-free)
│   ├── voice.py              ← voice connect/play/disconnect
│   ├── db.py                 ← SQLite schema + writes
│   ├── rate_limit.py         ← per-user/per-guild rate limiting
│   ├── timer_format.py       ← mm:ss / progress-bar formatting
│   ├── stats.py              ← stats aggregation (windows, streak, rate)
│   ├── cleanup.py            ← /teamode-clear message classification
│   └── pidlock.py            ← single-instance PID lock
├── assets/
│   ├── reverie.wav           ← end-of-session chime
│   └── wind-chime.wav        ← wrap-up nudge chime
├── scripts/
│   ├── teamode_launcher.sh   ← sources ~/.teamode-secrets, dev/stable modes
│   └── generate_art.py       ← dev-only art candidate generator (Pillow)
├── tests/                    ← pytest suite
├── docs/                     ← Discord platform notes, schema, comparisons
├── requirements.txt          ← pinned runtime dependencies
├── requirements-dev.txt      ← dev-only deps (Pillow, for generate_art.py)
├── .project-meta/            ← conventions, UI-ADR, project-meta artifacts
├── .LLMAO/                   ← LLMAO workflow docs
├── .project-meta/USEE/       ← USEE knowledge framework (under project-meta)
└── .apm/                     ← APM session artifacts
```

APM session artifacts live under `.apm/` and should not be treated as
product source.

### Architecture

**`teamode.py`** — entry-point. Acquires the PID lock, probes for
`ffmpeg` (warns, non-fatal, if missing), loads env vars
(`DISCORD_BOT_TOKEN`, `TEAMODE_DB_PATH`), initializes the database and
reconciles crashed sessions, constructs the bot, runs the event loop.
Imports all logic from `app.discord_bot`.

**`app/discord_bot/`** — Discord-facing layer, split into mixins
composed onto one bot class in `client.py`: `CommandsMixin`
(`/teamode`, `/handoff`), `ViewsMixin` (buttons, modal, welcome/timer
embeds), `TimerMixin` (the active-timer edit loop), `LifecycleMixin`
(end-of-session, Reflect, solo grace, message cleanup),
`BreakMixin` (chaining and breaks), `ClearMixin` (`/teamode-clear`),
`StatsMixin` (`/teamode-stats`). `client.py` owns the `discord.Client`,
the `CommandTree`, and the `on_<event>` handlers (`on_ready`,
`on_interaction`, `on_raw_reaction_add`, `on_voice_state_update`).
`on_ready` syncs slash commands per guild in `TEAMODE_DEV_GUILD_ID`;
if that env var is unset, registration is skipped entirely with a
warning (no global-registration fallback).

**`app/constants.py`** — every tunable number and every Discord-facing
string, as named constants. Pure data: no `discord` or `app.config`
imports, so it is readable and testable in isolation.

**`app/config.py`** — env var loading (`DISCORD_BOT_TOKEN`,
`TEAMODE_DB_PATH`, `TEAMODE_DEV_GUILD_ID`, `TEAMODE_TIMEZONE`), with
IANA timezone resolution and fallback to UTC if even the default is
unavailable.

**`app/session.py`** — Session state machine. Pure logic, no
discord.py imports beyond `Interaction` typing. State transitions:
`pending` → `intention_set` → `active` → `followup` → terminal
(`completed` / `followup_timeout` / `cancelled` / `crashed`). Imported
by tests directly without a live bot.

**`app/voice.py`** — Voice connect, `FFmpegPCMAudio` playback of
`assets/reverie.wav` / `assets/wind-chime.wav`, disconnect. Single
source of truth for voice.

**`app/db.py`** — SQLite schema, connection, write helpers, and the
stats read helpers (`fetch_user_stats_rows`,
`fetch_guild_stats_rows`). See `docs/sqlite-schema.md` for the schema
reference.

**`app/rate_limit.py`**, **`app/timer_format.py`**, **`app/stats.py`**,
**`app/cleanup.py`**, **`app/pidlock.py`** — flat, Discord-free,
injectable-clock modules backing rate limiting, timer text formatting,
`/teamode-stats` aggregation, `/teamode-clear` message classification,
and the single-instance PID lock, respectively.

### Data Stores

| Store | Format | Location | Purpose |
|---|---|---|---|
| `sessions` table | SQLite | `$TEAMODE_DB_PATH` (default `./sessions.db`) | One row per `/teamode` invocation. Updated at every state transition. |

## Key Files

| File | Purpose |
|---|---|
| `teamode.py` | Entry point — `python3 teamode.py` |
| `app/discord_bot/client.py` | discord.Client, CommandTree, event handlers, mixin composition |
| `app/discord_bot/commands.py` | `/teamode` and `/handoff` registration + handlers |
| `app/discord_bot/views.py` | Buttons, modal, welcome/timer embeds |
| `app/discord_bot/timer.py` | Active timer edit loop |
| `app/discord_bot/lifecycle.py` | End-of-session, Reflect, solo grace, message cleanup |
| `app/discord_bot/breaks.py` | Chaining and break flow |
| `app/discord_bot/clear.py` | `/teamode-clear` |
| `app/discord_bot/stats.py` | `/teamode-stats` |
| `app/constants.py` | Every tunable + every Discord-facing string |
| `app/config.py` | Env var loading |
| `app/session.py` | Session state machine (testable without Discord) |
| `app/voice.py` | Voice connection + reverie/wind-chime playback |
| `app/db.py` | SQLite schema, writes, and stats read helpers |
| `app/pidlock.py` | Single-instance PID lock |
| `assets/reverie.wav` | End-of-session chime |
| `assets/wind-chime.wav` | Wrap-up nudge chime |
| `scripts/teamode_launcher.sh` | Local launcher (dev/stable modes) |
| `scripts/generate_art.py` | Dev-only art candidate generator |
| `docs/discord-platform-notes.md` | Discord API reference for slash, components, voice |
| `docs/sqlite-schema.md` | Field-by-field schema reference with citations |
| `docs/language-library-comparison.md` | Why discord.py; hosting tradeoffs |
| `docs/windows-shortcut.md` | Windows Terminal desktop shortcut for the launcher |
| `.project-meta/conventions.md` | All coding standards |
| `.project-meta/UI-ADR.md` | Discord-surface palette, identity, settled UI decisions |
| `.LLMAO/USER-GUIDE.md` | LLMAO workflow walkthrough |
| `.project-meta/USEE/1understand-criteria.md` | What TeaMode is, success criteria |
| `.project-meta/USEE/3execute.md` | Current status |

## Build, Test, and Development Commands

Create or activate the local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the bot:

```bash
DISCORD_BOT_TOKEN=... python3 teamode.py
```

Run the automated suite:

```bash
.venv/bin/python -m pytest tests/ -v
```

### Dependencies

- `discord.py[voice]` — Discord client + voice extras (PyNaCl + Opus)
- `python-dotenv` — env var loading from `.env` for dev convenience
- Standard library: `sqlite3`, `asyncio`, `pathlib`, `datetime`, `random`

System requirements: `ffmpeg` on PATH for voice playback.

### Read Efficiency

Use `offset` and `limit` parameters to read only the sections you need.
Avoid re-reading entire files when you only need a few lines.

Before editing any file, read it first. Before modifying a function,
grep for all callers. Research before you edit.

## Coding Style & Naming Conventions

See `.project-meta/conventions.md` for the full project conventions
reference (naming, architecture, testing, version control, TeaMode
specifics). All coding standards live there — do not duplicate them
here.

## Testing Guidelines

See `.project-meta/conventions.md` §Testing for test runner, patching
conventions, and smoke test rules. See `.LLMAO/test-patterns.md` for
discord.py and asyncio testing patterns.

## Commit & Pull Request Guidelines

See `.project-meta/conventions.md` §Version Control for commit format,
versioning, and branch rules. PRs should include a brief description,
test results, and Discord screenshots when user-visible behavior
changes.

## Approval Gates

Always ask for explicit user approval before making any code or
documentation edit, not just before commits or high-risk operations.
Propose the intended change first, wait for confirmation, then edit.
Keep this rule in force even for repository docs, `.apm/` planning
artifacts, and small refactors.

Exception: during APM Task execution, the checkpoint rules in
APM_RULES › Approval Workflow apply instead.

## Configuration & Platform Notes

Do not hardcode local paths or tokens. Read `DISCORD_BOT_TOKEN`,
`TEAMODE_DB_PATH`, `TEAMODE_DEV_GUILD_ID`, and `TEAMODE_TIMEZONE` from
environment. Do not check `.env` files into git.

### Bot identity

- Application name (Discord developer portal): `TeaMode`
- Bot user display name: `Ocha`
- Slash command: `/teamode`

### Hosting

| Environment | Status |
|---|---|
| WSL (facilitator's laptop) | Supported (MVP) |
| Linux VPS | Planned (V2) |
| Termux (Android) | Not supported — voice playback path unverified |

## APM Chat Shorthand

For chats in this repo, use these plain-text shortcuts to refer to
APM skills:

- `apm planner` → `apm-1-initiate-planner`
- `apm manager` → `apm-2-initiate-manager`
- `apm handoff manager` → `apm-3-handoff-manager`
- `apm summarize` → `apm-4-summarize-session`
- `apm recover` → `apm-5-recover`

`apm-communication` is a support skill, not a direct user command.

## Working Preferences

- The MVP worked best with agents running one at a time. Parallel
  worktrees cost about 75k extra tokens.
- The user approves in short replies like "y" and "1y 2y".
- The user tends to add TODO entries freely.

---

# APM Automatic Handoff

Context usage is tracked automatically. When you reach 70% context
usage, you will receive instructions to perform a Handoff. Follow those
instructions when they appear — do not worry about monitoring context
yourself.

---

APM_RULES {

## Approval Workflow

- For APM Task execution in this project, the User approved
  checkpoint-based approval. This replaces the per-edit rule in
  § Approval Gates above and the "wait for plan approval" rule in the
  User's global instructions: a Task Prompt from the Manager is the
  approved plan, so implement it without asking before each edit.
- Stop and return Partial (never proceed past these) when the Task
  reaches a User checkpoint:
  - a manual Discord smoke test,
  - review of generated art assets,
  - any Discord-facing string that is not already defined in
    `app/constants.py` or given in the Task Prompt,
  - any decision the Task Prompt marks as the User's.
- Workers commit freely on their assigned feature branch (local and
  reversible). The Manager obtains explicit User approval before each
  merge into `main` — presenting the commits and changed files, then
  waiting. Tags and pushes always need explicit User approval.
- Outside APM Task execution (ad-hoc chats), § Approval Gates above
  applies unchanged.

## Version Control

- Base branch: `main`. One `type/short-description` feature branch per
  dispatch unit (e.g. `refactor/discord-bot-package`); the Manager
  creates branches and merges with `--no-ff`, then deletes the branch.
  Nothing is pushed to `origin`.
- Commits: Conventional Commits `type(scope): description` (types
  feat, fix, refactor, docs, test, chore, style, perf), 50/72 rule
  (subject ≤ 50 chars, imperative, no period; body wrapped at 72).
  One logical change per commit; commit at intermediate points on
  large work.
- Stage files explicitly by path (`git add <path>`); never
  `git add -A` / `git add .` — the working tree may hold uncommitted
  `.apm/`, `AGENTS.md` or User edits that are not yours to commit.
- `.apm/` and `.claude/` are tracked per convention; the Manager
  commits APM artifacts, Workers do not stage them (Task Logs are
  written to disk only).

## Validation Protocol

- For all code changes, run the full validation pipeline. Blocking
  checks must pass clean before reporting a Task complete or
  requesting commit approval:
  1. `ruff format --check app/ teamode.py tests/`
  2. `ruff check app/ teamode.py tests/`
  3. `.venv/bin/python -m pytest tests/`
  4. `pyright` (bare, no flags — configured in `pyproject.toml`)
  5. `.LLMAO/scan_injection.sh .apm`
- Any blocking-check failure halts completion. Zero-error target —
  fix root causes rather than bypassing (no disabling rules, no
  skipped tests).
- For changes affecting user-visible Discord behavior (slash command
  shape, embeds, button rows, modals, message deletion, voice playback,
  voice channel status): flag the change as requiring a manual Discord
  smoke test and note it explicitly in the completion report.

## Smoke Test Delivery

- When a Task's completion requires user-facing verification, include
  in the completion report:
  - **Paste-ready launch:**
    ```bash
    cd ~/WSL/github.com/jonathan-fang/teamode && \
    source .venv/bin/activate && python3 teamode.py
    ```
    If the change lives in a git worktree, the `cd` points to the
    worktree path.
  - **In-Discord steps:** which server, which voice channel, which
    command, expected behavior, expected SQLite row state with a
    paste-ready query, e.g.
    `sqlite3 sessions.db "SELECT id,status,duration_minutes,started_at,ended_at FROM sessions ORDER BY id DESC LIMIT 5;"`
  - If a step needs a temporarily lowered constant (long timeouts),
    give the exact edit in `app/constants.py` and an explicit reminder
    to revert it afterwards.
- Reduce friction: every smoke test is either a single paste-able
  command or a numbered checklist. No ambiguity.

## User Collaboration

- When a Task requires user-provided input (Discord token, server
  access or permissions, asset review, judgment-call approval), return
  Partial with a specific request rather than blocking.
- Requests must be concrete: exact commands to run, expected output
  shape, file format expected, decision being asked.

## Conventions Reference

Commit format, versioning, test runner, package structure, test
patching, async patterns, and TeaMode-specific rate-limit / voice /
SQLite rules are defined in `.project-meta/conventions.md`. Discord
surface rules (palette, embed formatting, custom_id namespace
`teamode:<session_id>:<purpose>[:<value>]`, authorization) are in
`.project-meta/UI-ADR.md`. Read and follow both directly; do not
duplicate them here.

**Agent-specific additions** (not in conventions.md):
- No `Co-Authored-By`, no "Assisted by Claude" trailer, no attribution
  lines of any kind in commits.
- Always use `.venv/bin/python -m pytest tests/`.
- Refer to the Python package as `app/` (the repo root directory is
  also named `teamode/`).

## Code Organization

- Discord-free logic (formatting, rate limiting, stats aggregation,
  message classification, session state) lives in flat modules under
  `app/` with no `discord` imports and injectable clocks, so it is unit
  testable. `app/discord_bot/` holds only Discord wiring: commands,
  views, event handlers, timer and lifecycle orchestration.
- Every tunable number (durations, timeouts, limits, intervals, scan
  depths, widths) and every string Ocha sends to Discord (messages,
  embed titles/fields, button labels, slash-command descriptions, voice
  channel statuses) lives in `app/constants.py` as a named constant,
  using `str.format` placeholders for variable parts. Palette hex
  values live there too. Never inline these in other modules.
  `app/constants.py` must not import `discord` or `app.config`.
- Discord event handlers on the client must be named `on_<event>`
  (discord.py routes `client.event` by function name).

## Typing

- Annotate parameters and return types on every function in `app/`
  and `teamode.py` (Ruff `ANN` enforces this; `tests/` exempt).
  Annotate local variables only when it adds information: a value
  that can be missing or have more than one type, or a non-obvious
  container shape. Let tooling infer the rest.
- Do not use `cast()` or `# type: ignore`. Narrow with `isinstance`,
  explicit `None` checks, or a more precise API (e.g.
  `interaction.channel_id`). The only exception is a genuine bug in
  upstream type stubs: then use `# type: ignore[<specific-code>]` with
  a one-line comment explaining why, and call it out in the completion
  report.

## Discord Messaging

- Any message that will later be edited or deleted must be sent with
  `channel.send`, or have its ID captured
  (`interaction.original_response()`, `followup.send(..., wait=True)`),
  and must be edited/deleted through the channel
  (`channel.get_partial_message(id)`), never through the interaction
  webhook — interaction tokens expire after 15 minutes and sessions
  outlast that.
- Discord edit/delete/status calls that fail (`NotFound`, `Forbidden`,
  `HTTPException`) are logged at WARNING and must not break the session
  flow.
- Never let a stale button crash or mutate state: component
  interactions for missing or finished sessions get the standard
  "session no longer active" ephemeral refusal from constants.

## Async and Logging

- Every background task (`asyncio.create_task`) must log unexpected
  exceptions with `logger.exception` (try/except in the coroutine or a
  done-callback); no task failure may be silently dropped.
  `asyncio.CancelledError` is expected on cancellation and must be
  re-raised, not logged as an error.
- Log to stdout via the module `logger`: INFO for lifecycle events
  (session start/end with state, break start/end/cancel, rate-limit
  refusals, cleanup counts); WARNING for degraded operation (missing
  permission, missing ffmpeg, HTTP 429, failed delete, invalid
  config); `logger.exception` inside error handlers.

## Execution Constraints

- Preserve existing discord.py runtime behavior unless a change is
  explicitly within task scope.
- Do not add dependencies. The only approved addition for this
  project is Pillow, dev-only, in `requirements-dev.txt` (never in
  runtime `requirements.txt`). discord.py stays at 2.7.1.
- Do not add LLM-generated or AI-written text to the bot's runtime
  output (anything Ocha sends to Discord). Use only strings defined in
  `app/constants.py` or given verbatim in the Task Prompt. The ASCII
  teacup banner (`TEACUP_BANNER`) is a User-approved exception.
- Do not perform destructive git operations (force push, reset --hard,
  branch -D, checkout/restore of files you did not change) without
  explicit User instruction.
- The working tree carries the User's own uncommitted edits (e.g.
  `README.md`, `TODO.md`, `changelog.md`,
  `docs/external-interest-log.md`). Preserve them; never revert or
  overwrite them wholesale — make targeted edits only.

## Token Security

- Never commit `DISCORD_BOT_TOKEN`, `.env` files, or any other
  credential to git. `.env` is gitignored; `.env.example` carries stub
  values only.
- Never log token values to stdout, stderr, or any file. If a token
  must appear in a debug line, redact to last-four:
  `Token: ****{last_4}`.
- Never echo a token via `print()`, an error message, a Discord
  message, or a commit message.
- Tests must not require a live Discord token. Use the `FakeInteraction`
  / `AsyncMock` patterns from § Test Patterns below.

## Test Patterns

These rules apply to every test you write. Full reference:
`.project-meta/conventions.md` § Testing and
`.LLMAO/test-patterns.md`. Embedded essentials:

- **SQLite**: use `sqlite3.connect(":memory:")` for tests that
  exercise the database. Do not mock the SQLite layer — exercise the
  real query path.
- **Async**: use `AsyncMock` (not `MagicMock`) for any awaitable mock.
  `MagicMock` returns a `MagicMock` from `await`, which silently
  breaks async paths.
- **Discord**: never hit a live Discord gateway in any test. Use a
  `FakeInteraction` fixture that exposes only the attributes the code
  under test reads. Use `MagicMock(spec=discord.VoiceChannel)` (etc.)
  so `isinstance` narrowing works.
- **Voice**: mock `voice_client.play`; do not shell out to `ffmpeg`
  from a test.
- **Time**: never wait on real time. Use the injectable
  `sleep`/`monotonic` seams (`FakeClock` in
  `tests/test_session_countdown.py`), patched `asyncio.sleep`, or an
  injected clock; use fixed timezone-aware datetimes for date logic.
- **Patch where used, not where defined**: if module A imports
  `helper` from module B, patch `A.helper` in tests targeting A —
  not `B.helper`. Bot code lives in `app.discord_bot.<module>`; patch
  there.

} //APM_RULES
