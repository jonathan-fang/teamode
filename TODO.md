# TODO

Backlog for TeaMode. Structure follows `.project-meta/conventions.md`
§ "Backlog & Release Scoping."

This file is the inbox + holding pen for ideas that aren't in flight.
The active project work is tracked in `.apm/plan.md` once Work
Breakdown is complete — not here.

---

## Next Patch

- **PID file lock — prevent dual-instance interaction failures.** When two bot
  instances run against the same token simultaneously, Discord delivers each
  interaction event to both. One instance acknowledges first; the other crashes
  with `40060 Interaction already acknowledged` or `404 Unknown interaction`,
  and users see "This session is no longer active." Fix: on startup in
  `teamode.py`, write a PID file (e.g. `/tmp/teamode.pid`); if it already
  exists and that PID is alive, log an error and exit cleanly; if the PID is
  stale (process dead), overwrite and continue. Remove the file via `atexit` on
  clean shutdown. No new dependencies.

- **Tunables constants file.** Add `app/constants.py` holding the numbers
  that currently require a code change to adjust: allowed durations
  (`5, 10, 25, 50`), per-user rate-limit window/allowance/daily cap, and
  the wrap-up-nudge trigger time. Everything below that references a
  "configurable" number pulls from this file.

- **Per-user rate limiting (Option C).** Sliding 5-minute window per user:
  allow the first 2 invocations freely, block on the 3rd+ until the window
  clears. Ephemeral error message shows how many seconds remain. Combined with
  a per-guild daily cap of 50 invocations (resets at midnight, in-memory).
  Both checks happen at the top of the `/teamode` handler before session logic.
  No new dependencies. Approved approach. Numbers (window, allowance, cap)
  live in the constants file above.

- **`ffmpeg` startup probe.** At bot startup, run `shutil.which("ffmpeg")`;
  if `None`, emit a WARNING log line: `"ffmpeg not found on PATH — reverie
  playback will fail. Install ffmpeg before starting a session."`
  Non-fatal — the bot still starts. Also add a setup-step note in the
  README's Requirements section pointing to the install line. **Same
  README touch-up should also document `TEAMODE_DEV_GUILD_ID`** (comma-
  separated guild IDs for guild-scoped command sync — currently only in
  `app/config.py` comments, missing from README's Configure section) so
  it doesn't get lost as a separate task. Rationale: caught the hard way
  during T4.2 smoke testing — without ffmpeg,
  `FFmpegPCMAudio` raises and the helper short-circuits to disconnect, so
  the Reflect embed posts immediately and the bot appears to skip reverie
  silently.

- **Wrap-up nudge for longer sessions.** For sessions with duration ≥ 20
  minutes only, post a one-time channel message when N minutes remain
  (default 3, configurable in the constants file — was previously
  considered as a flat 5-minute nudge for all durations, narrowed to
  long-sessions-only + configurable trigger). Edge cases: don't fire if
  `mark_cancelled` happened first; guard against durations shorter than
  the trigger time.

- **Add mentions to the active timer message.** Not yet implemented —
  confirmed via code read that `_ACTIVE_TIMER_FMT` (`app/bot.py`) has no
  mentions. Match the same `@`-mention set used in the `[Set Intention]`
  prompt (`app/bot.py:909`), appended after the facilitator's intention
  line.

- **Delete welcome/set-intention messages after session ends.** After a
  session completes or goes incomplete, delete the "now entering TeaMode"
  welcome message and the `[Set Intention]` prompt to avoid cluttering the
  channel's text chat.

### Groove Boogaloo pre-deployment checklist

Items to investigate and resolve before deploying to the Groove Boogaloo
testing server. See `docs/groove-boogaloo-deployment.md` for admin context.
Per-user rate limiting and the `ffmpeg` probe above are part of this
checklist. Intention text privacy and data anonymization were also
originally scoped here — see `docs/external-interest-log.md` for why
they're postponed.

---

## Next Minor

- **Voice channel status updates.** discord.py supports this
  (`VoiceChannel.edit(status=...)`, confirmed against the installed
  library — requires the "Set Voice Channel Status" permission). Three
  states over a session's lifecycle:
  - On `/teamode` launch: `"🍵 Starting TeaMode"` (emoji prefix).
  - Once the timer is set: `"to HH:MM"` — the wall-clock time the
    session/regroup completes, 24-hour format, in the facilitator's
    timezone (need to figure out where that's read from; default to
    Pacific if unset).
  - On completion: `"Finished TeaMode at HH:MM"`.
  Supersedes the older "rename to HH:MM" note below with the fuller
  three-state spec.

- **Embed timer with progress bar and phase labels.** Replace the
  plain-text active timer with a `discord.Embed`: title
  (`🍵 TeaMode • <duration> min session`), `Intention`/`Facilitator`/
  `Started at` fields, a phase label (`Deep focus` → `Wrap up — finish
  your current task` for the last few minutes), and `MM:SS remaining`
  plus an ASCII progress bar (`█████░░░░░ 50%`). Accent color matcha
  sage `#7B9D6F`, shifting hue (e.g. oolong amber) for the wrap-up
  phase. Inspired by `dlqa`'s `FocusTimerWidget`
  (`~/WSL/.../dlqa/app/ui/widgets.py:173`). **Keep the plain `mm:ss`
  text-edit path too** — this is additive, not a replacement.

- **Chained sessions.** "Go again? / Take a 5-minute break?" prompt
  after the follow-up answer.

- **ASCII teacup banner on welcome.** Cute flourish, low effort.

- **Custom avatar art.** Replace the placeholder avatar with a designed
  teacup/kettle/steam image.

- **`/teamode-stats` command.** Surface the SQLite log via a Discord
  command instead of requiring the `sqlite3` CLI. Surface shape (embed?
  CSV upload? graph?) still to be decided during implementation.

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

- **Rename `app/bot.py` → `app/discord_bot.py` (or similar).**
  Becomes worth doing if a second bot integration ever lands (slack
  webhook, web dashboard, etc). Today the project is Discord-only and
  `bot.py` is unambiguous within `app/`. Cascade: `teamode.py` import,
  three `tests/test_bot_*.py` patch points (`app.bot.X`), references
  in `AGENTS.md`, `.apm/plan.md`, `.apm/spec.md`. Defer until a real
  second integration creates the ambiguity.

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

_Empty._
