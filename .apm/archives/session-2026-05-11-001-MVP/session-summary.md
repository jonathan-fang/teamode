---
date: 2026-05-11T12:30:00Z
project: TeaMode
stages_completed: 6
total_tasks: 15
outcome: complete
---

# APM Session Summary — TeaMode V1

## Project Scope

TeaMode is a self-hosted Discord bot that runs FLOWN/Groove-style guided co-working sessions in voice channels. The bot user is named Ocha. A single slash command `/teamode` walks the facilitator through duration pick → intention capture → countdown → reverie chime → follow-up, recording every session to a local SQLite database. MVP scope: personal use on the facilitator's own server, hosted on demand from their WSL laptop.

Success criteria: a facilitator can run real focus sessions through TeaMode end-to-end, sessions persist correctly to SQLite, the bot is stable enough for a 50-minute session, and voice playback succeeds in ≥ 9 of 10 sessions (graceful degradation to text mention acceptable).

Stack: Python 3.12.3 · discord.py[voice] 2.7.1 · asyncio · SQLite (`sqlite3`) · pytest · pyright · ruff.

---

## Stages and Outcomes

### Stage 1 — Foundation (Tasks 1.1–1.2) · Complete

**Objective:** Package skeleton, env loader, SQLite schema, and write helpers.

- **T1.1** created `app/__init__.py`, `app/config.py` (strict `DISCORD_BOT_TOKEN` enforcement), `teamode.py` entry stub, `requirements.txt` with exact-version pins, `.env.example`, and `tests/test_config.py`. Clean first pass.
- **T1.2** implemented `app/db.py` with idempotent `init_db`, ten write helpers covering every state transition, and `reconcile_crashed_sessions`. One follow-up cycle: the schema doc's `NOT NULL` constraints on `started_at` and `duration_minutes` conflicted with the `pending` insert lifecycle — corrected to nullable in `docs/sqlite-schema.md`, then db helpers revised to omit those columns at INSERT. 29 tests in `test_db.py`, all using `:memory:`.

### Stage 2 — Invocation + Welcome (Tasks 2.1–2.2) · Complete

**Objective:** Session state machine, invocation guard, and welcome surface.

- **T2.1** shipped `app/session.py` with `SessionState` enum (8 states), `Session` dataclass, and `SessionRegistry` (in-memory + SQLite in lockstep, channel-exclusivity invariant). Pinned `pytest-asyncio` to `strict` mode in `pyproject.toml`; added `tests/conftest.py` stub-token fixture so the suite runs without a live token. 19 tests. Clean first pass.
- **T2.2** shipped `app/bot.py` with `discord.Client`, `app_commands.CommandTree`, and the cumulative invocation guard (channel-type → in-voice → no-active-session). Welcome embed uses the matcha-sage accent (`#7B9D6F`) and the canonical copy authored by User (committed to UI-ADR). Timer-pick buttons dispatched as `teamode:<session_id>:timer:<5|10|25|50>`. Two follow-up cycles: (1) worker-invented welcome copy violated "no LLM-generated runtime output" — User wrote canonical copy; (2) `_on_ready` handler never fired due to `client.event` using `__name__` — fixed to `on_ready`. Manual smoke test confirmed all four guard cases. 56 tests total.

### Stage 3 — Intention + Timer + Voice (Tasks 3.1–3.3) · Complete

**Objective:** Timer-pick handler, intention modal, voice plumbing, active timer, and countdown loop.

