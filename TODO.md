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

- **Custom avatar art.** Replace the placeholder avatar with a designed
  teacup/kettle/steam image.

- **Discord application identity assets — approved for creation.**
  - Application icon: 1024×1024 PNG/JPG/GIF/WEBP, ≤ 10 MB, 1:1 aspect
    ratio. Shown in the developer portal and as the bot user's avatar.
    Align style with the matcha-sage / steeping-forest palette in
    `.project-meta/UI-ADR.md`.
  - Application banner: 680×240 PNG/JPG/GIF/WEBP, ≤ 10 MB, 17:6 aspect
    ratio. Shown on the application's developer-portal page. Same style
    direction as the icon.

---

## Next Major

_Empty._

---

## Future

Valid ideas blocked on an external trigger or deferred until after V1
ships. Promote to a release-target queue when ready.

### v2 — bookkeeping

- **Participant snapshot at session start.** Record who was in the
  voice channel when the session started — useful for stats but adds
  a Discord API call. Blocked on: participant-capture decision (see
  `docs/external-interest-log.md` — postponed).

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
- **`/teamode-clear` permission refusal — manual Discord check
  postponed; observe in production.** Run `/teamode-clear` as a member
  without Manage Messages and confirm the ephemeral refusal "You need
  the Manage Messages permission to run /teamode-clear." (other smoke
  steps passed; delete pacing via `CLEAR_DELETE_INTERVAL_SECONDS`).
