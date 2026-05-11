# UI Architecture Decision Record — TeaMode

Current Discord-surface state for TeaMode (Ocha bot). Reference this
document instead of re-reading the codebase when making UI decisions per
`.LLMAO/ui-decisions-subsection.md`.

Last reviewed: 2026-05-09 (pre-implementation; reflects approved Spec
decisions, not landed code).

---

## Bot identity

- **Application name** (Discord developer portal, internal): `TeaMode`.
  Matches the repo (CamelCase reading) for searchability while the
  slash command stays lowercase per Discord convention.
- **Bot user display name** (what people see in chat): `Ocha`.
  Short, mentionable (`@Ocha`), tea-coded, distinct from the application
  name. The asymmetry is intentional — the application is the project,
  Ocha is the persona.
- **Avatar:** a teacup, kettle, or steam emoji on a calm-coloured square.
  Matcha sage background recommended.
- **Status text:** rotates through the active session phase:
  - Idle: `Idle ☕`
  - During welcome / setup: `Steeping intentions… 🍵`
  - Timer running: `Brewing focus — {mm}:{ss}`
  - End of timer: `Time's up — tea time!`

---

## Color palette

| Role | Color | Hex |
|---|---|---|
| Active timer embed | Matcha sage | `#7B9D6F` |
| End-of-session embed | Steeping forest (deeper sage) | `#3F5E4A` |
| Refusal / warning | Muted grey | `#8A8A8A` |
| Crashed / cancelled | Muted red | `#A05A5A` |
| Completed (post-follow-up) | Oolong amber | `#C97B53` |

Colors live in a `COLORS` constant in the bot code; do not hardcode hex
values inline.

## Emoji palette

The consistent pair: **🍵** (tea moments — welcome, end-of-session) and
**⏳** (active timer). Secondary emoji used sparingly:
- 🌿 — accent on success / "kept your intention"
- ✨ — small flourish on session completion
- 🥅 — accent on goal-setting (intention modal prompt)
- ✅ / ⛔ — follow-up reactions on the Reflect-embed message.
  Pre-populated by the bot. The current facilitator's reaction is
  **authoritative** for `completed_intention` (✅ = 1, ⛔ = 0). Other
  participants' reactions are logged-only social signal.

Do not introduce new emoji without updating this section.

---

## Surface inventory

| Surface | Location | Purpose | Interactive |
|---|---|---|---|
| Welcome embed | Voice channel's text chat | Greets facilitator, prompts tea/desk/distractions | No (display) |
| Timer-pick button row | Same message as welcome (or follow-up) | 5 / 10 / 25 / 50 minute buttons | Yes — buttons |
| Participant `[Set Intention]` prompt | Voice channel's text chat, plain text | Posted 1s after welcome embed; @-mentions all current voice members (bot filtered) inviting them to share intention | No (display) |
| Intention modal | Triggered by timer-pick | Free-form text capture | Yes — modal |
| Active timer embed | Same channel | Cycles `mm:ss` every 10s | No (display only) |
| Session-complete embed | Same channel | "Session complete!" + @-mentions of voice members; reverie plays in voice | No (display) |
| Reflect embed | Same channel | "[Reflect] Share how your session went!" + facilitator prompt + pre-populated ✅/⛔ | Yes — emoji react |
| Follow-up "why" prompt | Same channel | Posts only when facilitator reacts ⛔ — invites public reflection (not bookkept) | No (display) |
| Refusal message | Same channel | "Session already running here — try another channel" | No (display, ephemeral to invoker) |

### Welcome embed copy (canonical)

Source of truth for the welcome embed. The bot's runtime output must
match this verbatim — do not paraphrase in code.

- **Title:** `🍵 Now Entering TeaMode`
- **Body:**

> Time for TeaMode!
> · Grab your tea (or water/beverage of your choice),
> · Clear your desk,
> · And silence all distractions (like phones, impromptu meetings).
>
> ⏳ **How long would you like to focus today?**

- **Accent color:** `#7B9D6F` (matcha sage).
- **Buttons (attached to the same message):** `5 min`, `10 min`,
  `25 min`, `50 min` — secondary style.

### End-of-session embed copy (canonical)

Source of truth for the end-of-session embed. The bot's runtime
output must match this verbatim — do not paraphrase in code.

- **Title:** `✨ Session complete!`
- **Body:** `🌿 Sip your tea, stretch, and notice your progress.`
  - Rendered as `## 🌿 Sip your tea, stretch, and notice your progress.`
    in the embed description — the `##` markdown promotes it to heading
    weight for visual emphasis.
- **Accent color:** `#3F5E4A` (steeping forest).
- **Content (above embed; @-mentions of current voice channel members
  at end-tick, with Ocha filtered out — mentions ping):**

  ```
  Time's up, <@id1> <@id2> <@id3>!
  ```

  If the voice channel is empty (everyone left mid-session), `content`
  is just `"Time's up!"` with no mention list. The list always
  reflects current voice membership, so it adapts to handoff and
  late joiners alike.

Posted as a single `channel.send(content=..., embed=...)` call.
Mentions live in `content` (they ping); they don't ping from embed
description.

### Reflect embed copy (canonical)

