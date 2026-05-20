# Groove Boogaloo — Admin Q&A Round 1

Draft replies to the admin questions. Paste into Discord as-is or adapt tone.
Source material: `docs/groove-boogaloo-deployment.md`.

---

**Q: How secure is a free host? When something is free, the user is the
product — what is the host pulling from end users?**

A: This is exactly the right question to ask, and I want to address it
directly: the premise doesn't apply here, because there is no free host.
The "user is the product" concern is real and valid for free cloud platforms
— services like Heroku or Railway free tiers fund themselves by monetizing
your traffic. None of that is involved. The bot runs off my personal PC.
No platform, no third party, no advertising network, no data broker anywhere
in the chain. The only person with access to anything the bot touches is me.

---

**Q: What happens when usage exceeds limits? Is someone charged? Who bears
the responsibility? What if you need to collect money from us?**

A: There are no external limits, because there is no external service to
exceed them on. The only "limit" is whether my PC is on and the bot is
running. If I turn it off, the bot goes offline. No overage, no bill, no
credit card on file with anyone, no charge to pass on. The admins and the
community bear zero financial liability — there is no scenario in which
using this bot results in a charge to you, to Megan, or to anyone in the
community.

If I ever moved to paid hosting down the road (we're talking ~$5–6/month
at most, on the cheapest VPS), I'd bear that cost personally. Any donation
model would be entirely optional, transparent, and something I'd discuss
openly before setting up — not something sprung on anyone. Right now that's
a hypothetical. Currently it costs me nothing beyond my electricity bill.

---

**Q: Who provides customer service? What happens when the bot breaks or
behaves unexpectedly? What about when a Groover needs more help?**

A: I do, best effort. If it breaks, it won't work — users can DM me on the
Groove Discord and I'll look into it. I'll either fix it within a few days
when I have time or post a known-issues note somewhere visible. I'm not
running an on-call rotation for a free side project, so response times will
vary.

When it breaks, it's effectively like the bot never existed: the server
continues exactly as it has for the past year. Nothing downstream breaks,
nothing changes, you just can't use `/teamode`. It's a purely additive
feature — at worst, status quo.

If it behaves unexpectedly, same path: DM me, I'll investigate. The bot
has a narrow, explicitly configured set of Discord permissions. It cannot
send DMs, read message history, or do anything outside of a `/teamode`
session. If something goes sideways, the worst realistic outcome is a weird
embed in a voice channel text chat.

---

**Q: What problems is the bot solving? What features currently exist?
What other features are planned?**

A: The problem: running a co-working session on the Groove Discord currently
requires a facilitator to manually time, announce, and follow up. This bot
automates that. Type `/teamode` in a voice channel's text chat, pick a
duration, optionally set an intention, and Ocha handles the rest —
countdown timer, end-of-session chime played into the voice channel, and a
follow-up prompt asking how the session went.

Current features: slash command, duration picker (25/50/90 min or custom),
optional intention modal, countdown timer embed, end-of-session audio chime,
follow-up emoji prompt (did you succeed or struggle), session logged locally.

Possible future features: a channel status line showing time remaining,
better always-on hosting if it proves useful. Nothing beyond the MVP is
committed to.

**Important caveat:** the current MVP has not yet been tested on Groove
Boogaloo specifically. I'd rather show it to you on a testing server first
before anything touches the main community — which brings me to the last
section below.

---

**Q: Where will it be hosted? What are the actual capabilities and
limitations? Expected uptime?**

A: My personal PC, for the experiment phase. Live when I'm around and
running it, offline when I'm not. When it's offline, anyone who tries
`/teamode` sees "The application did not respond" from Discord — no crash,
no drama, just unavailable. At Groove Boogaloo's scale (~120 members,
~15 active at any time), this is not a traffic problem; it's a "is
Jonathan's PC on" problem.

If it ever proved popular enough that people wanted it always on, the next
step would be a Raspberry Pi or small home server (~$35–100 one-time, no
monthly fee) before anything else. A small cloud VPS would be $4–6/month
and I'd cover that personally. None of those decisions need to be made now.

