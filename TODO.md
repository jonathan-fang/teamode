# TODO

Backlog for TeaMode. Structure follows `.project-meta/conventions.md`
§ "Backlog & Release Scoping."

This file is the inbox + holding pen for ideas that aren't in flight.
The active project work is tracked in `.apm/plan.md` once Work
Breakdown is complete — not here.

---

## Next Patch

_Empty._

### Groove Boogaloo pre-deployment checklist

Items to investigate and resolve before deploying to the Groove Boogaloo
testing server. See `docs/groove-boogaloo-deployment.md` for admin context.
Per-user rate limiting and the `ffmpeg` probe shipped in `v26Q3.0.0.0`
and satisfy this checklist. Intention text privacy and data
anonymization were also originally scoped here — see
`docs/external-interest-log.md` for why they're postponed.

---

## Next Minor

_Empty._

---

## Next Major

_Empty._

---

## Future

Valid ideas blocked on an external trigger or deferred until after V1
ships. Promote to a release-target queue when ready.

### v2 — bookkeeping

_Empty._

### v1.x — code organization

- **Bump discord.py to 2.8 when released** (resolves the PyNaCl
  `PYSEC-2026-1448` / `PYSEC-2026-3002` pin — see `changelog.md` §
  `v26Q3.0.0.0` Known issues).

- **Five background coroutines catch `asyncio.CancelledError` and
  `return` instead of re-raising** (watchdog, solo grace, pending
  expiry, break, Go-again timeout). `asyncio.CancelledError` should
  propagate on cancellation per convention; audit and fix each site.

- **~10 harmless "coroutine was never awaited" test warnings** from
  mocked `create_task` in the test suite. Cosmetic — tests pass — but
  worth silencing at the source (return a real awaited coroutine or an
  `AsyncMock` configured to avoid the warning) rather than living with
  the noise.

- **`voice.play_reverie()` is dead in production** — only
  `tests/test_voice.py` calls it directly; the real runtime path
  (`voice.play_reverie_then_disconnect()`, used by `lifecycle.py` and
  `breaks.py`) reimplements the same `voice_client.play(FFmpegPCMAudio(
  REVERIE_PATH), after=...)` call inline instead of calling
  `play_reverie()`, because `play_reverie()` has no `after` parameter.
  Ruff doesn't flag this as unused since the tests reference it. Fix:
  add an optional `after` parameter to `play_reverie()` and have
  `play_reverie_then_disconnect()` call it, removing the duplicated
  `play()` call — do not merge `play_reverie()` with
  `play_wind_chime()` (their guard/exception/return-type contracts
  differ for good, caller-driven reasons: the wind chime fires inside
  the live timer edit loop and must never raise, reverie playback
  propagates errors to `play_reverie_then_disconnect()` by design).

- **Add GitHub Actions CI + swap README badges from static to live.**
  README currently carries static shields.io badges (python/pytest/
  pyright/ruff/platform/version) hand-updated at time of writing —
  they will silently drift as the suite grows. Trigger to act: (1) a
  `.github/workflows/` CI file exists that actually runs
  ruff format --check / ruff check / pytest / pyright on push, (2) it
  has run at least once so a status exists to show, and (3) the repo
  is public (or a shields.io GitHub token is wired up) — private repos
  won't render a status badge without that. Until all three hold,
  leave the badges static.

### Shelved

- **Remove the "Time's up!" message 3 minutes after session completion.**
  Shelved (not tied to external interest — just not a priority right
  now). Revisit on its own merits later, independent of the external-
  interest items in `docs/external-interest-log.md`.

---

## Notes

Inbox for loose observations and monitoring items. Triage at the end
of each release cycle. Items under the 7-day waiting period stay here
until promoted.

- **Long-break streak and break voice — manual Discord check postponed;
  observe in production.** The 5-step smoke checklist was not run before
  merge: (1) two chained ≥ 25-min sessions → prompt offers "Take a
  10-minute break" and lists the durations; (2) clicking it posts "Break
  started", Ocha joins voice and shows `⏸️ to HH:MM`, staying connected;
  (3) at break end the status shows `✨ Break over at HH:MM`, reverie
  plays, Ocha leaves, "Break is over" + Go again appears; (4) the next
  chain prompt is back to the normal 5-minute offer; (5) `/teamode`
  during a break makes Ocha leave voice, edits the message to "Break
  cancelled by /teamode", and the new session connects normally.
- **`/clear` permission refusal — manual Discord check
  postponed; observe in production.** Run `/clear` as a member
  without Manage Messages and confirm the ephemeral refusal "You need
  the Manage Messages permission to run /clear." (other smoke
  steps passed; delete pacing via `CLEAR_DELETE_INTERVAL_SECONDS`).
- **Participant tracking — manual Discord check postponed; test in
  production.** Merged untested live. (1) Two humans in voice →
  `/teamode`, pick a duration, submit an intention; (2) a third human
  joins voice while the timer runs; (3) optionally one of the first two
  leaves and rejoins; (4) run
  `sqlite3 -readonly sessions.db "SELECT * FROM session_participants ORDER BY session_id DESC LIMIT 20;"`
  — expect the first two with `joined_late=0`, the third with
  `joined_late=1`, the rejoiner still `0`, and no row for Ocha.
- **Participant-aware `/stats` — manual Discord check postponed; test
  in production.** A user who only joined (did not facilitate) a
  completed session runs `/stats` → "You" shows that session and its
  minutes with "— completed"; the facilitator's "You" completion rate
  is unchanged.

Command naming — resolved: `/teamode-clear` and `/teamode-stats` were
shortened to `/clear` and `/stats`; `/teamode` and `/handoff` stay
as-is. Discoverability handled via Discord's per-app command filter
(type the bot's name, e.g. `/ocha`, in the slash-command picker) rather
than prefixing every command with `teamode-` — documented in README.

Automatic RNG handoff — resolved: verified live in Discord 2026-10-01
(facilitator leaves with others remaining → session reassigned);
recorded in `changelog.md` § Unreleased.
- [ ] Apparently ocha doesn't need manage messages to delete it's own messages, including old ones? So I could have it so that anybody can trigger it, is that desired? Minor to input in Todo md, not planning to touch it for another quarter. There will never be a time a codebase considered nothing can be improved or change because circumstances change .
- [ ] minor generate art doesn't really belong in git it's a one time thing ...? Also ai art controversial atm 