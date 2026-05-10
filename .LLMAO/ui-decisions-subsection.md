# UI Decisions Subsection — TeaMode (Discord)

## What This Is

A required subsection in any APM Implementation Plan for tasks that touch
TeaMode's user-visible Discord surface — slash command shape, embeds,
button rows, modals, message edit cadence. Locks visual and interaction
decisions **before** implementation starts, so the worker agent doesn't
make judgment calls.

This is not a separate phase or skill. It's a subsection within the
existing plan.

## When to Include

Include a "UI Decisions" subsection in the Implementation Plan when the
task touches any of:

- Slash command definition or option shape (`/teamode`, future commands)
- Button rows, select menus, or modal forms
- Embeds (color, title, fields, footer, thumbnail)
- Message edit cadence (e.g. countdown updates)
- Reaction-based interactions
- Bot status text or presence
- Mobile-vs-desktop rendering considerations

**Skip for:** SQLite schema changes, internal asyncio refactors, voice
plumbing that has no surface change, test-only work, or pure platform
fixes that don't affect what the user sees.

## What to Decide

Answer these questions before implementation. The Planner or Manager
should surface them during planning; the user locks the answers.

### Channel and visibility
- Which channel does the message land in? (the voice channel's text chat
  by default — see `.project-meta/UI-ADR.md`)
- Ephemeral or visible to all participants?
- Does the message persist after the session ends, or get cleaned up?

### Content
- Exact title, description, and field text — not placeholder
- What's the empty state? (e.g. before intention is captured)
- What updates it? (timer tick, button click, follow-up)

### Interaction
- Components used: button row / select menu / modal / reactions
- `custom_id` namespace (must follow `teamode:<session_id>:<purpose>`)
- Which user is allowed to interact? (facilitator only, anyone in
  voice channel, anyone in server)
- Failure mode if a non-authorised user clicks (silent vs. ephemeral
  refusal)

### Style
- Embed accent color: inherit from `.project-meta/UI-ADR.md` palette or
  override (and why)
- Emoji palette: inherit (🍵, ⏳) or override
- Footer / timestamp / author line presence

### Rendering
- Mobile width considerations — Discord mobile clips embed widths; flag
  any column-heavy field layout
- Notification behaviour — does the edit ping anyone? (Discord re-pings
  on `@mention` in edits; usually undesirable)

## Template

Add this to the Implementation Plan under the relevant stage:

```markdown
### UI Decisions

**Surface:** [embed / button row / modal / status text / etc.]
**Channel:** [voice-channel-text-chat / DM / etc.]
**Trigger:** [slash command / button click / timer tick / etc.]

| Decision | Answer |
|----------|--------|
| Title / label | [exact text] |
| Body / description | [exact text or template string] |
| Empty state | [what shows before data is available] |
| Update trigger | [timer tick (10s) / button click / etc.] |
| Components | [button row labels + styles + custom_ids] |
| Authorised interactor | [facilitator only / anyone in voice / etc.] |
| Unauthorised click | [silent / ephemeral refusal] |
| Embed color | [hex from UI-ADR or override] |
| Emoji used | [list] |
| Mobile rendering | [single-column / unchanged / mitigation] |

**Mockup (optional):**
```
┌─────────────────────────────────────┐
│ 🍵  TeaMode — 25 min session        │
│                                     │
│ Intention: Finish v26Q2 changelog   │
│ ⏳ 24:50 remaining                   │
└─────────────────────────────────────┘
```
```

## How the Worker Uses It

The APM worker references this subsection as the spec for all visual
decisions. If a decision isn't covered, the worker should return Partial
and ask — not guess.

The worker should NOT:
- Choose embed colors, emoji, or text independently
- Add interactive behavior not specified in the UI Decisions
- Skip the `custom_id` namespace convention

## After Implementation

Flag the change as requiring a manual Discord smoke test in the commit
approval request. Include a paste-ready launch command:

```bash
cd ~/WSL/github.com/jonathan-fang/teamode && source .venv/bin/activate && python3 teamode.py
```

Plus the in-Discord steps: which server / channel / voice channel to
join, which command to run, what to look for.

If the change affects the look-back stats (SQLite reads), include a
`sqlite3 sessions.db` query the user can paste to verify what was logged.
