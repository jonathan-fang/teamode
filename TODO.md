# TODO

Backlog for TeaMode. Structure follows `.project-meta/conventions.md`
§ "Backlog & Release Scoping."

This file is the inbox + holding pen for ideas that aren't in flight.
The active project work is tracked in `.apm/plan.md` once Work
Breakdown is complete — not here.

---

## Next Patch

_Empty — no patches scoped yet (V1 has not shipped)._

---

## Next Minor

_V1 work is tracked in `.apm/plan.md` once the Planner approves it.
This section will populate after V1 ships._

---

## Next Major

_Empty._

---

## Future

Valid ideas blocked on an external trigger or deferred until after V1
ships. Promote to a release-target queue when ready.

### v2 — sharing and reach

- **Shareable to one external server.** README + token + slash command
  registration walkthrough so a colleague can clone, configure, and
  run on their own server within 30 minutes. Blocked on: V1 stable
  for a week of real usage.
- **VPS hosting path.** Deploy guide + systemd unit + secrets
  handling for always-on operation. Blocked on: external server
  onboarding.

### v2 — participant capture

The MVP keeps participant intentions and follow-ups social only — the
bot prompts but does not log. Two capture options were discussed and
deferred:

- **Capture via chat-window listener.** Bot posts the participant
  intention prompt and listens for chat messages from voice-channel
  members during a 60-second window. Each message logged per-user.
  Requires Message Content Intent (the gateway intent for reading
  channel messages) and a participants table. Blocked on: deciding
  whether the look-back data is actually useful.
- **Capture via per-user modal.** Bot posts a "Share my intention"
  button anyone in voice can click; each click opens a personal modal,
  submissions logged per-user. No Message Content Intent needed.
  Cleaner privacy story than the listener. Blocked on: same.

### v2 — UX polish

- **Embed with progress bar on the active timer.** Replace the plain
  `mm:ss` text edit with a sage-accent embed that includes a unicode
  progress bar (`▰▰▰▰▱▱▱▱▱▱`). Blocked on: confirming the edit
  cadence behaves well at production load.
- **Chained sessions.** "Go again? / Take a 5-minute break?" prompt
  after the follow-up answer. Blocked on: V1 stable.
- **ASCII teacup banner on welcome.** Cute flourish, low effort.
  Blocked on: nothing — just deferred to keep V1 minimal.
- **Custom avatar art.** Replace the placeholder avatar with a
  designed teacup/kettle/steam image. Blocked on: someone making one.
- **`/teamode-stats` command.** Surface the SQLite log via a Discord
  command instead of requiring `sqlite3` CLI. Blocked on: deciding
  what the surface looks like (embed? CSV upload? graph?).

### v2 — bookkeeping

- **Participant snapshot at session start.** Record who was in the
  voice channel when the session started — useful for stats but adds
  a Discord API call. Blocked on: capture-flow decision above.

### v1.x — Discord application identity assets

- **Application icon.** 1024×1024 PNG/JPG/GIF/WEBP, ≤ 10 MB, 1:1
  aspect ratio. Shown in the developer portal and as the bot user's
  avatar. No source asset yet; align style with the matcha-sage /
  steeping-forest palette in `.project-meta/UI-ADR.md`.
- **Application banner.** 680×240 PNG/JPG/GIF/WEBP, ≤ 10 MB, 17:6
  aspect ratio. Shown on the application's developer-portal page.
  Same style direction as the icon.

### v1.x — code organization

- **Rename `app/bot.py` → `app/discord_bot.py` (or similar).**
  Becomes worth doing if a second bot integration ever lands (slack
  webhook, web dashboard, etc). Today the project is Discord-only and
  `bot.py` is unambiguous within `app/`. Cascade: `teamode.py` import,
  three `tests/test_bot_*.py` patch points (`app.bot.X`), references
  in `AGENTS.md`, `.apm/plan.md`, `.apm/spec.md`. Defer until a real
  second integration creates the ambiguity.

### v1.x — intention modal flexibility

- **Allow empty modal submission.** Spec § `intention` already says
  "Empty string allowed (intention is optional in the flow)" but
  T3.2's worker shipped `required=True`. Flip to `required=False` and
  handle the empty case in `_ACTIVE_TIMER_FMT` — proposed fallback
  display: `🍵 Facilitator's Intention: (none)\n<duration> min session\n⏳ MM:SS`,
  or `🍵 Focus session\n<duration> min session\n⏳ MM:SS`. Pick one
  before merging. Some facilitators prefer to speak their intention
  rather than type it.

### v1.x — countdown wrap-up message

- **Three-minute wrap-up nudge.** When the countdown reaches 180 s
  remaining, post a one-time channel message: `⏳ Three minutes left
  — start to wrap up your task. We're nearing the end of the session.`
  Edge cases: don't fire if `mark_cancelled` happened first; sessions
  shorter than 3 min (none in the 10/25/50 set, but worth a guard).
  Could fold into V2 timer "phase label" instead — see below.

### v2 — embed timer with progress and phase labels

Inspired by `dlqa`'s `FocusTimerWidget` (`~/WSL/.../dlqa/app/ui/widgets.py:173`).
Replace the plain-text active timer with a `discord.Embed` that
renders four stacked sections per tick:

1. **Title** — `🍵 TeaMode • <duration> min session`.
2. **Embed fields** — `Intention`, `Facilitator`, `Started at`
   (Discord renders these in a dedicated card layout, less squashed
   than a one-liner edit).
3. **Phase label** — a contextual line that the bot swaps based on
   time remaining: `Deep focus` for the bulk of the session,
   `Wrap up — finish your current task` for the last 3 minutes.
   Unifies the v1.x wrap-up nudge above with the timer visual itself
   (no separate channel message needed).
4. **Countdown + progress** — `MM:SS remaining` plus an ASCII
   progress bar (`█████░░░░░ 50%`). The "remaining" suffix is a
   small UX win for clarity.

Accent color: matcha sage `#7B9D6F` (active), shifts to a different
hue (e.g. oolong amber) for the wrap-up phase. Mobile rendering wins
because embeds get a dedicated card.

---

## Notes

Inbox for loose observations and monitoring items. Triage at the end
of each release cycle. Items under the 7-day waiting period stay here
until promoted.

_Empty — pre-implementation._
