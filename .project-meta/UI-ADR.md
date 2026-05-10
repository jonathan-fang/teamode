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

Do not introduce new emoji without updating this section.

---

## Surface inventory

| Surface | Location | Purpose | Interactive |
|---|---|---|---|
| Welcome embed | Voice channel's text chat | Greets facilitator, prompts tea/desk/distractions | No (display) |
| Timer-pick button row | Same message as welcome (or follow-up) | 10 / 25 / 50 minute buttons | Yes — buttons |
| Intention modal | Triggered by timer-pick | Free-form text capture | Yes — modal |
| Active timer embed | Same channel | Cycles `mm:ss` every 10s | No (display only) |
| End-of-session embed | Same channel | "Time's up — tea time!"; reverie plays in voice | No (display) |
| Follow-up button row | Same message as end-of-session | Y / N + optional "why" text | Yes — buttons |
| Follow-up reaction window | Same message | 3-min reaction window for participants (optional) | Yes — emoji react |
| Refusal message | Same channel | "Session already running here — try another channel" | No (display, ephemeral to invoker) |

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
- `teamode:42:followup:yes` — facilitator's "yes" answer
- `teamode:42:followup:end` — facilitator ends follow-up window early

The session id makes interactions safe across concurrent sessions in
different channels.

### Authorization rules
- Timer pick / intention modal: facilitator only. Other clicks: ephemeral
  refusal "Only the facilitator can answer."
- Follow-up Y/N: facilitator only.
- Follow-up reaction window: anyone in voice channel may react with
  thumbs up / down (social signal; not authoritative).
- Facilitator handoff: when the original facilitator leaves voice, a new
  facilitator is selected from remaining voice members via `random.choice`
  and announced in the channel.

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
- **Reaction-only follow-up is not authoritative**; the facilitator's
  Y/N click writes `completed_intention`. Reactions are social signal.
- **Ephemeral refusals**, not visible-to-channel public ones, when a
  user is unauthorised or invokes during an active session.
- **Bot joins voice at session start**, not late-join at end. Reverie
  reliability outweighs the small cost of holding a voice connection.
- **Confetti analogue** at end-of-session: a single message with a
  small 🍵🌿✨ flourish; no animated cycle for MVP.

---

## Pending UI decisions (track here as they're made)

- Welcome flourish format (single tidy embed vs. ASCII teacup banner —
  v2 polish, not MVP).
- Whether to render an embed progress bar at v2 fidelity.
- Whether to surface look-back stats via a `/teamode-stats` command or
  a one-off SQL query helper.
- Avatar image — placeholder vs. final asset.
