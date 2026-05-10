# TeaMode

A self-hosted Discord bot that runs FLOWN/Groove-style guided co-working
sessions in voice channels. Built around a single command — `/teamode` —
that walks you and your friends through a focus block: pick a duration,
write your intention, focus, hear the reverie chime, reflect.

The bot user is named **Ocha** (お茶 — tea). It's tiny, opinionated, and
designed to replace the Japanese `simple-timer` bot a small group of
friends were already using.

> **Status:** pre-MVP. Planning complete; implementation not yet started.
> This README describes the bot's intended shape; sections marked
> _planned_ aren't usable yet.

---

## What a session looks like

```
/teamode  ←  invoked from a voice channel's text chat,
              by someone who is in the voice channel

  🍵 Welcome to TeaMode! Take a sip of a beverage of your choice,
     tidy your desk, and get rid of any distractions like phones
     or irrelevant tabs.

     [ 10 ]  [ 25 ]  [ 50 ]   ← pick a timer

  ⌨  Modal: "What's your intention for this session?"

  🍵  Intention: Finish the v26Q2 changelog.
  ⏳  24:50 remaining            ← edits every 10 seconds

       …focus block, bot stays silently in voice…

  🍵  Time's up — tea time!     ← reverie chime plays in voice
  🌿✨

       Did you accomplish your intention?
       [ Yes ]  [ No ]           ← facilitator answers
       👍 / 👎 reactions open to anyone in the voice channel for 3 minutes

  ✓ Session logged.
```

Every session is recorded to a local SQLite database — duration,
intention, follow-up answer — so you can look back at what you've done
and what you set out to do.

---

## Features

- **Single slash command**, no setup ceremony per session. `/teamode`,
  pick a duration, write an intention, focus.
- **Voice-channel-aware.** The bot joins the voice channel you're in
  and chimes `reverie.wav` through the channel when the timer ends.
- **Multi-user friendly.** You and your co-workers all see the same
  session message. Facilitator drives; everyone can react.
- **Multi-session safe.** Two facilitators in two different channels
  can run sessions in parallel. Same-channel concurrency is gently
  refused.
- **Local persistence.** SQLite at `./sessions.db` (configurable). No
  cloud, no telemetry.
- **Calm aesthetic.** Matcha-sage embeds, 🍵 + ⏳ emoji pair, no
  AI-generated text — every string Ocha says was written by a human.

---

## Self-hosting

### Requirements

- Python 3.11+
- `ffmpeg` on `PATH` (for voice playback)
- A Discord application with a bot user — see
  [Discord Developer Portal](https://discord.com/developers/applications)
- The bot invited to your server with `applications.commands`,
  `Send Messages`, `Connect`, and `Speak` permissions

### Install

```bash
git clone https://github.com/jonathan-fang/teamode.git
cd teamode
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # planned
```

### Configure

Set the bot token (and optionally a custom database path) via
environment variables:

```bash
export DISCORD_BOT_TOKEN="..."          # required
export TEAMODE_DB_PATH="./sessions.db"  # optional; this is the default
```

Or put them in a `.env` file at the repo root (gitignored).

### Run

```bash
python3 teamode.py   # planned
```

The bot logs in, registers `/teamode` as a guild-scoped command on
your server, and waits for invocations.

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

## How sessions are guarded

| Situation | What happens |
|---|---|
| You invoke `/teamode` from a regular text channel | Refused: must be a voice channel's text chat |
| You invoke `/teamode` but you're not in a voice channel | Refused: join voice first |
| Another `/teamode` is already running in this channel | Refused (privately) — pick another channel |
| You leave voice mid-session (others remain) | A random remaining voice member becomes facilitator |
| You leave voice mid-session (solo) | 5-minute rejoin grace; otherwise session marked incomplete |
| Bot loses its websocket | Auto-reconnects; the timer keeps running |
| Bot process dies | Session is marked `crashed` on next startup |

---

## Repo layout

```
teamode/
├── teamode.py                 ← entry point (planned)
├── teamode/                   ← package: bot, session, voice, db (planned)
├── assets/reverie.wav         ← end-of-session chime
├── docs/                      ← Discord platform notes, schema, comparisons
├── tests/                     ← pytest suite (planned)
├── .project-meta/             ← project conventions, UI-ADR
├── .LLMAO/                    ← development workflow docs
├── .project-meta/USEE/        ← project-knowledge framework
└── .apm/                      ← APM session artifacts
```

If you're contributing, start with [`AGENTS.md`](AGENTS.md) →
[`.project-meta/conventions.md`](.project-meta/conventions.md).

---

## What's intentionally out of scope

- Chained sessions ("go again? / 5-minute break?") — planned for v2.
- Embed with progress bar — planned for v2.
- A `/teamode-stats` command — for now, query SQLite directly.
- Web dashboard, cross-server analytics, AI-generated reflection
  prompts, voice transcription. Not coming.

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

Unlicensed — all rights reserved. Personal project; not currently open
for redistribution.
