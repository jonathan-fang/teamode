# TeaMode

A self-hosted Discord bot that runs FLOWN/Groove-style guided co-working
sessions in voice channels. Built around `/teamode` — a facilitator-led
flow that walks you and your friends through a focus block: pick a
duration, write your intention, focus, hear the reverie chime, reflect —
plus `/handoff`, `/teamode-stats`, and `/teamode-clear` around it.

The bot user is named **Ocha** (お茶 — tea). It's tiny, opinionated, and
designed to replace the Japanese `simple-timer` bot a small group of
friends were already using.

> **Status:** `v26Q3.0.0.0` shipped. Chained sessions, breaks, the embed
> timer, `/teamode-stats`, and `/teamode-clear` are live. See
> `changelog.md` for what landed.

---

## What a session looks like

```
/teamode  ←  invoked from a voice channel's text chat,
              by someone who is in the voice channel

  🍵 Now Entering TeaMode
     ### Time for TeaMode!
     ### · Grab your tea (or water/beverage of your choice),
     ### · Clear your desk,
     ### · And silence all distractions (like phones, impromptu meetings).
     ### ⏳ How long would you like to focus today?

     🥅 [Set Intention]  @mentions  ← participant prompt (1 s after welcome)

     [ 5 min ]  [ 10 min ]  [ 25 min ]  [ 50 min ]   ← facilitator picks timer

  ⌨  Modal: "What will you focus on?"   (optional — can be left blank)

  🍵 TeaMode • 25 min session           ← embed, edits every 10 seconds
     Intention: Finish the v26Q3 changelog
     Facilitator: @you
     Range: 14:00 to 14:25
     Deep focus                        ← → "Wrap up" for the last 3 minutes
     24:50 remaining
     █████████░ 92%

  ⏰ Wrap-up nudge — 3 minutes left.    ← sessions ≥ 10 min, + wind chime

  ✨ Session complete!
     ### 🌿 Sip your tea, stretch, and notice your progress.
                                       ← reverie chime plays in voice

  🌿 [Reflect]
     ### Share how your session went!
     ### · React with emoji
     ### · Share in voice
     ### · Or type in chat
                                       ← pre-populated ✅/⛔ reactions;
                                          facilitator's reaction is
                                          authoritative (3-min window)

  Go again? / Take a 5-minute break?   ← anyone in voice can click either
```

Every session is recorded to a local SQLite database — duration,
intention, follow-up answer — so you can look back at what you've done
and what you set out to do, or check `/teamode-stats`.

---

## Features

- **`/teamode`** — pick a duration, write an intention, focus. Guarded
  invocation (must be a voice channel's text chat, invoker must be in
  voice, no concurrent session in the channel), per-user (3 per 5
  minutes) and per-guild (50/day) rate limits.
- **`/handoff @user`** — manually transfer the facilitator role to
  another voice-channel member. Also happens automatically if the
  facilitator leaves voice with others remaining.
- **`/teamode-stats`** — ephemeral summary of your sessions and this
  server's, over the last 7 days / 30 days / all time, plus your
  personal daily streak.
- **`/teamode-clear`** (requires Manage Messages) — deletes Ocha's own
  past TeaMode clutter from the last 200 messages in the channel,
  paced to stay under Discord's rate limits. Keeps timers, handoff
  notices, and anything belonging to a live session, chain prompt, or
  break.
- **Embed timer** with an intention/facilitator/range layout, a
  `Deep focus` → `Wrap up` phase shift, `MM:SS remaining`, and a
  progress bar. A wrap-up nudge (with a wind chime in voice) fires for
  sessions ≥ 10 minutes.
- **Chained sessions and breaks.** After each session, anyone in voice
  can click "Go again" or "Take a 5-minute break." After two chained
  sessions ≥ 25 minutes, the prompt offers a 10-minute break instead.
- **Voice-channel-aware.** The bot joins the voice channel you're in,
  chimes `reverie.wav` through the channel when the timer ends, and
  (while connected) shows a live status on the voice channel itself.
- **Multi-user friendly.** You and your co-workers all see the same
  session message. Facilitator drives; everyone can react.
- **Multi-session safe.** Two facilitators in two different channels
  can run sessions in parallel. Same-channel concurrency is gently
  refused.
- **Reliability.** A PID lock prevents two bot instances fighting over
  one token; a startup probe warns (non-fatally) if `ffmpeg` is
  missing; a crashed process is reconciled on next startup.