- **T3.1** shipped `app/voice.py` with `connect`, `play_reverie`, `disconnect`, and `REVERIE_PATH` constant resolved at import. 7 tests. Clean first pass.
- **T3.2** wired the `on_interaction` dispatcher (`teamode:<sid>:timer:<value>` → `_handle_timer_pick` → `IntentionModal`). One follow-up: original worker introduced pyright errors (`CommandTree.process_application_commands` doesn't exist; `Label.component` type erasure — resolved with `cast(discord.ui.TextInput[...], label.component)` pattern). 5 tests.
- **T3.3** shipped `run_countdown` coroutine in `app/session.py` (injectable `sleep`/`monotonic` for fake-clock testing), `_EditState` per-session holder with 10s edit cadence and 429 exponential backoff, and the post-intention flow (voice connect → mark_active → timer post → countdown task). Three smoke-driven fixes: `channel.send` 403 → switched to `interaction.followup.send(ephemeral=False, wait=True)`; `client.fetch_channel` 403 → threaded resolved `VoiceChannel` through `IntentionModal.__init__`; timer format refreshed to three-line layout per User direction. 8 countdown tests + 7 tick-callback tests. 84 tests total. Scope-drift carry-forward: T3.3 worker added a premature `voice_client.disconnect()` after `mark_followup` — flagged for T4.1 to remove.

### Stage 4 — End-of-Session + Follow-up (Tasks 4.1–4.2) · Complete

**Objective:** Reverie playback and the full end-of-session UX (Session-complete embed, Reflect embed, reaction-authoritative follow-up).

- **T4.1** added `play_reverie_then_disconnect(voice_client) -> bool` using `asyncio.Event` set via `loop.call_soon_threadsafe` in the `after` callback; always disconnects; returns `True`/`False` for fallback decision. Removed the premature disconnect from T3.3. 4 new voice tests. 88 tests total.
- **T4.2** went through three design states: (1) initial buttons-based implementation (Yes/No/End-early + `WhyModal`) — worked, smoke-tested; (2) reactions redesign at User direction — dropped all buttons, `on_raw_reaction_add` handler makes facilitator ✅/⛔ authoritative, ⛔ posts a public "why" prompt that is not captured, 3-min watchdog via cancellable `asyncio.Task`; (3) pre-merge UX bundle — participant prompt moved to 1s post-welcome with @-mentions, 5-min timer option added (durations now 5/10/25/50), intention modal accepts empty submission (collapses to `🍵 No intention set`), Session-complete body promoted to `###` heading style. Org monthly usage limit interrupted the Sonnet worker mid-bundle — Manager finished docs, tests, and pipeline inline. Smoke test revealed `ffmpeg` not installed on WSL host (silent failure mode); fixed with `sudo apt install ffmpeg`. 11 followup tests. 101 tests total. Manager 1 → Manager 2 handoff happened mid-T4.2.

### Stage 5 — Edge Cases (Tasks 5.1–5.4) · Complete

**Objective:** Facilitator handoff, solo grace watchdog, crash reconciliation test reorganization, reconnect-tolerance documentation.

- **T5.1** wired `on_voice_state_update` for auto RNG handoff (facilitator leaves, ≥1 other remains → `random.choice` → `mark_handoff` → announcement). Scope expanded at User direction to also implement `/handoff @user` manual slash command with a 5-branch guard (no active session, non-facilitator invoker, self-target, bot target, target not in voice). `SessionRegistry.find_active_in_voice_channel` lookup method added. 10 tests. Smoke step 1 (slash sync) confirmed; manual happy path and auto RNG steps deferred to V1 monitoring. 111 tests total.
- **T5.2** implemented `_run_solo_grace` watchdog in `app/bot.py`; stashed per-session `_voice_clients`, `_countdown_tasks`, `_solo_grace_tasks` dicts. Watchdog times out at 5 minutes, edits timer message to "Session ended — facilitator did not return," disconnects, writes `status='cancelled'`. Rejoin within window cancels watchdog. 10 tests. 121 tests total.
- **T5.3** closed the Plan deliverable cosmetically — wiring shipped in T1.2/T2.2. Lifted `conn` fixture to `tests/conftest.py`, moved reconciliation tests to `tests/test_db_reconciliation.py`. Added ordering-invariant comment in `teamode.py`. No test count change.
- **T5.4** pure documentation: reconnect-tolerance comments in `session.py:run_countdown` and `bot.py:TeaModeBot.__init__`; wifi-drop smoke-test plan appended to `docs/discord-bot-setup.md`. Manager 2 → Manager 3 handoff at Stage 4 close/Stage 5 open boundary; Manager 3 ran all four Stage 5 dispatches.

### Stage 6 — Cleanup + V1 Release (Tasks 6.1–6.2) · Complete

**Objective:** Final validation pipeline, docs sync, dependency audit, V1 tag.

- **T6.1** synced `README.md` (removed all `_planned_` markers, corrected timer durations to 5/10/25/50, updated session-flow example to the shipped reactions-based design, added `/handoff @user` row, corrected `teamode/` → `app/` in layout tree). Created `changelog.md` with V1 feature list and a "Not in V1" section. Audited `docs/sqlite-schema.md` (stripped "Proposed" from title, corrected duration values). `pip-audit` found two CVEs: CVE-2025-71176 (pytest 8.3.5) — remediated by bumping to pytest 9.0.3 and pytest-asyncio 1.3.0; CVE-2025-69277 (PyNaCl) — unresolvable at V1 (discord.py pins `PyNaCl<1.6`, fix requires 1.6.2). Worker returned Partial with full diagnostic; Manager + User triaged as documented known issue. Manager follow-up commit added `vulture==2.16` to dev deps; vulture run at confidence ≥80 returned zero findings. Final pipeline: ruff format clean, ruff check clean, 121 tests pass, pyright 0 errors, vulture 0 findings, `scan_injection.sh` only pre-existing false positives, pip-audit only the documented PyNaCl known issue.
- **T6.2** Manager-driven (no worker dispatch): annotated tag `v26Q2.0.0` composed and created on merge commit `8ab3323`. User approved push. `git push origin main` + `git push origin v26Q2.0.0` both succeeded.

---

## Key Deliverables

| Deliverable | Path |
|---|---|
| Entry point | `teamode.py` |
| Discord-facing layer | `app/bot.py` |
| Session state machine | `app/session.py` |
| Voice helpers | `app/voice.py` |
| SQLite schema + helpers | `app/db.py` |
| Configuration loader | `app/config.py` |
| Test suite (121 tests) | `tests/` |
| Requirements (exact-pinned) | `requirements.txt` |
| Changelog | `changelog.md` |
| README | `README.md` |
| Schema reference | `docs/sqlite-schema.md` |
| State machine diagram | `docs/state-machine.md` |
| Bot setup guide + reconnect smoke plan | `docs/discord-bot-setup.md` |
| V1 annotated tag | `v26Q2.0.0` on `origin/main` |

---

## Codebase State

The codebase fully implements the plan. All planned modules exist and all key functions are present at the locations the task logs describe:

- `app/session.py`: `SessionState` enum, `Session` dataclass, `SessionRegistry` (all 9 transitions), `run_countdown` coroutine, `find_active_in_voice_channel` lookup
- `app/db.py`: `init_db`, 10 write helpers, `reconcile_crashed_sessions`
- `app/voice.py`: `connect`, `play_reverie`, `disconnect`, `play_reverie_then_disconnect`
- `app/bot.py`: `/teamode` slash command, `/handoff` slash command, `on_voice_state_update`, `on_raw_reaction_add`, `IntentionModal`, `_run_solo_grace`, `_EditState`-driven countdown edit cycle

The codebase evolved past the original Spec in three ways that were all explicitly approved: (1) timer durations expanded from 10/25/50 to 5/10/25/50; (2) follow-up mechanism changed from button-based to reaction-authoritative (redesigned mid-Stage 4); (3) participant prompt moved 1s post-welcome with @-mentions (pre-merge UX bundle). The Spec and Plan were updated in-session to reflect each of these changes.

The `on_raw_reaction_add` handler (rather than `on_reaction_add`) was used because cached message objects are not guaranteed for messages the bot sent. This is an implementation detail consistent with the Spec's intent.

---

## Notable Findings

**`client.event` uses handler `__name__` for event routing.** A leading underscore in `_on_ready` caused the ready handler to silently fail — slash commands never synced to the dev guild. Fixed in T2.2 follow-up. Now documented in `docs/discordpy-api/gotchas.md`.

**`interaction.followup.send` vs `channel.send`.** `channel.send` requires explicit View/Send channel overrides in private voice channels; `interaction.followup.send` reuses the interaction webhook token and bypasses that gate. T3.3 switched to followup after two 403 errors in smoke testing. Documented in memory index and `docs/discordpy-api/gotchas.md`.

**`discord.ui.Label.component` type erasure.** pyright sees `Label.component` as `Item[Unknown]`, not `TextInput`, so `.value` access fails type checking. Workaround: `cast(discord.ui.TextInput[discord.ui.Modal], label.component)`. Documented in gotchas.

**ffmpeg silent failure.** `play_reverie_then_disconnect` catches synchronous `play()` failures and disconnects immediately — so when `ffmpeg` was absent from the WSL host, the bot disconnected and posted the Reflect embed with no error visible. Diagnosed during T4.2 smoke test. Setup fix: `sudo apt install ffmpeg`. A v1.x TODO captures a startup `shutil.which("ffmpeg")` probe to emit an explicit WARNING.

**Parallel dispatch net-negative in Stage 3.** T3.1 and T3.2 dispatched in parallel via worktrees. T3.2 worker engaged with a User question mid-dispatch and never returned a Task Result, requiring a recovery dispatch (~75k extra tokens). Sequential was faster overall. Stage 5 ran sequentially by default.

**Org usage limit interrupted T4.2 Sonnet worker.** Worker completed all code surfaces mid-bundle but hit the monthly limit before docs, tests, and pipeline. Manager finished inline — cheaper and faster than re-dispatch given the remaining scope was well-bounded diffs.

**PyNaCl CVE-2025-69277 blocked by discord.py pin.** `discord.py[voice]==2.7.1` pins `PyNaCl<1.6`; the fix requires PyNaCl 1.6.2. Remediation requires a discord.py version bump. Documented as a known issue in `changelog.md`. Manager + User assessed practical risk as low given TeaMode uses only standard voice encryption (not atypical custom-crypto paths).

---

## Known Issues

1. **PyNaCl CVE-2025-69277 (unresolvable at V1).** Requires discord.py upstream release with PyNaCl ≥ 1.6 support. Documented in `changelog.md`. Low practical risk for standard voice-channel usage.

2. **Eight live-Discord smoke paths deferred to V1 monitoring.** From Stages 4 and 5: non-facilitator reaction logged-only, 3-min Reflect timeout, `/handoff` manual happy path, `/handoff` refusal branches, auto RNG handoff, solo-grace rejoin cancel, solo-grace 5-min timeout, wifi-drop reconnect tolerance (T5.4 plan). These paths are covered by automated tests but have not been exercised in a real Discord session.

3. **`ffmpeg` missing fails silently.** Without `ffmpeg` on PATH, reverie playback fails and the bot disconnects immediately before the Reflect embed. Symptom looks like reverie didn't play, no error visible. A startup `shutil.which("ffmpeg")` WARNING probe is tracked in `TODO.md` (v1.x).

4. **audioop deprecation warning.** `pytest` emits one warning per run from discord.py's use of `audioop` (deprecated in Python 3.11, removed in 3.13). Pre-existing, upstream concern.

---

## Snapshot Notice

This summary reflects the session state as of `2026-05-11T12:30:00Z`. The codebase may have diverged since this summary was created.
