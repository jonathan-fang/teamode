# 2. Form — Strategy

Phase 2 of USEE. Captures *how* we plan to deliver the criteria from
`1understand-criteria.md`. The high-level shape of the work, the order it
lands in, and the architectural commitments that bound it.

---

## Architectural commitments

- **Language / library**: discord.py (Python). Inherits the existing
  toolchain (ruff, pyright, pytest) from `dlqa` and `dawa`. See
  `docs/language-library-comparison.md` for the comparison.
- **Persistence**: SQLite from day one. One `sessions` table per
  `docs/sqlite-schema.md`. No relational complexity for MVP.
- **Hosting**: WSL on the facilitator's laptop, on demand, for MVP.
  Migrate to a cheap VPS only when V2 onboards a second server. See
  `docs/language-library-comparison.md` for hosting tradeoffs.
- **Concurrency model**: one `asyncio` task per active session, keyed by
  `session_id`. Sessions in different text channels run independently.
  Same-channel concurrency is forbidden (friendly refusal).
- **Voice connection**: bot joins the facilitator's voice channel at
  session start, holds the connection for the full timer, plays
  `reverie.wav` at zero, then disconnects.
- **Source-of-truth file layout**: business logic in an importable
  module (`teamode/`), thin entry-point at repo root (`teamode.py`)
  per the `.project-meta/conventions.md` separation-of-concerns rule.

## Stage shape (provisional — locked during APM Planning)

The Spec/Plan in `.apm/` is authoritative. This is a strategic sketch.

1. **Foundation** — repo scaffolding, dependencies, bot registration
   docs, SQLite schema migration, env-var loader.
2. **Slash command + welcome** — `/teamode` registered, voice-channel
   guard, welcome embed.
3. **Timer pick + intention modal** — button row, modal capture, write
   row to `sessions` table.
4. **Countdown loop + voice connect** — bot joins voice, edit cycle
   every 10s, in-flight refusal logic.
5. **End-of-session + reverie + follow-up** — reverie playback,
   follow-up Y/N + optional "why" text, reaction window with
   3-min timeout, facilitator early-end button.
6. **Edge cases** — facilitator leaves voice (handoff or 5-min grace),
   bot reconnect after gateway drop, SQLite reconciliation on startup
   for crashed sessions.
7. **Cleanup + release** — README, validation gates, V1 tag.

## What we're deliberately deferring

- Embed-with-progress-bar timer surface (v2 polish; MVP is plain text
  cycling `mm:ss`).
- Chained sessions ("go again? / 5-min break?") — defer to v2.
- Stats command (`/teamode-stats`) — facilitator can `sqlite3 sessions.db`
  for now.
- Cross-server distribution — V2 once V1 is stable.

## Risks and how we'll handle them

| Risk | Likelihood | Mitigation |
|---|---|---|
| Voice connection drops mid-session | Medium | discord.py auto-reconnects; fallback to text mention if reverie playback fails. |
| Bot process dies (laptop sleep) | Medium | SQLite reconciliation on startup marks orphaned `active` rows as `crashed`. Facilitator notified at next start. |
| Discord rate limit on edit cycle | Low at 10s cadence | Skip edit if previous still in flight; exponential backoff on 429. |
| Modal text captures something embarrassing on accident | Low | Modal text is logged only; no public display unless facilitator chooses to share. |
| Termux/voice unverified path | High if attempted | Don't attempt for MVP. WSL host avoids this. |

## Decisions still pending strategy-level resolution

None at the strategy level — all material decisions captured during
Context Gathering. Tactical decisions (exact embed wording, button
labels, etc.) belong in UI Decisions during APM Planning.