- **Local persistence.** SQLite at `./sessions.db` (configurable). No
  cloud, no telemetry.
- **Calm aesthetic.** Matcha-sage embeds, 🍵 + ⏳ emoji pair. The only
  AI-generated runtime text is the ASCII teacup banner on the welcome
  embed — a User-approved exception; every other string Ocha says was
  written by a human.

---

## Self-hosting

### Requirements

- Python 3.12+
- `ffmpeg` on `PATH` (for voice playback) — `sudo apt install ffmpeg`
  on Debian/Ubuntu (including WSL)
- A Discord application with a bot user — see
  [Discord Developer Portal](https://discord.com/developers/applications)
- The bot invited to your server (see Permissions below)

### Install

```bash
git clone https://github.com/jonathan-fang/teamode.git
cd teamode
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

Set these via environment variables (or a `.env` file at the repo
root, gitignored):

```bash
export DISCORD_BOT_TOKEN="..."                      # required
export TEAMODE_DB_PATH="./sessions.db"              # optional; this is the default
export TEAMODE_DEV_GUILD_ID="111...,222..."         # optional; comma-separated guild IDs
export TEAMODE_TIMEZONE="America/Los_Angeles"       # optional; IANA name, this is the default
```

- **`TEAMODE_DEV_GUILD_ID`** registers slash commands per-guild for
  instant propagation. If unset, the bot logs a warning at startup and
  **skips command registration entirely** — set it to your server's
  guild ID(s) or your commands won't appear.
- **`TEAMODE_TIMEZONE`** controls the wall-clock times shown in the
  timer embed and voice channel status, and the local-midnight reset
  for stats/streaks and the guild daily cap. An invalid IANA name logs
  a warning and falls back to the default; if even the default is
  unavailable, falls back to UTC.

### Run

```bash
python3 teamode.py
```

The bot logs in, syncs `/teamode`, `/handoff`, `/teamode-stats`, and
`/teamode-clear` to each guild in `TEAMODE_DEV_GUILD_ID`, and waits
for invocations.

### Launcher

For repeated local launches, `scripts/teamode_launcher.sh` sources
`~/.teamode-secrets`, activates the venv, and runs `python3 teamode.py`
in `dev` (default) or `stable` mode (a separate `git worktree`, for
running a known-good build alongside active development).

```bash
export DISCORD_BOT_TOKEN=...
export TEAMODE_DEV_GUILD_ID=111...,222...
export TEAMODE_TIMEZONE=America/Los_Angeles
```

Save that as `~/.teamode-secrets`, then:

```bash
chmod 600 ~/.teamode-secrets
```

A Windows desktop shortcut that launches the script inside Windows
Terminal is documented in
[`docs/windows-shortcut.md`](docs/windows-shortcut.md).

### Looking at your session log

```bash
sqlite3 sessions.db
> SELECT started_at, duration_minutes, intention, completed_intention
  FROM sessions ORDER BY started_at DESC LIMIT 10;
```

Field-by-field schema reference: [`docs/sqlite-schema.md`](docs/sqlite-schema.md).

### Hosting recommendation

For personal use, run TeaMode on your own machine on demand —
sessions only happen when you're working, so 24/7 hosting is overkill.
For multi-server use, a small VPS works well. See
[`docs/language-library-comparison.md`](docs/language-library-comparison.md)
§ "Hosting options" for a comparison.

---

## Permissions

Invite the bot with scopes `bot` + `applications.commands` and these
permissions (no privileged gateway intents required):

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Add Reactions
- Connect
- Speak
- Use Application Commands (labeled "Use Slash Commands" in the
  Developer Portal permissions list)
- Set Voice Channel Status

Combined invite permissions integer: **`281477127425088`**.

TeaMode does **not** request Manage Messages or Manage Channels — even
`/teamode-clear` runs under the invoking member's own permission, not
the bot's.

**Adding "Set Voice Channel Status" to an existing bot role:** open
Server Settings → Roles → the bot's role → toggle "Set Voice Channel
Status" on. If a voice channel has its own permission overrides (common
for private/locked voice channels), also check that channel's
permission overrides don't deny it to the bot's role.

Voice channel status only ever shows while Ocha is actually connected
to that channel (timer running, or on a break) — TeaMode deliberately
does not request Manage Channels to set a status while disconnected.

---

## How sessions are guarded

| Situation | What happens |
|---|---|
| You invoke `/teamode` from a regular text channel | Refused: must be a voice channel's text chat |
| You invoke `/teamode` but you're not in a voice channel | Refused: join voice first |
| Another `/teamode` is already running in this channel | Refused (privately) — pick another channel |
| You've hit the per-user rate limit (3 per 5 minutes) | Refused (privately) with seconds remaining |
| The server has hit its daily cap (50/day) | Refused (privately) until local midnight |
| You leave voice mid-session (others remain) | A random remaining voice member becomes facilitator |
| You want to hand the facilitator role to someone else manually | Run `/handoff @user` — they must be in the voice channel |
| You leave voice mid-session (solo) | 5-minute rejoin grace; otherwise session marked incomplete |
| A pending session (welcome shown, no duration picked) sits idle | Expires after 10 minutes — welcome edited to `🍵 Expired` |
| Bot loses its websocket | Auto-reconnects; the timer keeps running |
| Bot process dies | Session is marked `crashed` on next startup |
| Two bot instances start against the same token | The second exits — see the PID lock in `teamode.py` |

---

## Repo layout

```
teamode/
├── teamode.py                  ← entry point: PID lock, ffmpeg probe, startup order
├── app/
│   ├── discord_bot/            ← Discord wiring only (client, commands, views,
│   │                              timer, lifecycle, breaks, clear, stats, tasks)
│   ├── constants.py             ← every tunable + every Discord-facing string
│   ├── config.py                ← env var loading
│   ├── session.py               ← session state machine (Discord-free, testable)
│   ├── voice.py                 ← voice connect/play/disconnect
│   ├── db.py                    ← SQLite schema + writes
│   ├── rate_limit.py            ← per-user/per-guild rate limiting
│   ├── timer_format.py          ← mm:ss / progress bar formatting
│   ├── stats.py                 ← stats aggregation
│   ├── cleanup.py               ← /teamode-clear message classification
│   └── pidlock.py               ← single-instance PID lock
├── assets/                      ← reverie.wav, wind-chime.wav
├── scripts/                     ← teamode_launcher.sh, generate_art.py (dev-only)
├── docs/                        ← Discord platform notes, schema, comparisons
├── tests/                       ← pytest suite
├── .project-meta/               ← project conventions, UI-ADR
├── .LLMAO/                      ← development workflow docs
├── .project-meta/USEE/          ← project-knowledge framework
└── .apm/                        ← APM session artifacts
```

If you're contributing, start with [`AGENTS.md`](AGENTS.md) →
[`.project-meta/conventions.md`](.project-meta/conventions.md).

---

## Art assets

`scripts/generate_art.py` (Pillow, dev-only — see
`requirements-dev.txt`, never installed at runtime) deterministically
generates icon/banner/avatar candidates into a review folder
(`--out`, default `.debug-images/`). A person reviews the candidates
and places the chosen finals in `assets/` as `app-icon.png`
(1024×1024), `app-banner.png` (680×240), and `app-avatar.png`
(1024×1024). These are uploaded manually in the
[Discord Developer Portal](https://discord.com/developers/applications)
(App Icon, Banner, Bot icon) — TeaMode does not upload them
programmatically.

---

## What's intentionally out of scope

- Custom avatar/icon/banner art — generated but not yet finalized (see
  Art assets above).
- Web dashboard, cross-server analytics, AI-generated reflection
  prompts, voice transcription. Not coming.

---

## Sound credits

- `assets/reverie.wav` — by Seemant Chandra (Instagram:
  `piyush.x_x`).
- `assets/wind-chime.wav` — "Wind Chime" by GnoteSoundz, CC0 1.0.

---

## Credits

Carries the spirit of `dlqa`'s focuswork routine into Discord —
countdown, intention, reverie chime.

References:
- [FLOWN](https://flown.com/) — video co-working sessions; the
  facilitator-led structure inspired TeaMode's flow.
- Groove (RIP) — the body-doubling co-working app whose session
  rhythm this bot tries to keep alive.
- [Japanese Simple Timer](https://github.com/simple-timer) [Discord link to Japanese Simple Timer](https://discord.com/discovery/applications/757427376341778494)

---

## License

All rights reserved. Personal project; not currently open
for redistribution.