These plans are also preliminary — if people don't use it or don't like it,
I may wind the experiment down entirely. That's intentional. I'm not trying
to create a dependency.

---

**Q: A full design doc would be helpful.**

A: I've put together a working document covering security, hosting,
cost/liability, support, product scope, and developer motivation in detail.
Happy to share it. I'm also happy to share a screenshot of the Discord
developer portal showing exactly what permissions the bot holds.

But honestly — the fastest way to understand what this is, is to see it
working. Invite me to your testing server and I can have Ocha deployed and
running in about 5 minutes. No commitment, no community rollout, just the
admins poking at it and seeing what it does.

---

**Q: What's in this for you as a developer?**

A: Honest answer, a few things:

I built this because I had the same frustration on another server I run, and
it works well there. I wanted to see if Groovers would find it useful — that
curiosity is genuine. I'm interested in aggregate usage patterns (what
session lengths do people prefer, do people generally feel they succeeded or
struggled?) but I'm planning to collect only anonymous aggregate stats before
any deployment — nothing linked to individual users.

If this proves useful in the real world, it becomes something I can point to
as a portfolio piece for future job searches. I retain all rights to the
code. I'm not monetizing this, I'm not building a business here, and I don't
intend to profit from the Groove Boogaloo server.

It's a useful thing I made, and it felt like it could bring back a little bit
of what made Groove good — in the Discord space you've already built.

---

**On your closing note:**

I hear you. You built something with real care out of something that was
taken away, you've kept it free, and you're asking these questions to protect
that — not to be difficult. That's exactly the right instinct and I respect
it.

I'm not trying to add friction or risk to what you've built. If at any point
this feels like more trouble than it's worth, just say so. The bot is
completely optional, it doesn't change anything about the server's core
experience, and its absence leaves everything exactly as it's been for the
past year.

The next step I'd suggest: let me show it to you before we discuss further.
Invite me to your testing server, I'll deploy it in 5 minutes, and you can
see for yourself what it does and doesn't do. If it doesn't feel right after
that, that's a totally valid outcome.

---

*Source: `docs/groove-boogaloo-deployment.md` — full research and audit notes there.*

---

## Actual Messages Sent (2026-05-19)

*Exact content pasted into the Groove Boogaloo Discord.*

---

**Q1: How secure is a free host? When something is free, the user is the
product, so what is the host pulling from the end users (i.e. people in
this Discord)?**

A: I think this is a great set of questions to ask, and I looked into the
free and paid tiers of VPS's available. My current conclusion is that for
this experimental phase of the TeaMode bot, the free host is me, or more
precisely my PC. The bot runs off my personal PC when I'm on the server
anyways.

---

**Q2: What happens when usage exceeds limits? Is someone charged? Who bears
the responsibility? What if you need to collect money from us?**

A: The only limit atm is whether my PC is on and the bot is running. If I
turn it off, the bot goes offline. There's no scenario in which using this
bot results in a charge to you, to Megan, or to anyone in the community.

If I ever moved to paid hosting down the road (we're talking ~$5–6/month at
most, on the cheapest VPS), I'd bear that cost personally. Any donation model
would be entirely optional, transparent, and something I'd discuss openly
before setting up and not something sprung up unexpectedly. Right now that's
a hypothetical. Currently it costs me nothing beyond my electricity bill. I
do not currently plan on moving to paid hosting because I do not have enough
data to decide whether I'd even want to scale it to that point.

---

**Q3: Who provides customer service? What happens when the bot breaks or
behaves unexpectedly? What about when a Groover needs more help?**

A: I am the designated customer rep for TeaMode, as an unpaid volunteer and
service will be variable. If it breaks, it won't work; users can DM me on
the Discord and I'll look into it. I'll either fix it within a few days when
I have time or post a known-issues note somewhere visible. I'm not running an
on-call rotation for a free side project, so response times will vary. I
intend to message very clearly to the community to manage their expectations
about this bot in that it's a free optional application they can use, and
maintainability is just one guy so don't expect like 24/7 call support.

