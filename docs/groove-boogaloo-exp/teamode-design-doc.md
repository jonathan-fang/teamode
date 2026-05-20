# TeaMode/Ocha — What It Is and What It Does

MVP 2026.05.19

---

## What is Ocha?

Ocha is a Discord bot that runs a guided co-working session inside a voice
channel. The user types one slash command — `/teamode` — and it handles the rest:
countdown timer, end-of-session chime, and a follow-up check-in. That's it.

It's named after the Japanese word for tea. The bot user is called Ocha; the
project is called TeaMode.

---

## What a session currently looks like, step by step

1. A facilitator joins a voice channel and types `/teamode` in its text chat.
2. Ocha posts a message with buttons to pick a session length:
   **10 min / 25 min / 50 min.**
3. The facilitator picks a length. Ocha optionally asks for an intention
   (a short note on what you're working on — this is optional and can be
   skipped).
4. The session starts. Ocha posts a countdown timer that ticks down in
   real time.
5. When the timer hits zero, Ocha plays a soft chime into the voice channel
   (the "reverie" ring).
6. Ocha posts a follow-up embed asking how the session went — did you
   accomplish what you set out to do? Members react with an emoji to respond.
7. Done. The session is over.

The facilitator is the only one who can control the session (pick a length,
set an intention, end it early). Other members in the voice channel just
experience it.

---

## What Ocha can do right now

- Run a timed co-working session from a voice channel
- Let the facilitator set an optional intention before the session starts
- Show a live countdown timer
- Play an audio chime when time is up
- Ask a simple follow-up question at the end

---

## What Ocha cannot do

- Read message history or DMs
- Send direct messages to anyone
- Listen to or record voice audio
- See who else is on the server (only who's in the active voice channel)
- Do anything outside of a `/teamode` session

Discord itself controls what the bot is and isn't allowed to do through its
permissions system. The permissions Ocha holds are visible on the Discord
developer portal — happy to share a screenshot.

---

## What the MVP doesn't have yet

Ocha works, but it's an early version and there are a few things still on
the list before a community-wide rollout:

- **Data privacy cleanup.** Before deployment, I'll strip any user-identifying
  data from what gets logged. The stats I care about (session counts,
  durations, how sessions went) don't need to be linked to any specific person,
  and they won't be.
- **Rate limiting.** A small guard to prevent someone from spamming the
  command repeatedly in a channel.
- **Testing on Groove Boogaloo specifically.** I've been using this on
  another server I run, but it hasn't been tried on the Boogaloo server yet.

None of these are blocking for a first look — but they'll be done before
anything goes to the wider community.

---

## Possible future features

These are ideas, not promises. They only happen if people actually use Ocha
and find it useful:

- A channel status line showing how much time is left in a session
- Better always-on availability (home server or similar) if people want it
  running when I'm not on the server.

---

## Current Data & privacy, in plain language

When someone runs a `/teamode` session, Ocha logs: session length, when it
started and ended, and whether the facilitator indicated the session went well
or not. Before deployment, I'll remove any information that could be linked
to a specific user — the goal is anonymous aggregate stats only (how many
sessions happened, how long they ran, how they went).

Ocha does **not** log: who else was in the voice channel, message content,
DMs, or anything outside of an active session. Members who never use
`/teamode` have nothing collected about them.

All of this lives on my personal PC. There is no cloud service, no platform,
no third party involved.

---

## Availability

Ocha runs off my personal PC. When it's on and running, the bot is online.
When it's off, the bot is offline and `/teamode` simply won't respond.
At Groove Boogaloo's scale, this is less of a "traffic" problem and more of
a "is Jonathan around" problem.

This is intentional for the experiment phase. If people use it and want it
more reliably available, we can talk about next steps then. Nothing is
committed beyond the experiment.

---

*Last updated: May 19, 2026.*