Posted right after the Session-complete embed. The bot pre-populates
✅ and ⛔ reactions on this message.

- **Content (above embed; plain prompt, no mention):**

  ```
  [Follow-up] React ✅ if you finished, ⛔ if not.
  ```

  No facilitator @-mention — the Session-complete message immediately
  above already @-mentions all voice members (facilitator included),
  so a second ping would be noise. The `[Follow-up]` prefix is a
  visual hand-off cue.

- **Embed title:** `🌿 [Reflect]`
- **Embed body:**

  > Share how your session went!
  > · React with emoji
  > · Share in voice
  > · Or type in chat

- **Accent color:** `#3F5E4A` (steeping forest — matches Session-complete embed).

### "Why" prompt copy (canonical)

Posted only when the facilitator reacts ⛔. Plain-text channel
message:

```
<@facilitator_id> — share what got in the way: type in chat or share in voice.
```

The bot does not capture the response (`followup_note` stays NULL).
The reflection is social, not bookkept.

---

## Interaction model

### Slash command
- **Single command**: `/teamode` (no subcommands for MVP).
- **Options**: none — keeps invocation conversational rather than
  parameterized. Timer length is chosen via post-invocation buttons so
  the user sees options in context.
- **Scope**: guild-scoped during dev (instant updates); promote to global
  when shareable.

### Custom_id namespace
All component `custom_id` values follow:

```
teamode:<session_id>:<purpose>[:<value>]
```

Examples:
- `teamode:42:timer:25` — pick 25-minute timer for session 42

The session id makes interactions safe across concurrent sessions in
different channels. After the T4.2 redesign, the only interactive
component using a custom_id is the timer-pick button row; follow-up
state is captured via ✅/⛔ reactions on the Reflect embed message
(see § "Authorization rules" and § "Emoji palette").

### Authorization rules
- Timer pick / intention modal: facilitator only. Other clicks: ephemeral
  refusal "Only the facilitator can answer."
- Follow-up ✅/⛔ reactions on the Reflect-embed message:
  - **The current facilitator's reaction is authoritative.** ✅ →
    `mark_completed(completed_intention=1)`. ⛔ →
    `mark_completed(completed_intention=0)` + posts a public "why"
    prompt (not bookkept — facilitator shares in voice or chat; bot
    does not capture).
  - Anyone else's reaction (including the bot's own pre-populated
    reactions) is logged to console only and does **not** change
    session state.
- Facilitator handoff: when the original facilitator leaves voice, a new
  facilitator is selected from remaining voice members via `random.choice`
  and announced in the channel. The new facilitator becomes the
  authoritative reactor for ✅/⛔ from that point on.

### Refusal behavior
When `/teamode` is invoked while another session is active in the same
text channel, the response is **ephemeral** (only the invoker sees it),
muted-grey embed: "A TeaMode session is already running in this channel
— please pick another text channel."

### Timer edit cadence
- Edit the active timer message every **10 seconds**.
- Use exponential backoff on `discord.HTTPException`; do not retry
  faster than 10s.
- Skip an edit if the previous one is still in flight (no edit queue
  build-up).

---

## Mobile rendering

- Discord mobile clips embed widths around ~340px.
- Avoid multi-column field layouts; prefer single-column for the timer
  embed.
- The matcha-sage accent renders correctly on both light and dark
  themes.

---

## Decisions already made (do not revisit)

These are settled architectural choices. New UI work should build on
them, not reconsider them.

- **Single slash command**, no subcommands for MVP. Future commands
  (`/teamode-stats`, etc.) are separate commands, not subcommands.
- **No accountability picker, no action step** — dropped from the
  original Steps array.
- **Voice channel's own text chat** is the only valid invocation
  channel.
- **MVP visual fidelity**: plain text edit cycling `mm:ss`. Embed +
  unicode progress bar is a v2 polish — do not preempt.
- **Ephemeral refusals**, not visible-to-channel public ones, when a
  user is unauthorised or invokes during an active session.
- **Bot joins voice at session start**, not late-join at end. Reverie
  reliability outweighs the small cost of holding a voice connection.
- **Confetti analogue** at end-of-session: a single message with a
  small 🍵🌿✨ flourish; no animated cycle for MVP.
- **Timer durations**: `5 / 10 / 25 / 50` min. Reaction-only follow-up
  redesign superseded the Y/N click model — see § "Authorization rules".
- **Intention modal accepts empty submissions.** The active-timer first
  line collapses to `🍵 No intention set` when intention is empty or
  whitespace-only. Facilitators who prefer to speak rather than type
  can submit a blank modal.
- **Participant `[Set Intention]` prompt fires post-welcome** (1-second
  beat after the welcome embed), not post-modal-submit. This invites
  participants to share their intention before the timer is picked,
  paralleling the facilitator's modal.

---

## Pending UI decisions (track here as they're made)

- Welcome flourish format (single tidy embed vs. ASCII teacup banner —
  v2 polish, not MVP).
- Whether to render an embed progress bar at v2 fidelity.
- Whether to surface look-back stats via a `/teamode-stats` command or
  a one-off SQL query helper.
- Avatar image — placeholder vs. final asset.
