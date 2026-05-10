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
├── teamode.py                ← entry point (thin)
├── teamode/                  ← package
│   ├── __init__.py
│   ├── bot.py                ← discord.Client + slash command registration
│   ├── session.py            ← session state machine
│   ├── voice.py              ← voice connect/play/disconnect
│   └── db.py                 ← SQLite schema + writes
├── assets/
│   └── reverie.wav           ← end-of-session ring
├── tests/                    ← pytest suite
├── docs/                     ← Discord platform notes, schema, comparisons
├── requirements.txt          ← pinned dependencies
├── .project-meta/            ← conventions, UI-ADR, project-meta artifacts
├── .LLMAO/                   ← LLMAO workflow docs
├── .project-meta/USEE/       ← USEE knowledge framework (under project-meta)
└── .apm/                     ← APM session artifacts
```

APM session artifacts live under `.apm/` and should not be treated as
product source.

### Architecture

**`teamode.py`** — entry-point. Loads env vars (`DISCORD_BOT_TOKEN`,
`TEAMODE_DB_PATH`), constructs the bot, runs the event loop. Imports
all logic from `teamode.bot`.

**`teamode/bot.py`** — discord.py `Client` + slash command tree.
Registers `/teamode`, dispatches button/modal interactions to
`session.py`. The Discord-facing layer.

**`teamode/session.py`** — Session state machine. Pure logic, no
discord.py imports beyond `Interaction` typing. State transitions:
`pending` → `intention_set` → `active` → `followup` → terminal
(`completed` / `followup_timeout` / `cancelled` / `crashed`). Imported
by tests directly without a live bot.

**`teamode/voice.py`** — Voice connect, `FFmpegPCMAudio` playback of
`assets/reverie.wav`, disconnect. Single source of truth for voice.

**`teamode/db.py`** — SQLite schema, connection pool, write helpers.
See `docs/sqlite-schema.md` for the schema reference.

### Data Stores

| Store | Format | Location | Purpose |
|---|---|---|---|
| `sessions` table | SQLite | `$TEAMODE_DB_PATH` (default `./sessions.db`) | One row per `/teamode` invocation. Updated at every state transition. |

## Key Files

| File | Purpose |
|---|---|
| `teamode.py` | Entry point — `python3 teamode.py` |
| `teamode/bot.py` | Discord-facing layer, slash command + interaction routing |
| `teamode/session.py` | Session state machine (testable without Discord) |
| `teamode/voice.py` | Voice connection + reverie playback |
| `teamode/db.py` | SQLite schema and writes |
| `assets/reverie.wav` | End-of-session ring |
| `docs/discord-platform-notes.md` | Discord API reference for slash, components, voice |
| `docs/sqlite-schema.md` | Field-by-field schema reference with citations |
| `docs/language-library-comparison.md` | Why discord.py; hosting tradeoffs |
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

## Configuration & Platform Notes

Do not hardcode local paths or tokens. Read `DISCORD_BOT_TOKEN` and
`TEAMODE_DB_PATH` from environment. Do not check `.env` files into
git.

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

---

# APM Automatic Handoff

Context usage is tracked automatically. When you reach 70% context
usage, you will receive instructions to perform a Handoff. Follow those
instructions when they appear — do not worry about monitoring context
yourself.

---

APM_RULES {

## Approval Workflow

- Obtain explicit user approval before making any code or documentation
  edit — present the proposed change and wait for confirmation before
  modifying any file.
- Obtain explicit user approval before creating any commit — present
  the commit message and changed files, then wait for confirmation.
- If approval has not been granted, stop and present the proposed
  change or next action. Do not proceed unilaterally.

## Validation Protocol

- For all code changes, run the full validation pipeline. Blocking
  checks must pass clean before requesting commit approval:
  1. `ruff format --check teamode/ teamode.py tests/`
  2. `ruff check teamode/ teamode.py tests/`
  3. `.venv/bin/python -m pytest tests/`
  4. `pyright`
  5. `.LLMAO/scan_injection.sh .apm`
- Any blocking-check failure halts the commit. Zero-error target —
  fix root causes rather than bypassing.
- For changes affecting user-visible Discord behavior (slash command
  shape, embeds, button rows, modals, voice playback): flag the change
  as requiring a manual Discord smoke test and note it explicitly when
  requesting commit approval.

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
    paste-ready query.
- Reduce friction: every smoke test is either a single paste-able
  command or a numbered checklist. No ambiguity.

## User Collaboration

- When a Task requires user-provided input (Discord token, server
  access, asset files, judgment-call approval), return Partial with a
  specific request rather than blocking.
- Requests must be concrete: exact commands to run, expected output
  shape, file format expected, decision being asked.

## Conventions Reference

Commit format, versioning, test runner, package structure, test
patching, async patterns, and TeaMode-specific rate-limit / voice /
SQLite rules are defined in `.project-meta/conventions.md`. Do not
duplicate those rules here — read and follow conventions.md directly.

**Agent-specific additions** (not in conventions.md):
- No `Co-Authored-By`, no "Assisted by Claude" trailer, no attribution
  lines of any kind in commits.
- Always use `.venv/bin/python -m pytest tests/`.

## Execution Constraints

- Preserve existing discord.py runtime behavior unless a change is
  explicitly within task scope.
- Do not add new broad dependencies unless explicitly approved.
- Do not add LLM-generated or AI-written text to the bot's runtime
  output (anything Ocha sends to Discord).
- Do not perform destructive git operations (force push, reset --hard,
  branch -D) without explicit user instruction.
- Do not commit Discord tokens or `.env` files.

} //APM_RULES
