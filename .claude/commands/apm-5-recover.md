---
command_name: recover
description: Recover the APM Manager's working context.
---

# APM Auto 1.0.0 - Recover Command

This command reconstructs the Manager's working context after platform auto-compaction, manual compaction, or when the Manager must resume after a cleared or lost conversation. If you are a Planner or non-APM agent, concisely decline and take no action.

**Procedure:**
1. Re-read your initiation command (`.claude/commands/apm-2-initiate-manager.md`) and read every document it references - every guide, skill, agent definition, and project artifact listed in its loading sequence. Reading the initiation command alone is not sufficient - the documents it references contain the procedural knowledge and project state needed for recovery. Skip identity determination and greeting.
2. Explore project state from the artifacts listed in your initiation command and the current state of the codebase to reconstruct where work stands. When gaps remain that artifacts cannot fill, ask the User for brief context before continuing.
3. Note the recovery event: add a working note to the Tracker. Recovery does not increment the instance number - you continue as the same instance. When eventually performing Handoff, note which portions of working context are reconstructed rather than first-hand.
4. Continue with duties per `.claude/commands/apm-2-initiate-manager.md` §3 Autonomous Coordination Loop.

---

**End of Command**
