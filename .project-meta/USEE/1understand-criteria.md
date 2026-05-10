# 1. Understand — Criteria

Phase 1 of USEE (Understand, Strategize, Execute, Evaluate). Captures
*what* TeaMode is and *what success looks like*. Read before opening any
APM session so the work to be done is grounded in the problem, not the
implementation.

---

## What TeaMode is

A self-hostable Discord bot that runs a guided FLOWN/Groove-style
co-working session. Replaces the Japanese `simple-timer` bot the
facilitator currently uses — same problem (structured focus session in a
voice channel) but built so the facilitator owns the tooling and can shape
the flow over time.

The bot ports the spirit of dlqa's focuswork routine — countdown timer,
intention capture, follow-up reflection, reverie chime — into Discord.

## Who uses it

- **Facilitator (primary user, V1):** the repo owner. Invokes
  `/teamode`, picks duration, sets intention, runs sessions in a voice
  channel with 1–3 friends.
- **Co-workers (incidental users, V1):** friends in the voice channel.
  See the bot messages, may react during the follow-up window. No
  authoritative role.
- **External self-hoster (V2):** a single other Discord server interested
  in running the bot. Setup story must be tractable for someone with
  basic Python.

## What success looks like

1. The facilitator can run a real focus session through the bot end-to-end
   — invoke, pick timer, write intention, focus, hear reverie, answer
   follow-up, see the row in SQLite — without reaching for the Japanese
   `simple-timer` bot.
2. The session log accumulates over time so the facilitator can look back
   at completed sessions, intentions, and follow-up notes.
3. The bot is stable enough that a 50-minute session does not require
   intervention.
4. The facilitator can hand off the bot to one external server with a
   README + token + slash command registration — no consulting required.

## What it explicitly is *not*

- Not a 24/7 service. MVP runs on demand (WSL on the facilitator's
  laptop).
- Not a multi-tenant SaaS. Each instance is self-hosted per server.
- Not a productivity tracker beyond the session-log table. No streaks,
  XP, gamification (those live in dlqa).
- Not a replacement for FLOWN. FLOWN is a video co-working platform; this
  is a Discord-native, smaller-scope alternative.

## Non-goals (explicit)

- Web dashboard for stats — defer indefinitely.
- Cross-server analytics — out of scope.
- AI-generated reflection prompts — out of scope; runtime AI text is
  prohibited per `.project-meta/conventions.md`.
- Voice transcription, presence analysis, or anything beyond the
  scripted step flow.

## Success metrics (subjective, MVP-appropriate)

- Facilitator runs at least 5 real sessions through TeaMode without
  reverting to the Japanese bot.
- Session log accurately reflects every session; no missing or corrupt
  rows after a week of use.
- Voice playback of `reverie.wav` succeeds in ≥ 9 of 10 sessions
  (graceful degradation to text mention is acceptable).
- A colleague can clone the repo, follow the README, and have the bot
  running on their server within 30 minutes (V2 only).

## Open questions to revisit during Evaluate

- Does the 10/25/50 timer set reflect actual usage, or do real sessions
  cluster at one duration?
- Does the reaction window add value, or do co-workers ignore it?
- Is the SQLite schema rich enough, or are we wishing for participant
  tracking after a month?
