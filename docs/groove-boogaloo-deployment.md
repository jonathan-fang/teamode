# Groove Boogaloo Deployment — Negotiations & Q&A

Working document for the conversation with Groove Boogaloo admins about
deploying Ocha (the TeaMode bot) on their server.

**Throughline for every answer:** This is a free, optional, best-effort
experiment. I'm not selling anything. The downside is bounded — if it breaks,
the core Discord server is unaffected. The upside is a quality-of-life
improvement for anyone who wants to focus without the friction of manually
running a session.

---

## Stakeholder Interests

### Admin interests (megan oregano)
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

**Q: How secure is a free host? When something is free, the user is the
product — what is the host pulling from end users?**

The premise of this question doesn't apply here: **there is no free host.**
The "user is the product" concern is valid for free cloud platforms
(Heroku, Railway, Render free tiers) where the platform company monetizes
your traffic or data to fund its free tier. None of those are in use.
The bot runs off my personal PC. There is no platform, no third party,
no advertising network, no data broker in the chain. The only party with
access to anything is me.

**Q: What happens if usage exceeds limits? Is someone charged?**

There are no external limits, because there is no external service.
The "limit" is whether my PC is on and the bot process is running.
If I turn it off, the bot goes offline — no overage, no charge,
no bill. Nobody gets charged. See Hosting & Availability for the
full picture.

The bot itself collects the following per session, stored in a local SQLite
database on my machine:
- Discord user ID (numeric, not username) of the session facilitator
- Discord user ID of the handoff facilitator, if the session was handed off
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
the process, the bot is offline. The bot's user will appear offline in the
server member list. Any attempt to run `/teamode` will receive a Discord
"The application did not respond" timeout — no crash, no error cascade, just
unavailable.

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

**If scaling past the experimental phase becomes a question:**
The bot is deliberately lightweight — Python, SQLite, one audio file. It does
not need significant compute. Rough estimates for context (not commitments):
- *Raspberry Pi / micro-PC home server:* ~$35–100 one-time hardware cost,
  no ongoing hosting fee, always-on as long as my home internet is up.
- *Cheapest VPS (e.g. Hetzner, Fly.io):* ~$4–6/month. Fully managed by me,
  no exposure to the community.
- *At Groove Boogaloo's current and historical scale,* the bot's resource
  footprint is negligible — this is not a traffic problem, it's a "is it
  running" problem.
If this question ever becomes real, I'd share options and costs transparently
before making any move.

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
If it ever came to that, the threshold would be something like "at least one
month of server costs covered" before collecting anything (~$5–6 at VPS
scale). I'd manage it personally — likely via Ko-fi or PayPal to accommodate
international contributors. Nothing would be collected until there was a real
cost to offset.

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

1. **It's a useful thing I made.** 
   I wanted to solve a problem, I solved it, and I thought Groovers might
   appreciate the optional functionality. It's a little bit of what was good about Groove bringing back with the help of software.

2. **Curiosity.** I built this and it works. I want to see how real people
   outside my own server actually use it — what session lengths are popular,
   whether people report success or struggle, how often it gets used at all.
   The stats I'm interested in (session counts, durations, success/struggle
   rate) do not require knowing who ran the session. Before deployment I'll
   drop or anonymize any user-identifying fields so the data is aggregate only
   — see the Research Findings section for what that means in practice at
   Groove Boogaloo's scale. If the admins would rather I collect no stats at
   all, that's a reasonable ask and I'm open to discussing it. The bot is
   entirely optional either way.

3. **Proof of concept.** I've been using this on another server for a few
   weeks. Groove Boogaloo would be the first external beta test. Seeing
   whether Groovers adopt it tells me something real that I can't get from
   testing alone.

4. **Portfolio.** If this proves useful, it becomes something I can point to
   as a real-world deployed project when I'm looking for future work. I retain
   all rights to the code.



