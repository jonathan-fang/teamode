---
name: apm-communication
description: Agent communication standards for structured inter-agent messaging.
---

# APM Auto 1.0.0 - Communication Skill

## 1. Overview

**Reading Agent:** Planner, Manager

This skill defines agent communication standards. It covers communication models and the Manager's Handoff Bus protocol. Agent-specific delivery and coordination procedures are defined in each agent's guides and commands.

---

## 2. Agent-to-User Communication

### 2.1 Direct Communication

When communicating with the User - asking questions, requesting actions, providing status updates, presenting completions - use natural language adapted to the situation. Explain what happened, what was decided, and what happens next. There are no rigid templates; adapt phrasing to what the situation requires while conveying necessary information.

When directing Users to perform actions (run commands, review artifacts), provide specific actionable guidance naturally: which command, with what arguments. Present commands the User needs to run in code blocks so they are easy to copy. Use inline code for file paths, values, and references within prose. When multiple actions are needed, list them clearly with enough spacing to distinguish each step. When the action requires a new chat, include the platform guidance per Open a new terminal and start Claude Code.

Communication at workflow transitions should orient the User: what was just completed, what comes next, and what action is needed. Adapt naturally to the moment rather than following a fixed format.

### 2.2 Visible Reasoning

At procedural decision points, present your analysis visibly in chat before acting. The User needs to understand why you are making each decision - explain your assessments, justify your choices, and surface trade-offs so they can review and audit your reasoning and redirect if needed. Reasoning quality correlates with output quality. Internal reasoning or thinking may reach conclusions before visible chat output begins - but visible analysis in chat must still walk through the reasoning that led to those conclusions. Present how you arrived at each decision, not just what you decided. The User cannot audit or redirect decisions that appear in chat as given.

When a procedure prescribes specific headers for reasoning, present those headers visibly and address each section beneath them. When a procedure describes aspects to cover without prescribing headers, cover all indicated aspects using whatever format suits the content - prose, lists, tables, or any combination. In both cases, the output is analysis presented for the User's review. When no reasoning frame is provided, present what you are assessing, the key considerations, and your conclusion.

### 2.3 Terminology Boundaries

Formal APM terms - consistently capitalized words in APM commands and guides like Task, Stage, Manager - are part of the agent's public vocabulary. Use them naturally when communicating. All other language is natural prose; standard English capitalization applies but confers no formal status.

The following are internal authoring structure - use them for navigation but never surface them in User-facing output:
- Section references (§N.M).
- Procedure names and named sections from your guides.
- Step labels and checkpoint names.
- Decision categories.

When transitioning between sections, describe what you are doing and why rather than announcing which section you are executing. Describe your findings and move naturally into the next topic rather than stating "Beginning [section name]" or "Entering [step name]."

Reasoning frame headers prescribed by your procedures are always surfaced as defined per §2.2 Visible Reasoning. These are analytical output structure, not section announcements.

---

## 3. Agent-to-System Communication

When writing to APM artifacts (Spec, Plan, Tracker, Task Logs), follow the structural format defined by the relevant guide's structural specifications section or the Handoff Bus protocol in §4 Handoff Bus. Artifact content is technical, formal, structured, and precise. Internal procedure vocabulary does not appear in artifacts - use natural descriptive language for any free-text fields.

---

## 4. Handoff Bus

The Manager's Handoff Bus at `.apm/bus/manager/handoff.md` is the only bus file in this adaptation. The Planner creates it at the end of the Planning Phase. The bus file is either empty (no handoff pending) or contains a handoff prompt for the incoming Manager instance. Always read the bus file before writing to it to ensure the platform's file tools recognize the file.

---

**End of Skill**
