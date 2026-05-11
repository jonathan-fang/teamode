---
title: TeaMode
---

# APM Memory Index

## Memory Notes

- **`pytest-asyncio` config:** the project uses `pytest-asyncio==0.26.0` without an explicit `asyncio_mode` setting, which emits a deprecation warning every test run. The first task that introduces async tests (T2.1) should add `asyncio_mode = "strict"` to `pyproject.toml` (or `[pytest]` in `pytest.ini`) to silence the warning and pin behavior before the library's default flips.
- **Package vs repo-root naming:** the Python package is `app/`; the repo root directory on disk is also named `teamode/` (visible in `AGENTS.md`'s tree diagram, line 22). When dispatching, refer to the package as "`app/`" explicitly to avoid worker confusion when they re-read `AGENTS.md`. The slash command `/teamode` and entry-point file `teamode.py` are unrelated to either.
- **Test environment dependency:** `app/config.py` raises `RuntimeError` at module import time when `DISCORD_BOT_TOKEN` is unset. The whole test suite depends on `tests/conftest.py` calling `os.environ.setdefault("DISCORD_BOT_TOKEN", "test-stub-token")` before any `app.*` import. New test modules inherit this for free; running tests outside pytest (e.g. ad-hoc `python -c "from app import session"`) needs the env var set manually. If this brittleness bites again, a factory pattern (`Config.load()`) is the right refactor — punt until then.
- **discord.py event registration gotcha:** `Client.event(func)` uses `func.__name__` to determine which Discord event the handler responds to. Method names with leading underscores (e.g. `_on_ready`) silently fail to register because no event by that name exists. Always name event handlers with the public `on_<event>` form. Caught the hard way during T2.2 smoke test. Also documented in `docs/discordpy-api/gotchas.md` for visibility next to the offline API reference.
- **discord.py `on_interaction` + `CommandTree` separation:** `on_interaction` fires for every interaction type but the `CommandTree` has already routed `APPLICATION_COMMAND` types via internal `_state._command_tree._from_interaction` before `on_interaction` runs. A custom `on_interaction` listener that wants to handle component clicks must filter to `interaction.type == discord.InteractionType.component` and not attempt to re-dispatch slash commands (no `process_application_commands` method exists). Documented in `docs/discordpy-api/gotchas.md`.
- **discord.py `Label.component` type erasure:** when a `Modal` wraps a `TextInput` in a `Label`, pyright sees `Label.component` as `Item[Unknown]` not `TextInput`, so `.value` access errors. Use `cast(discord.ui.TextInput[discord.ui.Modal], label.component).value` at the read site. Documented in `docs/discordpy-api/gotchas.md`.
- **`interaction.followup.send` over `channel.send` after a modal/interaction.** `interaction.channel.send(...)` and `client.fetch_channel(...)` go through the bot's regular HTTP path and require explicit channel-level View/Send perms. `interaction.followup.send(content, ephemeral=False, wait=True)` reuses the interaction webhook token and skips that gate — it just works wherever the original interaction was accepted. Default to followup for any post-interaction send. Resolve channel objects from `interaction.channel` directly rather than `client.fetch_channel(...)`; for cross-handler use, thread the resolved object through (e.g. `IntentionModal.__init__`) instead of re-fetching by id.
- **Private-channel deployment requires explicit role allow-list.** Discord evaluates role grants → channel overrides → category overrides with denies winning. In a private channel, `@everyone` is denied View Channel by default and role-level grants do not propagate. Bot must be added as an explicit allow on the channel. Documented in `docs/discord-bot-setup.md` § "Private voice channels".
- **Parallel-dispatch overhead can erase the wall-clock win.** Stage 3 ran T3.1 + T3.2 in parallel via worktrees. T3.2's worker engaged with a User mid-dispatch question, never returned a Task Result, and required a recovery dispatch (~75k extra tokens). The wall-clock savings vs sequential were net-negative once recovery was counted. For future parallel opportunities (T5.3 + T5.4), default to sequential unless the User explicitly wants parallel again.
- **Don't message an in-flight worker directly.** Workers receive direct user messages and will engage with them, breaking the apm-worker "no User interaction" contract — they may forget to commit, log, or return a `## Task Result`. User has confirmed: route any mid-dispatch question through the Manager (queue it; Manager answers when worker returns or relays after).
- **Org monthly usage limit can interrupt worker dispatch mid-Task.** During T4.2 pre-merge UX bundle, a Sonnet worker hit the limit partway through with code surfaces complete but docs, tests, and pipeline incomplete. Manager finished the work inline (cheaper than waiting/re-dispatching, and the remaining diffs were precise). Pattern: if a worker dies mid-Task with most of the heavy lifting done, finishing inline as Manager is the right move — preserve worker context for fresh-start work.
- **Pyright `discord.Client.user` is a read-only property.** Tests that need to set `bot.client.user.id` cannot assign directly; swap `bot.client` with a `MagicMock(spec=discord.Client)` and set `user.id` as an attribute. Pattern used in `tests/test_bot_followup.py` `_install_fake_client_user` helper.
- **ffmpeg-missing fails silently into early disconnect.** `play_reverie_then_disconnect` catches `play()` synchronous failures, sets `success=False`, and skips `await done.wait()` — so without `ffmpeg` on PATH the bot disconnects immediately and the next message (Reflect embed) posts. Symptom looks like "reverie didn't play" with no error visible. v1.x TODO captures a startup probe; setup-time fix is `sudo apt install ffmpeg`.
- **Discord embed body markdown.** `# H1`, `## H2`, `### H3` headings work inside embed descriptions (since 2023). Project settled on `### ` prefix on every line of every **content** embed (welcome, Session-complete, Reflect) for consistent heading-style weight; refusal embeds excluded. UI-ADR § "Decisions already made" pins this rule.

## Stage Summaries

### Stage 6 — Cleanup + V1 Release

Two Tasks closed the V1 release. T6.1 synced README and docs, created `changelog.md`, audited deps, and pinned `pip-audit` + `vulture` as dev tools. T6.2 tagged `v26Q2.0.0` on the merge commit and pushed to `origin/main`. Worker returned Partial on T6.1 due to an upstream-blocked CVE; Manager triaged inline with User and resolved as documented known issue rather than holding the release.

T6.1 (`chore/v1-release-prep`, merged `8ab3323`):
- **README sync (commit `5383850`):** dropped all `_planned_` / `(planned)` markers; corrected timer durations to 5/10/25/50; replaced the outdated Yes/No-button + 👍/👎-reaction example with the actually-shipped Session-complete embed → reverie → Reflect embed → facilitator ✅/⛔ flow; added `/handoff @user` row to the guards table; corrected `teamode/` → `app/` in the repo-layout tree.
- **`changelog.md` created:** v26Q2.0.0 feature list (slash command + guard, full session flow, durations 5/10/25/50, empty intention, participant prompt, reverie, ✅/⛔ Reflect, 3-min watchdog, auto + manual handoff, solo grace, crash reconciliation, SQLite log) plus "Not in V1" deferrals.
- **Docs audit:** `docs/sqlite-schema.md` had `(Proposed)` stripped from the title and `duration_minutes` corrected to "5, 10, 25, or 50". Other docs accurate; no changes.
- **`pip-audit` 2.10.0 pinned** under `# Dev` in `requirements.txt`. Audit surfaced two CVEs:
  - **CVE-2025-71176 (pytest):** remediated cleanly — bumped `pytest==8.3.5→9.0.3` and `pytest-asyncio==0.26.0→1.3.0` (0.26.0 caps `pytest<9`). All 121 tests pass on the new pins.
  - **CVE-2025-69277 (PyNaCl):** **unresolvable** at V1 — `discord.py[voice]==2.7.1` (latest on PyPI as of 2026-05-11) pins `PyNaCl<1.6,>=1.5.0`, fix requires `PyNaCl==1.6.2`. pip raises `ResolutionImpossible`. Worker returned Partial with full diagnostic. Manager + User triaged: low practical risk (atypical custom-crypto paths; discord.py uses only standard voice encryption), documented as a Known Issue in `changelog.md`, will revisit when discord.py releases with PyNaCl>=1.6 support.
- **Manager follow-up commit `6b17d80`:** added `vulture==2.16` to `requirements.txt` dev section; named `vulture` explicitly as the dead-code scanner in `.project-meta/conventions.md` § Release Process (the existing "Scan for dead code; remove" step). Vulture run at confidence ≥80 returned zero findings on `app/ teamode.py`.
- **`pip list --outdated`** run informationally: only PyNaCl (the documented blocker), `pip` itself (meta), and `pyright`/`ruff` patches (dev tools — non-blocking per conventions § Dependency Maintenance monthly cadence).

T6.2 (no branch — Manager-driven, no worker dispatch): composed annotated tag message summarising V1 deliverables and explicitly noting the PyNaCl known issue. Tagged `v26Q2.0.0` on merge commit `8ab3323`. User approved push. `git push origin main` + `git push origin v26Q2.0.0` both succeeded.

Stage verification: final pipeline on `main` post-T6.1-merge — ruff format check clean, ruff check clean, 121 pytest passing, pyright 0 errors / 0 warnings, vulture 0 findings at confidence ≥80, `scan_injection.sh` flagged only the documented pre-existing false positives, `pip-audit` flagged only the documented PyNaCl known issue.

**Carry-forward beyond V1:** post-release backlog (V1 monitoring / V1.x):
- Discord smoke-test bundle deferred from Stages 4 and 5: non-facilitator reaction logged-only, 3-min Reflect-timeout, manual `/handoff` happy path + refusals, auto RNG handoff, solo-grace 5-min timeout, solo-grace rejoin cancel, wifi-drop reconnect tolerance (T5.4 plan). Eight live-Discord paths total.
- ffmpeg startup probe (TODO.md v1.x): emit a WARNING log line when `shutil.which("ffmpeg")` returns None so the silent-disconnect failure mode is diagnosable.
- PyNaCl CVE-2025-69277: revisit when discord.py releases with PyNaCl>=1.6 support.

**Task Logs:**
- task-06-01.log.md
- (T6.2 had no worker dispatch; this Stage summary stands in for its log.)

### Stage 5 — Edge Cases

Four Tasks delivered facilitator handoff (auto RNG + manual `/handoff` command), solo-facilitator 5-minute grace watchdog, crash reconciliation closure (Plan-aligned test reorganisation; the wiring itself shipped earlier in T1.2/T2.2), and reconnect-tolerance documentation. All four Tasks clean first-pass on Sonnet workers, sequential dispatch. Manager 2 → Manager 3 handoff happened at the Stage 4 close / Stage 5 open boundary — Manager 3 ran all four Stage 5 dispatches.

T5.1 (`feat/facilitator-handoff`, commit `53f5d0c feat(bot): facilitator handoff — auto RNG and /handoff command`, merged `a81f725`): Added `SessionRegistry.find_active_in_voice_channel(voice_channel_id)` returning the in-progress session (`INTENTION_SET` or `ACTIVE`). Wired `on_voice_state_update` listener with leave-detection → facilitator-only filter → remaining-humans count → `random.choice` over the rest → `registry.mark_handoff(...)` → text-channel announcement (`<@old> left — <@new>, you're now the facilitator.`). Manual scope expansion approved by User: `/handoff @user` slash command with five-stage guard (no active session, non-facilitator invoker, target-is-self, target-is-bot, target-not-in-voice) — each refusal an ephemeral muted-grey embed. Success path uses `interaction.response.send_message` with `discord.AllowedMentions(users=True)` and "handed off —" wording (distinct from the auto announcement's "left —" so the channel sees the difference). 10 new tests in `tests/test_session_handoff.py` cover all branches. Smoke step 1 (slash sync — `/handoff` appears in command picker) confirmed by User; steps 2–5 (manual happy path, refusals, auto RNG, solo passthrough) deferred to Stage-close bundle.

T5.2 (`feat/solo-grace`, commit `fcd613c feat(bot): 5-minute solo-facilitator grace watchdog`, merged `d22b5b6`): Required upfront plumbing because the voice client and countdown task were closed over inside `IntentionModal.on_submit` and unreachable from `on_voice_state_update`. Added three per-session dicts on `TeaModeBot`: `_voice_clients`, `_countdown_tasks`, `_solo_grace_tasks`. Added `_SOLO_GRACE_SECONDS = 300` module constant. Added join-detection branch to `on_voice_state_update` (cancel watchdog if facilitator rejoins same VC). Extended the existing leave branch's empty-remaining path from no-op to "arm watchdog" with double-arm guard. `_run_solo_grace(session_id, sleep_seconds=300)` sleeps then cancels the countdown task, edits timer message to `"Session ended — facilitator did not return."`, calls `voice.disconnect(voice_client)` (no reverie), and writes `status='cancelled'`. The `sleep_seconds` parameter is the test-injection seam — production uses default. 10 new tests in `tests/test_session_solo_grace.py` cover watchdog timeout, missing-state graceful path, edit-failure resilience, listener arming, rejoin-cancel, non-facilitator-join-noop, different-channel-noop, bot-only-remaining arms, double-arm protection.

T5.3 (`chore/reconciliation-test-reorg`, commit `e19dcdc refactor(db): move reconciliation tests to dedicated module`, merged `cce472e`): Closed the Plan deliverable cosmetically — the reconciliation wiring itself shipped in T1.2 (`db.reconcile_crashed_sessions`) and T2.2 (`teamode.py` startup wiring). Added an inline comment at the call site documenting the `init_db → reconcile → gateway` ordering invariant. Lifted the `conn` fixture from `test_db.py` to `tests/conftest.py` and moved the five reconcile tests into the Plan-named `tests/test_db_reconciliation.py`. No functional change; test count unchanged at 121. User chose dispatch-anyway over inline-close to maintain dispatch consistency across Stage 5.

T5.4 (`docs/reconnect-tolerance`, commit `241ac93 docs(reconnect): document gateway reconnect tolerance and smoke plan`, merged `317555a`): Pure documentation. Two code comments at the relevant seams (top of `run_countdown` in `app/session.py` explaining `asyncio.sleep` is unaffected by websocket state and edits queue/retry transparently; above `discord.Client(...)` construction in `app/bot.py` noting discord.py handles reconnect with exponential backoff). New `## Reconnect tolerance verification` section appended to `docs/discord-bot-setup.md` with setup/steps/failure-modes/acceptance for a 30s wifi-drop smoke test at minute 3 of a 10-min session.

Stage verification: full pipeline clean on `main` post-merge (121 tests pass, ruff clean, pyright 0 errors, scan_injection only pre-existing handoff-log false positives). Stage-close smoke bundle (T5.1 steps 2–5, T5.2 rejoin + timeout, T5.4 wifi drop) pending User execution — see Tracker Working Notes for the deferred-to-V1-monitoring carry-forward if User opts to defer rather than run.

Memory notes added (none — Stage 5 had no surprising integration patterns that future Tasks would benefit from; existing notes about `MagicMock(spec=discord.Client)`, "patch where used", `AsyncMock`, and the `_install_fake_client_user` helper all carried forward unchanged).

**Carry-forward for Stage 6:** All four Stage 5 deferred smoke tests carry to Stage 6 UAT, alongside the Stage 4 deferred non-facilitator-reaction-logged-only and 3-min-followup-timeout paths. T6.1 (final validation + docs sync, `pip-audit`) and T6.2 (V1 tag) are sequential by Plan; T6.1 promotes to Ready once Stage 5 closes here.

**Task Logs:**
- task-05-01.log.md
- task-05-02.log.md
- task-05-03.log.md
- task-05-04.log.md

### Stage 4 — End-of-Session + Follow-up

Two Tasks delivered reverie playback at zero and the full end-of-session UX (Session-complete embed, reverie, Reflect embed, facilitator-authoritative ✅/⛔ reactions, 3-minute timeout watchdog). T4.2 went through three design states before merging — initial buttons-based, redesigned to reactions-authoritative mid-Stage, and a pre-merge UX bundle adding 5-min timer, earlier participant prompt, empty modal acceptance, and `###` heading style. Manager 1 → Manager 2 handoff happened mid-T4.2 (Manager 1 hit context limit while drafting the reactions-redesign follow-up dispatch).

T4.1 (`feat/reverie-playback`, commit `1848b6d feat(voice): add play_reverie_then_disconnect helper`) added the `play_reverie_then_disconnect(voice_client) -> bool` helper to `app/voice.py`. Uses `asyncio.Event` set via `loop.call_soon_threadsafe` in the `after` callback; awaits playback completion; always disconnects; returns `True` on success, `False` if `play()` raised synchronously. Four new tests cover both paths plus the `after`-callback signalling pattern. Clean first pass.

T4.2 (`feat/end-of-session-followup`, three rounds of dispatch): **(1) Initial buttons-based implementation** (commits `481640d` + `3548d0e`) shipped the end-of-session sequence with Yes/No/End-early buttons and a `WhyModal` for the "why" capture. Worker returned Success; smoke-test happy path worked. **(2) Reactions-redesign** (commit `18ba4b3 refactor(bot): replace follow-up buttons with reactions-authoritative flow`): User decided post-smoke to drop all buttons and use the facilitator's ✅/⛔ reaction on the Reflect embed as authoritative for `completed_intention`. ⛔ posts a public "why" prompt the bot does not capture. 727-line test file rewritten to 11 tests (~680 lines) covering happy path, empty voice channel, reverie failure, facilitator ✅/⛔, non-facilitator logged-only, bot-own-reaction ignored, unrelated emoji, non-session message, 3-min timeout, timer-pick auto-disable. Spec, Plan T4.2 guidance, and UI-ADR were updated for this redesign before dispatch (`4335b2d` + `f45756e` on `main`). **(3) Pre-merge UX bundle** (commits `20ce324` + `cc4df95` + `39e0c98` + `bc3757a`): User requested five bundled changes — `[Set Intention]` prompt moved to 1s post-welcome with @-mentions of voice members; 5-min option added (durations now 5/10/25/50); intention modal accepts empty submit (collapses to `🍵 No intention set`); Session-complete body promoted to heading; subsequently extended to `### ` on every line of every content embed for consistent visual weight; refusal embeds excluded. Worker dispatched on Sonnet hit org monthly usage limit mid-Task with code surfaces complete; Manager finished docs, tests, and pipeline inline. Reflect prompt copy refreshed inline by User to `[Follow-up] React with ✅ if you finished, or ⛔ if not.` (no facilitator mention — Session-complete already pings everyone above).

Smoke testing exposed a host-side issue: reverie failed to play because `ffmpeg` was not installed on the WSL host. `play_reverie_then_disconnect` short-circuits on `FFmpegPCMAudio` synchronous failure, disconnects immediately, and posts the Reflect embed — symptom looked like a code defect but was setup. User installed `ffmpeg`; v1.x TODO entry captures a startup probe to warn explicitly when missing. Reverie now plays in full before disconnect (the helper `await`s the playback-complete `asyncio.Event` from the `after` callback).

Stage verification: full pipeline clean on `main` post-merge (101 tests pass, ruff clean, pyright 0 errors, scan_injection only pre-existing handoff-log false positives) plus User-confirmed smoke test in dev guild covering welcome → participant prompt → empty-intention modal → reverie → Session-complete + Reflect embeds → facilitator ✅ path. Non-facilitator and 3-min timeout smoke paths deferred to V1 monitoring per User direction.

Documentation added: substantial UI-ADR amendments (Welcome/Reflect bodies show `### ` rendering, Session-complete heading, Surface inventory grew a Participant prompt row, four Decisions entries added), Spec amendments (Sequence diagram reordered, Visual fidelity tier covers empty intention and heading rendering, durations updated to 5/10/25/50), and `.apm/memory/handoffs/manager/handoff-1.log.md` tracked.

**Carry-forward for Stage 5:** T5.1 scope expanded to include manual facilitator handoff command **`/handoff @user`** (User renamed from `/lead @user` before dispatch). T5.1 should implement both the automatic RNG handoff on `voice_state_update` and the manual slash command. T5.4 (reconnect tolerance verification) is now Ready since T4.2 is Done. T5.3 (crash reconciliation) is Ready. T5.2 still waits on T5.1. Parallel dispatch is discouraged by Memory note — default sequential.

**Task Logs:**
- task-04-01.log.md
- task-04-02.log.md

### Stage 3 — Intention + Timer + Voice

Three Tasks delivered the timer-pick handler, intention modal, voice connection plumbing, active timer surface, and the drift-corrected countdown coroutine. T3.1 and T3.2 dispatched in parallel via worktrees; T3.3 sequential after both merged. T3.3 needed three follow-up cycles after smoke testing.

T3.1 (`feat/voice-plumbing`, commit `bcf6940`) added `app/voice.py` — three thin shims (`connect`, `play_reverie`, `disconnect`) over `discord.FFmpegPCMAudio` and `VoiceClient`, with `REVERIE_PATH` resolved at import. Seven tests cover happy paths and exception propagation, all mocking `voice_client.play` so no real `ffmpeg` invocation. Clean first pass.

T3.2 (`feat/timer-intention`, commit `6409d35`) wired the `on_interaction` listener with custom_id dispatch (`teamode:<sid>:timer:<value>` → `_handle_timer_pick` → `set_duration` → `IntentionModal`), the modal with one `discord.ui.TextInput`, the modal-submit chain (`set_intention` → defer → participant prompt). Worker engaged with a User question mid-dispatch (re: `CommandTree`) and never returned a Task Result; recovery worker fixed three pyright errors introduced by the original (notably `CommandTree.process_application_commands` doesn't exist) and committed cleanly.

T3.3 (`feat/active-timer-countdown`, six commits) shipped the `run_countdown` coroutine in `app/session.py` (Discord-independent, dependency-injected `sleep` and `monotonic` for `FakeClock` testing), the `_EditState` per-session holder with 10s edit cadence and 429 exponential backoff, and the post-intention flow chain (voice connect → mark_active → active timer post → countdown task → mark_followup). Three follow-up cycles after smoke testing: (a) `interaction.channel.send` 403'd because the bot lacked direct channel-send perms in the dev server's voice channel — switched to `interaction.followup.send(ephemeral=False, wait=True)` (commit `588dced`); (b) `client.fetch_channel(voice_channel_id)` 403'd similarly via the REST permission gate — User chose Option A: thread the resolved `discord.VoiceChannel` through `IntentionModal.__init__`, dropping the REST call (commit `b4e0693`); (c) timer message format refreshed to a three-line layout (`Facilitator's Intention` / `<duration> min session` / `⏳ MM:SS`) per User direction (commit `758d3a1`); plus participant prompt bolded `**[Set Intention]**`. User-side companion fix: explicit channel overrides on the voice channel for the TeaMode role.

Stage verification: full pipeline clean on `main` post-merge (84 tests pass, ruff clean, pyright 0 errors, scan clean) plus manual Discord smoke test in dev guild — facilitator submitted intention, Ocha auto-joined voice, three-line timer ticked correctly to zero with 10s edits, SQLite reached `status='followup'`. Reverie not yet played (T4.1 scope).

**Scope drift to address in T4.1:** the T3.3 worker added `voice_client.disconnect()` immediately after `mark_followup` (around `app/bot.py:182`), causing the bot to leave voice before reverie can play. T4.1's prompt explicitly removes this premature disconnect and reorders the post-followup sequence per Spec § Voice.

Documentation added: `docs/state-machine.md`, `docs/discord-bot-setup.md`, `docs/discordpy-api/{api,interactions-api,ext-commands-api,ext-tasks}.html` (offline reference), `docs/discordpy-api/gotchas.md`, `docs/fake-clock.md`, `docs/sqlite-schema.md` § "Viewing the database". TODOs added: app icon + banner (v1.x), `app/bot.py` rename (v1.x deferred), modal `required=False` + empty-intention display (v1.x), three-minute wrap-up nudge (v1.x), embed timer with progress bar + phase labels inspired by dlqa's `FocusTimerWidget` (v2). Spec § "Visual fidelity tier" updated. UI-ADR welcome embed copy synced.

**Task Logs:**
- task-03-01.log.md
- task-03-02.log.md
- task-03-03.log.md

### Stage 2 — Invocation + Welcome

Two Tasks delivered the session state machine and the Discord-facing slash command + invocation guard + welcome surface. T2.1 ran clean; T2.2 needed two follow-up adjustments after first delivery.

T2.1 (`feat/session-state-machine`, commit `972e289`) shipped `app/session.py` with the `SessionState` enum, `Session` dataclass, `SessionRegistry` orchestrator (in-memory + SQLite in lockstep, channel-exclusivity invariant), 19 new tests covering happy path, refusals from each state, parallel-channel safety, channel exclusivity, handoff, and registry lookups. Also pinned `pytest-asyncio` to `strict` mode in `pyproject.toml` (silencing the deprecation warning carried over from Stage 1) and added `tests/conftest.py` with a stub-token fixture so the suite runs without a live `DISCORD_BOT_TOKEN`.

T2.2 (`feat/slash-command-welcome`, six commits) shipped `app/bot.py` with `discord.Client` + command tree, the cumulative invocation guard (channel-type → in-voice → no-active-session), the welcome embed with timer-pick button row using the `teamode:<session_id>:timer:<value>` namespace, and full entry-point wiring in `teamode.py` (config → init_db → reconcile → registry → bot). Also extended `app/config.py` with `TEAMODE_DEV_GUILD_ID` for guild-scoped command registration. Three follow-ups during review: (1) worker-invented welcome copy violated the "no LLM-generated runtime output" rule — User wrote canonical copy, added to UI-ADR § "Welcome embed copy"; (2) bug in event handler registration (`_on_ready` vs `on_ready` — `client.event` uses `__name__`, leading underscore meant the handler never fired and slash commands never synced) caught during smoke test, fixed in commit `006694f`; (3) User reformatted the welcome copy as a bullet list in commit `87ef94e`, UI-ADR synced. Also added `docs/discord-bot-setup.md` (developer-portal walkthrough with intent/permission table, OAuth scopes, perms integer `2150714432`).

Stage verification: full validation pipeline clean on `main` post-merge (56 tests pass, ruff clean, pyright 0 errors, scan clean) **plus** manual Discord smoke test in dev guild — all four guard cases (wrong-channel, not-in-voice, guard-pass, session-already-active) confirmed by User.

**Task Logs:**
- task-02-01.log.md
- task-02-02.log.md

### Stage 1 — Foundation

Two Tasks delivered the package skeleton, env loader, and the SQLite layer for the session lifecycle. Both ran sequentially on Sonnet `apm-worker` subagents on dedicated `chore/*` branches; both passed the full validation pipeline (`ruff format`, `ruff check`, `pytest`, `pyright`, `scan_injection`) on first review.

T1.1 (`chore/package-scaffolding`, commit `4139ee2`) created `app/__init__.py`, `app/config.py` with strict `DISCORD_BOT_TOKEN` enforcement (raise on missing/empty, no token logging), `teamode.py` entry stub, `requirements.txt` with exact pins (`discord.py[voice]==2.7.1`, `python-dotenv==1.2.2`, `pytest==8.3.5`, `pytest-asyncio==0.26.0`, `ruff==0.11.13`, `pyright==1.1.398`), `.env.example`, and four `tests/test_config.py` cases via `monkeypatch` + `importlib.reload`. The worker's "important finding" about `app/` vs `teamode/` was a false positive — they conflated the repo-root directory name with the package directory.

T1.2 (`chore/sqlite-schema`) needed one follow-up cycle. Initial commit `764f5ff` implemented the schema and ten write helpers correctly per `docs/sqlite-schema.md`, but flagged that the schema doc's `NOT NULL` constraints on `started_at` and `duration_minutes` conflicted with the lifecycle (those columns are unknown at `pending` insert). Worker worked around it with sentinel values (`_now_utc()` and `0`). Manager surfaced the conflict to User; chose Option A — fix the schema doc. Doc correction (`cfa7572`) relaxed both constraints to nullable and expanded the documented `status` enum to include `pending`, `intention_set`, `followup`. Follow-up worker (`b96b0bd`) revised `app/db.py` to omit those columns at INSERT (true NULL), updated tests to assert NULL on insert and non-NULL after the corresponding transitions. Final state: 29 tests covering every helper plus reconciliation (both branches), no sentinel values in the data path.

Stage verification on `main` post-merge: full pipeline clean, 29 tests green.

**Task Logs:**
- task-01-01.log.md
- task-01-02.log.md

