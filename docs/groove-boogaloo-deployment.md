# Groove Boogaloo Deployment — Negotiations & Q&A

Working document for the conversation with Groove Boogaloo admins about
deploying Ocha (the TeaMode bot) on their server.

**Throughline for every answer:** This is a free, optional, best-effort
experiment. I'm not selling anything. The downside is bounded — if it breaks,
the core Discord server is unaffected.

---

## Stakeholder Interests

### Admin interests
- Security: no harm to server members or server itself
- Liability: no financial exposure to the server, its admins, or its members
- Reliability: clear expectations so members aren't confused or disappointed
- Transparency: understanding what the bot does, what data it touches, who is
  responsible for what

### Developer interests (Jonathan)
- Real-world proof of concept: I built this, it works on another server I run,
  I want to see if Groovers find it useful
- Usage data: session stats — session count, session duration, follow-up emoji
  outcomes (did people feel they succeeded or struggled) — for my own curiosity
  as the developer. The current DB design links sessions to Discord user IDs
  (see Security & Privacy). This data is not sold, shared, or monetized. The
  SQLite database that logs this is part of the existing design, not a new data
  collection decision. An open item before deployment is to review what needs
  to be retained vs. stripped.
- Portfolio / career: if this proves useful in the real world I may eventually
  open-source it, use it as a portfolio piece for future job searches, or
  explore partnerships. I retain all rights for now.
- No profit motive on this server.

---

## Admin Questions, Organized

### 1. Security & Privacy

**Q: How secure is a free host? What is the host pulling from end users?**

There is no external host. The bot runs off my personal PC. The only party
with access to anything is me.

The bot itself collects the following per session, stored in a local SQLite
database on my machine:
- Discord user ID (numeric, not username) of the session facilitator
- Session duration chosen
- Session start/end timestamps
- Follow-up emoji response (✅/❌ or equivalent)
- Intention text typed into the modal — **see note below**

The bot does **not** collect: message history, DMs, voice audio, member lists,
or any data outside of a `/teamode` session. Members who never run `/teamode`
have nothing collected about them.

**Note on intention text:** The current MVP logs intention text to the database.
Before deploying to Groove, I intend to make this opt-in or restrict it to my
own account only. This is a known open item — see TODOs.

**Note on user IDs:** Whether to retain Discord user IDs or strip/hash them
before long-term storage is an open question before deployment — see TODOs.

**On Discord and privacy generally:** Discord is already a third-party platform
with its own data practices. This bot only operates within what Discord's
permissions system allows, and people who don't wish to use it never have to
interact with it.

Discord itself enforces what the bot can and cannot do via its permissions
system. The permissions I've requested are visible on the Discord developer
portal and I'm happy to share a screenshot.

---

### 2. Hosting & Availability

**Q: Where will it be hosted? What are the capabilities and limitations?
What's the expected uptime?**

**There is currently no external host.** The bot runs off my personal PC.
It is live when my PC is on and I've started it. When my PC is off, or I stop
the process, the bot is offline. Discord will show the bot as offline and any
attempt to run `/teamode` will simply fail to respond — no crash, no error
cascade, just unavailable.

This is intentional for the experiment phase. At worst this is the exact same
status quo Groovers have had for the past year — the bot simply doesn't exist
and people Discord normally.

If the bot proves popular enough that people want it available when I'm not
running it, I would consider the following options in order:
1. A Raspberry Pi or micro-PC running as a home server — always-on, still
   mine, no third-party host
2. A small self-managed VPS — I bear the cost, no exposure to the community
3. A voluntary donation model to offset server costs — entirely optional and
   transparent, never mandatory

I am not currently planning to use a free or paid VPS, and none of these
decisions need to be made now.

**Expected uptime:** Best-effort. I'll run it when I'm around. This is an
experiment, not infrastructure.

---

### 3. Cost & Financial Liability

**Q: What happens at limits? Who bears the charge? What if you need to collect
money from us?**

Running off my PC costs nothing beyond my existing electricity bill. There is
no hosting bill, no metered usage, no credit card on file with a third party.

If I eventually move to a home server, I bear that cost personally. I do not
intend to solicit donations or collect money from the community or its admins
at this stage.

If someday there were a donation model, it would be entirely optional and
transparent — people could see how much the server costs and decide whether to
contribute. But that is hypothetical; right now there is no cost to pass on.

**The admins and the community bear zero financial liability.** There is no
scenario in which using this bot results in a charge to the server, its admins,
or its members.

If demand somehow surges unexpectedly, I'll throttle access or temporarily
take down the bot and prepare a response. At that point I'd work with the
admins to understand why demand spiked and decide together whether it makes
sense to scale up. The bot is not mandatory for the Discord server to function
— at worst it's the status quo.

---

### 4. Support & Maintenance

**Q: Who provides customer service? What happens when it breaks or behaves
unexpectedly?**

I do, on a best-effort basis. This is a free service and support reflects that.