I do not intend to profit from this on the Groove Boogaloo server.

---

## Licensing & Source Code

The code is proprietary — I retain all rights. I'm not sharing the source
publicly at this time and I'm not licensing it for reuse or redistribution.

I may open-source it in the future as it gets more stable and gets more real world use if I decide to, but
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

**Communication status:**
- Screenshots of the bot in action: sent
- Screen recording: not yet
- Developer Discord handle: already shared

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

---

## Audit Notes (pre-deployment code review)

Findings from a code review of `app/bot.py`, `app/session.py`, `app/db.py`,
`app/voice.py` against the claims in this doc.

### Confirmed accurate
- **Permissions:** Intents are minimal — `guilds`, `voice_states`, `reactions`
  only. `message_content` and `members` are not enabled. The bot provably
  cannot read message history, send DMs, or fetch member lists.
- **Voice audio:** The bot only plays `reverie.wav` outbound via
  `FFmpegPCMAudio`. No `listen()` call exists anywhere. No recording.
- **Session isolation:** One active session per text channel, enforced as a
  hard invariant. Concurrent sessions in different channels run independently
  with no shared state.

### Gaps corrected in this doc
- **`handoff_facilitator_id`:** The sessions table stores a second Discord
  user ID if a facilitator handoff fires. Added to the data disclosure above.
- **Offline UX:** When the bot is down, users see Discord's generic
  "The application did not respond" timeout — not a clean "bot is offline"
  message. Corrected above.

### Open pre-deployment items (code not yet written)
- **Intention text privacy:** Unconditionally saved today. Needs conditional
  logic or opt-in before community rollout.
- **User ID anonymization:** Both `facilitator_id` and
  `handoff_facilitator_id` are stored indefinitely, with an index on the
  former. Decision pending — see TODO.md.
- **Per-user rate limiting:** No invocation cooldown or daily cap exists.
  Any member in a voice channel can call `/teamode` repeatedly. Low risk at
  current server scale; a guard is planned before deployment.
- **`ffmpeg` startup probe:** If `ffmpeg` is missing on the host, the
  end-of-session chime silently fails and the bot disconnects. No startup
  warning exists yet.

---

## Research Findings

### Data Anonymization

#### Background: what "truly anonymous" means

True anonymization is irreversible — it permanently strips data of its
personal status. Unlike pseudonymization (replacing an ID with a hash you
could theoretically reverse), true anonymization means no path back to the
individual exists. Regulations like GDPR treat truly anonymized data as
outside their scope entirely.

Because absolute anonymization often destroys data utility, privacy
engineers use specific techniques to balance the two:

**The 4 core techniques:**

1. **Randomization** — Alter data values so they no longer correspond to a
   specific person while keeping overall statistical trends. Examples:
   adding mathematical noise to numbers, or shuffling traits among records.

2. **Generalization** — Reduce precision to group individuals together.
   E.g. exact birthdate `1994-05-14` → age bracket `30–35`; exact GPS
   coordinate → city region.

3. **Data masking** — Permanently strip or blank out identifying columns
   entirely (e.g. remove all user IDs from the table).

4. **Synthetic data generation** — Use an AI model to study the real
   dataset and produce a fake dataset with the same statistical properties
   but zero real records.

**Advanced mathematical frameworks** (referenced for completeness; overkill
at this scale):

- **k-Anonymity:** A dataset satisfies k-anonymity if every individual's
  identifying traits match at least k−1 other people in the dataset,
  making it impossible to single anyone out. Requires a population large
  enough to form groups.

- **Differential Privacy (gold standard):** Injects calibrated mathematical
  noise into queries so an observer cannot determine whether any specific
  person's data was used to compute a statistic. Prevents re-identification
  attacks. Meaningful only at statistical scale — not applicable to
  ~15 active users.

**The core trade-off:**

