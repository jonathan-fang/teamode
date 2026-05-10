# Pre-Plan Research Phase

## What This Is

A structured research step run **before** APM planning begins. The goal is to surface ecosystem knowledge, architectural constraints, and known pitfalls so the Planner builds on evidence, not assumptions.

This is separate from APM. Run it in a standalone session, save the output, then reference it when initiating the Planner.

## When to Use

- Greenfield features touching unfamiliar Discord API surface
- Library behavior questions (discord.py, voice extras, asyncio)
- Architectural decisions with multiple viable approaches
- Any task where the first instinct is "I'm not sure how to do this"

**Skip for:** Routine bug fixes, documentation, config changes, or features in well-understood code paths.

## How to Run

### 1. Define the research question

Write a clear, scoped question. Not "research discord.py voice" — instead: "Can discord.py's voice extras play a 5-second WAV reliably after holding an idle voice connection for 50 minutes?"

### 2. Spawn parallel research agents

Use 2-3 Explore agents in parallel, each with a distinct angle:

| Agent | Focus | Example prompt |
|-------|-------|----------------|
| **Stack** | Libraries, APIs, framework capabilities | "What does discord.py's `VoiceClient.play` API support? Read the source or docs. Report capabilities and limitations." |
| **Architecture** | How it fits into the existing codebase | "How would the voice playback path integrate with the existing session.py / voice.py split? Identify touch points." |
| **Pitfalls** | Known issues, edge cases, platform constraints | "What are known issues with long-held discord.py voice connections (50+ minutes idle)? Check GitHub issues." |

Adjust the agents to the task. Not every task needs all three angles.

### 3. Compile findings

Collect agent outputs into a single `RESEARCH.md` (or inline in the session). Structure:

```markdown
## Research: [topic]

### Stack Findings
- [key finding 1]
- [key finding 2]

### Architecture Findings
- [integration point 1]
- [constraint 1]

### Pitfalls
- [known issue 1]
- [platform-specific gotcha 1]

### Recommendation
[1-2 sentences: what approach to take based on findings]
```

### 4. Feed into Planner

When initiating `apm planner`, reference the research:

> "Before planning, read RESEARCH.md in .apm/ for pre-plan research findings on [topic]. The Planner should use these findings to inform phase decomposition and task scoping."

Or paste the key findings directly into the Planner brief.

## What Good Research Looks Like

- **Specific:** "discord.py's `Interaction.response.send_message` must be called within 3 seconds; after that, only `followup.send` is valid" — not "Discord has some response timing issues"
- **Actionable:** Each finding implies a decision or constraint the Planner should respect
- **Scoped:** Focused on the task at hand, not a general survey of the ecosystem
- **Sourced:** Points to code, docs, or issues that back up the claim

## Tradeoffs

**Cost:** Token-intensive. 2-3 Explore agents each consume context. For a TeaMode-scale project where you know the codebase, this is often overkill.

**Benefit:** Prevents the Planner from proposing approaches that hit dead ends. One research session can save multiple failed implementation cycles.

**Rule of thumb:** If you'd Google it before coding, run a research phase. If you already know how to do it, skip straight to planning.