**When it breaks:** It won't work. Users can DM me on the Groove Discord and
I'll note it. I'll either fix it within a few days when I have time, or log it
in a known-issues doc (likely a simple web page or pinned message). I'm not
running an on-call rotation for a free bot.

**When it behaves unexpectedly:** Same path — DM me, I'll investigate. At its
core this is a Python bot with a narrow set of Discord permissions. It cannot
send DMs, read message history, or do anything outside what those permissions
allow.

**Response times:** Variable. I'm a developer working on this in my free time.

I'll include clear expectations in any announcement to the community so no one
is surprised by this. If it breaks, it's like the bot never existed — the
same status quo as the past year. The core Discord server is completely
unaffected.

**These plans are preliminary.** If I don't get much use out of it or people
don't like it, I may wind the experiment down entirely. That's a feature, not
a bug — I'm not locking anyone into depending on this.

---

### 5. Product Scope

**Q: What problems does it solve? What features exist? What's planned?**

**The problem it solves:** Groove sessions on the Discord server currently
depend on a facilitator manually timing, announcing, and following up. Ocha
automates that: countdown, end-of-session chime, follow-up prompt. I built
this because I had the same pain point on another server I run and wanted to
see if Groovers would find it useful here too.

Lower friction for running a session means more people might stay in the
Groove Discord to work rather than dropping off — which over time could mean
better coverage across time zones and parts of the day. This is a pain point
the Groove community has had. Groovers who don't want to use it don't have to
touch it; the option is purely additive.

To put it plainly: at worst, nobody uses it and the server continues exactly
as it has for the past year — no change, no harm. At best, it's a meaningful
quality-of-life improvement: a polished graphical interface for starting and
running a co-working session that requires no technical knowledge to use. The
Groove community is generally non-developer, and this is designed for that —
buttons, embeds, a chime, a follow-up prompt. It reduces the friction between
"I want to focus" and "a session is running."

**Current features (MVP):**
- `/teamode` slash command in any voice channel's text chat
- Facilitator picks session duration (25 / 50 / 90 min or custom)
- Optional intention modal (text prompt before the session starts)
- Countdown timer with Discord embed
- End-of-session chime (audio played in voice channel)
- Follow-up embed asking how the session went (emoji reaction)
- Session logged to local SQLite database

**Important caveat:** The current MVP has not yet been tested with the Groove
Boogaloo server specifically. Before any public rollout, I'm offering to deploy
it on a testing server (or a test channel) so admins can try it out themselves
and give feedback.

**Planned / possible future features:**
- Channel name live update showing time remaining
- Home server migration (Raspberry Pi / micro-PC) for better uptime
- Known-issues page or pinned status message
- Potential open-source release if it proves useful in the real world

---

### 6. What's In It for the Developer?

**Q: What's in this for you?**

A few things, all of them honest:

1. **Curiosity.** I built this and it works. I want to see how real people
   outside my own server actually use it — what session lengths are popular,
   whether people report success or struggle, how often it gets used at all.
   That data stays with me for my own analysis; it's not monetized.

2. **Proof of concept.** I've been using this on another server for a few
   weeks. Groove Boogaloo would be the first external beta test. Seeing
   whether Groovers adopt it tells me something real that I can't get from
   testing alone.

3. **Portfolio.** If this proves useful, it becomes something I can point to
   as a real-world deployed project when I'm looking for future work. I retain
   all rights to the code.

4. **It's just a fun thing I made.** I'm not trying to build a business here.
   I wanted to solve a problem, I solved it, and I thought Groovers might
   appreciate the optional functionality.

I do not intend to profit from this on the Groove Boogaloo server.

---

## Licensing & Source Code

The code is proprietary — I retain all rights. I'm not sharing the source
publicly at this time and I'm not licensing it for reuse or redistribution.

I may open-source it in the future on my own timeline if I decide to, but
that's my call.

If admins want to verify what the bot does and what permissions it holds, the
Discord developer portal shows the bot's permission scopes and I'm happy to
share that.

---

## Next Step — Call to Action

Rather than answer more questions in the abstract, the fastest way to evaluate
this is to just see it working.

**Invite me to your testing server and I can have the bot deployed and ready
to try in about 5 minutes.** You'll see exactly what it does, what permissions
it requests, and what the experience looks like for a facilitator — no
commitment, no rollout to the community yet.

---

## Open TODOs

- [ ] **Research home server hosting** (Raspberry Pi / micro-PC): cost, setup
  effort, reliability vs. running off a laptop
- [ ] **Intention text privacy:** Add option to not persist intention text to
  the database (or restrict persistence to developer account only) before
  deploying to Groove
- [ ] **Deploy to test server/channel** for admins to try before any community
  rollout
- [ ] **Draft community announcement** with clear expectations: free, optional,
  best-effort, maintained by one person
- [ ] **Known-issues page or pinned message** — simple place to check status
  if the bot is down