```
[TRULY ANONYMOUS] <-----------------------------------------> [HIGH UTILITY]
Aggregate counts / masking          HMAC pseudonym        Raw user ID
No re-identification risk           Brute-forceable        Full exposure
Sufficient for this use case        False sense of safety  Not acceptable
```

#### Option A: HMAC Pseudonymization

Store `HMAC-SHA256(secret_key, str(user_id))` instead of the raw Discord ID.
Same user always produces the same digest — you can detect "this person ran
3 sessions this week" without storing the raw ID. Key lives in the
environment alongside `DISCORD_BOT_TOKEN`.

**Pros:**
- Repeat-user tracking still possible (same hash = same person)
- Feels technically rigorous
- Standard approach in larger systems

**Cons — critical at Groove Boogaloo's scale (120 total users, ~15 active):**
- Discord user IDs are a small, enumerable input space. With only 120 known
  users, an attacker who obtains the HMAC key can reverse every hash by
  iterating those 120 IDs in milliseconds. This is the same attack that
  reversed NYC taxi medallion hashes in under an hour on a much larger set.
- The key must be protected with the same rigour as the bot token. If it
  leaks, all pseudonymization is retroactively broken.
- Key rotation invalidates all existing hashes, making historical data
  unresolvable.
- Adds environmental complexity (new secret to manage) for marginal gain.

**Verdict at this scale: security theatre.** HMAC makes sense when the input
space is large enough that brute-force is infeasible. At 120 users it is not.

#### Option B: Aggregate counts only — drop the user ID (recommended)

Store only the stats that answer the actual questions: total sessions per
day/week, duration distribution, emoji outcome rate (success vs. struggle).
Never write a user ID to the database at all. A separate `stats` table with
`(week_bucket TEXT, duration_minutes INT, outcome INT)` covers everything.

**Pros:**
- Truly anonymous — no identifier exists to reverse, brute-force, or leak
- No secret key to manage or rotate
- Simpler code, simpler schema
- The stats Jonathan actually wants (how many sessions? what duration? do
  people feel they succeeded?) require no per-user linkage
- At 15 active users, per-user repeat tracking adds no analytical value —
  the sample is already too small for individual-level insights to be
  meaningful

**Cons:**
- Cannot answer "did this specific user run 5 sessions this month?" —
  but that question is not needed for the stated goals
- Cannot detect if one person is inflating session counts — mitigated by
  the per-user rate limiting guard (separate feature)

**Verdict: the right approach for this project and this scale.** Drop
`facilitator_id` and `handoff_facilitator_id` from the schema before
deployment. Keep only aggregate fields. True anonymization with no tradeoff
at 120 users.

---

### Donations & Legal Requirements (US)

**IRS 1099-K threshold (2025 onward):** Platforms (Ko-fi, PayPal, Patreon)
are only required to issue a 1099-K if you receive **more than $20,000 AND
over 200 transactions** in a calendar year. This threshold was restored by
the One Big Beautiful Bill Act of 2025. At $5–6/month VPS cost-recovery
scale, this is unreachable.

**Is it still taxable below the threshold?** Technically yes — the 1099-K
threshold is a reporting trigger for the platform, not a taxability cutoff.
However: voluntary Ko-fi-style tips where nothing is given in return are
closer to gifts in IRS framing. At under ~$200/year, virtually all hobbyist
maintainers report nothing. If reported, it goes on Schedule 1 as hobby
income (not Schedule C — no self-employment tax).

**Platform comparison:**

| Platform | Fee | Account needed | Best for |
|---|---|---|---|
| Ko-fi | 0% (free tier) | Personal | One-time tips, cost recovery |
| PayPal | ~2.9% + $0.30 | Personal (up to volume threshold) | International contributors |
| Patreon | 5–12% | Personal | Recurring subscriptions |

**Conclusion:** Ko-fi personal account, no business entity needed. Nothing
to act on until a real hosting cost exists. If international contributors
are expected, PayPal as a secondary option.