When it breaks, it's effectively like the bot never existed: the server
continues exactly as it has for the past year. Nothing downstream breaks,
nothing changes, you just can't use `/teamode`. It's a purely additive
feature, and at worst, status quo.

If it behaves unexpectedly, same path: the user can DM me on Discord, and
I'll investigate. The bot has a narrow, explicitly configured set of Discord
permissions. It cannot send DMs, read message history, or do anything outside
of a `/teamode` session. If something goes sideways, the worst realistic
outcome is a weird embed in a voice channel text chat.

---

**Q4: What problems is the bot solving? What features currently exist?
What other features are planned?**

A: The problem is quality of life: running a co-working session on the Groove
Discord currently requires participants to manually time, announce, and follow
up. This bot automates that. Type `/teamode` in a voice channel's text chat,
pick a duration, optionally set an intention, and Ocha (what I named the bot,
it's the Japanese word for tea) handles the rest: countdown timer,
end-of-session chime played into the voice channel, and a follow-up prompt
asking how the session went.

Current features: slash command, duration picker (10/25/50 min), optional
intention modal, countdown timer embed, end-of-session audio chime, follow-up
emoji prompt (did you succeed or struggle), session logged locally.

Possible future features: a channel status line showing time remaining,
better always-on hosting if it proves useful. Nothing beyond the MVP is
committed to.

---

**Q5: Where will it be hosted? What are the actual capabilities and
limitations? Expected uptime?**

A: On my PC, for the experiment phase. It'll be live when I'm around and
running it, offline when I'm not. When it's offline, anyone who tries
`/teamode` sees "The application did not respond" from Discord — no crash,
no drama, just unavailable. At the current scale (~120 members, ~15 active
at any time), this is not a traffic problem; it's a "is Jonathan's PC on"
problem.

If it ever proved popular enough that people wanted it always on, the next
step could be a Raspberry Pi or small home server (~$35–100 one-time, no
monthly fee) before anything else. At the moment I'm not looking at VPS
unless there's a paid one with good data protections. But that's contingent
on a lot of stuff and I'm not committing to any long term service yet.

These plans are preliminary. If people don't use it or don't like it, I may
wind the experiment down entirely. That's intentional. I'm not trying to
create a dependency.

---

**Q6: A full design doc would be helpful.**

A: I'm attaching a preliminary one here. Please let me know if you require
specific sections or details. I also think when you see it live it'll make
more sense and I've tried to build it to be intuitive to use.
*(attached: `docs/groove-boogaloo-exp/teamode-design-doc.md`)*

---

**Q7: What's in this for you as a developer?**

A:
1. I built this in the first place because I had the same frustration on
   another server I run, and it works well there. And then I wanted to see
   if Groovers would find it useful.

2. I'm interested in aggregate usage patterns (what session lengths do people
   prefer, do people generally feel they succeeded or struggled?) but I'm
   planning to collect only anonymous aggregate stats before any deployment.
   Nothing is linked to individual users.

3. If this proves useful in the community, it will become something I can
   point to as a portfolio piece for future job searches. I do not intend to
   monetize this tool for this server.

4. At the end of the day, it's a useful thing I made, and I felt like it
   could bring back a little bit of what made the OG Groove app feel good
   to use.

---

Lastly, I want to highlight that this Discord bot application I've built is
completely optional for users of the community. When it's broken or absent it
doesn't compromise the core Discord server experience, and when it works it
gives non-developer users a significant improvement in user experience since
they can automate the tedious parts of getting into the groove. That's how
I've been using this app for the past couple of weeks now.

I'm happy to deploy it on the testing server (it takes like 5 minutes, server
ID, and manage permissions) and show you all what it does. I hope I've
addressed your questions and I look forward to showing y'all my tea-themed
GUI app for the server 😆
