# APM Auto 1.0.0 - Task Assignment Guide

## 1. Overview

**Reading Agent:** Manager

This guide defines how you construct and deliver Task Prompts for subagents, manage version control workspace isolation, and coordinate dispatch via Claude Code's `Agent()` tool. Task Prompts are self-contained - subagents receive everything needed to execute a Task without referencing the Spec or Plan.

### 1.1 Outputs

- *Task Prompt:* Prompt string passed to `Agent()` for subagent execution.
- *Follow-up Task Prompt:* Refined prompt when the review outcome determines retry.
- *Feature branches:* One branch per dispatch unit, created off the base branch.
- *Worktrees:* Isolated working directories under `.apm/worktrees/` for parallel dispatch.

---

## 2. Operational Standards

### 2.1 Dependency Context Standards

Tasks may depend on outputs from previous Tasks. You classify dependency context depth at dispatch time based on the dispatch plan for the current cycle.

**Intra-batch dependencies:** The producer task is earlier in the same batch (same subagent). The subagent has working familiarity from executing the producer. Provide light context - recall anchors, key file paths, brief reference to previous work. Detail increases with dependency complexity.

**Cross-dispatch dependencies:** The producer task was in a different dispatch unit or completed in a previous dispatch cycle. The subagent has zero familiarity. Provide comprehensive context - explicit file reading instructions, output summaries, integration guidance. Assume nothing.

**Dependency identification:** Check the Task's Dependencies field in the Plan. "None" indicates no dependencies.

**Chain reasoning:** Dependencies may have their own dependencies. Trace upstream when ancestors established patterns, schemas, or contracts the current Task must follow. Stop tracing when an intermediate node fully abstracts what came before. When uncertain whether an ancestor is relevant, include rather than risk missing critical context.

### 2.2 Task Prompt Content Standards

Task Prompts must be self-contained. Subagents have the same tools as any agent but are intentionally scoped to their Task Prompt and Rules to keep them focused on execution. You enforce this scoping by extracting relevant content from the Spec, Plan, and authoritative sources into each prompt rather than referencing those documents by path. Never reference the Spec, Plan, Tracker, or Index by path - subagents should not read them. Task Prompt instructions and objectives do not reference Stage numbers, other Task IDs, or coordination-level concepts (dependency context sections reference producer Tasks by ID as needed). Validation criteria are subagent-scoped.

**Embed** content the subagent cannot discover from the codebase alone: design decisions and constraints from the Spec, Task definitions and guidance from the Plan, Task-relevant coordination context from the Tracker, observations from the Index, corrected findings from previous Tasks, and content from authoritative User documents the Spec references. Preserve specificity with exact constraints, not summaries. Present all embedded content as direct factual context. Never attribute content to its source artifact or use coordination-level vocabulary.

**Reference with reading instructions** content that exists in the codebase: source files, existing patterns, configurations. Point the subagent to specific files and what to look for in them. This applies to both dependency context and Spec content that references codebase patterns.

**Exclude** content relating to other domains, providing background without actionable requirements, or already captured in the Task's Guidance field.

### 2.3 Follow-Up Standards

Follow-up Task Prompts occur when the review outcome determines retry after investigation. You arrive with: original Task Log findings, investigation results, understanding of what went wrong, and potentially modified planning documents.

**Content principle:** The follow-up is a completely new prompt dispatched to a fresh subagent with zero prior context. It is not a continuation - the new subagent has no knowledge of the previous attempt. The follow-up must be self-contained: refined Objective, Instructions, Output, and Validation based on what went wrong, plus an explicit follow-up context section explaining what was previously attempted, what issues were encountered, and what approach to take instead. Include the previous Task Log's diagnostics as factual context. Do not copy the previous prompt - give the subagent concrete, corrected direction.

**Log path continuity:** Use the same `log_path` as the original. The subagent overwrites the previous log, keeping memory coherent with one log per Task regardless of how many dispatches occurred. Capture iteration patterns in Stage summaries when relevant.

**Dispatch mechanism:** Always a fresh `Agent()` call. Subagents are ephemeral - there is no mechanism to continue a completed subagent.

### 2.4 Dispatch Standards

Before constructing individual Task Prompts, assess dispatch opportunities across Ready Tasks.

**Task readiness:** A Task is Ready when all its dependencies are Done. Read the Tracker for current statuses; cross-reference the Dependency Graph for newly unblocked Tasks.

**Dispatch modes.** Assess all Ready Tasks, group by Worker Group, and form dispatch units:
- *Batch:* Multiple Ready Tasks for the same Worker Group, dispatched as one subagent. Candidates either form a sequential chain (each depends only on the previous or already-complete Tasks) or are an independent group (no dependencies between them, all Ready simultaneously). When forming chains, weigh whether external Tasks depend on intermediate results - if so, dispatching individually allows earlier review and unblocks dependent work sooner. Soft guidance is 2-3 Tasks per batch.
- *Single:* One Ready Task as one subagent.
- *Parallel:* Two or more dispatch units (any mix) with no unresolved dependencies among them, dispatched as multiple concurrent subagents. Requires version control workspace isolation.

Before dispatching a ready unit, check whether a pending review would unlock Tasks that combine well with the current unit. If it is the only outstanding result, waiting costs little. If multiple results are pending or no plausible combination exists, dispatch immediately.

**Wait state:** When no Tasks are Ready but subagents have not yet returned, communicate what was processed, what is pending, and what the User should expect next.

### 2.5 Version Control Standards

Version control provides workspace isolation during parallel dispatch. Each dispatch unit operates on its own feature branch, and you coordinate all merges during Task Review. When multiple repositories are listed in the Tracker's Version Control table, identify which repository each Task operates in from the Spec's Workspace section. If the User initially declined version control but later requests it mid-session, initialize it: run `git init` if needed, detect or confirm the base branch, establish conventions with the User, update Rules and the Tracker, then proceed with branch-based dispatch.

**Branch standards:** Every dispatch unit gets its own feature branch off the base branch per the branch convention in the Tracker. APM terminology (Task IDs, Stage numbers, domain identifiers) does not appear in branch names, commit messages, or worktree directory names - these reflect the actual work, not the framework managing it. A batch of sequential Tasks assigned to the same Worker Group shares one branch.

**Worktree standards:** Worktrees are created only for parallel dispatch. Each parallel dispatch unit gets its own worktree so all parallel subagents operate in isolated directories and the main working directory remains on the base branch for merge operations. For sequential dispatch, the subagent operates in the main working directory on its feature branch.

- *Layout:* Worktrees placed under `.apm/worktrees/` per §4.3 Branch and Worktree Standards.
- *Concurrency limit:* Maximum 3-4 concurrent worktrees.
- *Lifecycle:* Short-lived - created before dispatch, removed after merge.

Worktrees contain only tracked files; if a subagent needs untracked assets, note this in the Task Prompt. When `.apm/` is tracked (or partially tracked), the worktree may contain `.apm/` files but all APM runtime operations (Task Logs) must target the project root's `.apm/`, not the worktree copy. Include this guidance in the Task Prompt's Workspace section for worktree dispatch.

**Why not `isolation="worktree"`:** Claude Code's auto-worktree creates branches named `worktree-<slug>` at `.claude/worktrees/`, which does not follow APM's branch naming conventions. Manual worktree management gives you full control over branch names and paths.

### 2.6 Dispatch Mechanics

Dispatch via `Agent(subagent_type="apm-worker", description="<short task label>", prompt=<task_prompt_content>)`. The `apm-worker` agent definition at `.claude/agents/apm-worker.md` provides the subagent's behavioral rules as its system prompt; the `prompt` parameter contains the task-specific content. The `description` parameter is required on every call. For batches, the prompt contains a batch envelope with multiple Task Prompts. For parallel dispatch, multiple calls in a single message run concurrently.

**Foreground by default.** All dispatch runs in the foreground - you block until each subagent returns. This includes parallel dispatch: multiple foreground `Agent()` calls in a single message run concurrently, and you block until all return. Background dispatch is a separate concern - it allows you to continue doing other work while subagents run, but is only used if the User explicitly requested it during the understanding summary and confirmed that Claude Code permissions are properly configured. Background subagents with default permissions silently fail on tool approvals, wasting context and tokens.

---

## 3. Task Assignment Procedure

Dispatch assessment followed by per-Task analysis and prompt construction for each Task in the dispatch plan. Follow-up prompts use a separate construction path when a review outcome requires retry.

### 3.1 Dispatch Assessment

Assess dispatch opportunities from current project state per §2.4 Dispatch Standards. Before each dispatch decision, assess the current project state visibly in chat under the header **Dispatch Assessment:** covering which Tasks are Ready, what dependency relationships exist among them, and what dispatch mode best serves progress and efficiency. Each dispatch cycle is a fresh assessment.

Perform the following actions:
1. Identify Ready Tasks from the Tracker. Cross-reference the Dependency Graph for newly unblocked Tasks.
2. Check whether a pending result would unlock Tasks that combine well with currently Ready Tasks. If waiting costs little, consider it. Otherwise proceed.
3. Group Ready Tasks by Worker Group. Form dispatch units per §2.4 Dispatch Standards - assess all three modes (single, batch, parallel) before committing to a dispatch plan.
4. Assess parallel opportunity: if 2+ dispatch units exist with no unresolved dependencies - parallel dispatch.
5. Formulate dispatch plan: which dispatch units, whether parallel. For each Task, continue to per-Task analysis.

### 3.2 Per-Task Analysis

Execute for each Task in the dispatch plan.

Perform the following actions:
1. Read the Task's Dependencies field from the Plan. If "None," skip dependency context steps.
2. For each dependency, classify context depth per §2.1 Dependency Context Standards based on the dispatch plan: intra-batch (producer is earlier in the same batch) or cross-dispatch (everything else). Trace upstream when ancestors are relevant.
3. For cross-dispatch dependencies, read unique producer Task Logs and note key outputs, file paths, and integration details. When multiple Tasks in this dispatch cycle depend on the same producer, read that log once and extract from context for subsequent Tasks.
4. Extract Spec content relevant to this Task per §2.2 Task Prompt Content Standards. The Spec is in context from session start and refreshed on any modification. A fresh read is warranted at the start of a new Stage's first dispatch; per-Task re-reads of an unchanged Spec are not needed.
5. Extract Task definition fields from the Plan: Objective, Steps, Guidance, Output, Validation. When Guidance references Spec sections, resolve those references and extract the referenced content per §2.2 Task Prompt Content Standards. Transform steps into actionable instructions, incorporating Guidance and relevant Spec content.

### 3.3 Task Prompt Construction

Assemble the Task Prompt and dispatch via `Agent()`.

Perform the following actions:
1. Construct YAML frontmatter per §4.1 Task Prompt Format.
2. Construct prompt body: Task Reference, Context from Dependencies (if applicable), Objective, Detailed Instructions, Workspace, Expected Output, Validation Criteria, Instruction Accuracy, Task Logging path.
3. Create a feature branch off the repository's base branch per §2.5 Version Control Standards. For parallel dispatch, create a worktree: `git worktree add .apm/worktrees/<branch-slug> -b <branch-name>`. Include the branch name (sequential) or worktree path (parallel) in the Workspace section.
4. Record the branch name in the Task row's Branch column when updating the Tracker.
5. Dispatch per §2.6 Dispatch Mechanics. For batches, use §4.5 Batch Envelope Format to combine multiple Task Prompts in the prompt content.

### 3.4 Follow-Up Task Prompt Construction

Execute when the review outcome (per `.claude/apm-guides/task-review.md` §3.3 Review Outcome) determines follow-up is needed.

Perform the following actions:
1. Capture follow-up context: what went wrong, investigation findings, required refinement, any planning document modifications.
2. If planning documents were modified, extract relevant updated content per §3.2 Per-Task Analysis.
3. Refine all content sections per §2.3 Follow-Up Standards. Include a follow-up context section explaining the issue and required refinement.
4. Construct the follow-up prompt per §4.2 Follow-Up Format. Same `log_path` as the original.
5. Dispatch per §2.6 Dispatch Mechanics.

---

## 4. Structural Specifications

### 4.1 Task Prompt Format

Task Prompts are markdown content passed as the `prompt` parameter to `Agent()`. Adapt based on Task needs - not all sections are required for every Task.

**YAML Frontmatter Schema:**
```yaml
---
stage: 1
task: 2
domain: frontend
log_path: ".apm/memory/stage-01/task-01-02.log.md"
has_dependencies: true
---
```

**Field Descriptions:**
- `stage`: Stage number.
- `task`: Task number within Stage.
- `domain`: Worker Group identifier (kebab-case).
- `log_path`: Pre-constructed path for the Task Log. Path pattern: `.apm/memory/stage-<NN>/task-<NN>-<MM>.log.md` (relative to the project root). All Tasks in the same Stage share the same Stage directory. You construct the path; the subagent writes directly to it.
- `has_dependencies`: Whether dependency context is present.

**Prompt Body Sections:**
- *Title.* `#` heading using Task ID and title. Each section uses `##` heading:
- *Task Reference:* Task ID and assigned domain.
- *Context from Dependencies.* Included when `has_dependencies: true`. Format depends on dependency type per §2.1 Dependency Context Standards.
  - *Intra-batch.* "Building on your previous work:" intro - `**From Task <N>.<M>:**` with key outputs and recall points - `**Integration Approach:**` with brief guidance.
  - *Cross-dispatch.* "This Task depends on work completed previously:" intro - `**Integration Steps:**` numbered file reading instructions - `**Producer Output Summary:**` key features, files, interfaces, constraints - `**Upstream Context:**` for relevant ancestors.
- *Objective:* Single-sentence Task goal, optionally enhanced with coordination-level context.
- *Detailed Instructions:* Plan steps transformed into actionable instructions with integrated Spec content and guidance.
- *Workspace:* Working directory and branch name for sequential dispatch, or worktree path and project root for parallel dispatch. For worktree dispatch, instruct the subagent to perform code work in the worktree but resolve all `.apm/` paths (Task Log) from the project root. Subagent operates in the specified workspace, commits there, and notes it in the Task Log. Subagents do not merge.
- *Expected Output:* Deliverables from Plan Output field.
- *Validation Criteria:* From Plan Validation field.
- *Instruction Accuracy:* The objective and expected output are authoritative - deliver those. However, the detailed instructions and steps were constructed from planning documents and may contain inaccurate details, missed prerequisites, or outdated assumptions about the codebase. When a specific instruction contradicts what the codebase actually shows, validate the actual state rather than persisting with the instruction as written.
- *Task Logging:* The `log_path` where the subagent writes the Task Log. The `apm-worker` agent definition contains the logging format and procedure - no additional logging instructions needed in the prompt.

### 4.2 Follow-Up Format

Follow-up Task Prompts use the same structure as §4.1 Task Prompt Format with these modifications:
- *Title:* `APM Follow-Up Task: <Task Title>`
- *Follow-up context section* after Task Reference - previous issue, investigation findings, required refinement, additional guidance.
- *All content sections* refined based on what went wrong, not copied from the previous attempt.
- *Same `log_path`* as the original Task Prompt.

### 4.3 Branch and Worktree Standards

Branch naming follows the convention recorded in the Tracker Version Control table. Branch names are descriptive of the actual work; for batches, the name reflects the batch scope. Worktrees are placed under `.apm/worktrees/`. Each subdirectory name is derived from the branch name (e.g., replacing `/` with `-`). Each worktree directory contains a full checkout of all tracked files. Untracked files are not present.

### 4.4 Tracker VC Entry Format

VC configuration recorded in the Version Control table within the Tracker, with one row per repository. Branch state is tracked per-Task in the Task table's Branch column - an incoming Manager reads Task rows to rebuild working VC context.

**Format:**

```markdown
## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| <repo-name> | <branch-name> | <convention> | <convention> |
```

### 4.5 Batch Envelope Format

When sending multiple Tasks to a subagent in a batch, the prompt string uses this structure:

**YAML Frontmatter Schema:**
```yaml
---
batch: true
batch_size: <N>
tasks:
  - stage: 1
    task: 1
    log_path: ".apm/memory/stage-01/task-01-01.log.md"
  - stage: 1
    task: 2
    log_path: ".apm/memory/stage-01/task-01-02.log.md"
---
```

**Field Descriptions:**
- `batch`: Always `true` for batch envelopes.
- `batch_size`: Total Tasks in the batch.
- `tasks[].stage`: Stage number.
- `tasks[].task`: Task number within Stage.
- `tasks[].log_path`: Pre-constructed path for the Task Log, following the same pattern as single Task Prompts.

**Body:** Individual Task Prompts separated by `---` delimiters. Each Task Prompt retains its full structure (YAML frontmatter and body) as if standalone.

---

## 5. Common Mistakes

- *Planning document paths in Task Prompts:* Subagents are scoped to their Task Prompt and Rules - the Spec and Plan are not in their context. A reference like "see the Spec" or "check the Plan" breaks self-containedness. Extract and embed the relevant content instead.
- *Under-scoped cross-dispatch context:* Cross-dispatch dependencies require comprehensive context regardless of perceived simplicity. Subagents have no access to other subagents' work - the only context they receive is what you embed in the Task Prompt.
- *Shallow dependency chains:* A Task's direct dependency may itself depend on earlier work that established patterns, schemas, or contracts. Trace upstream until an intermediate node fully abstracts what came before.
- *Vague instructions:* "Implement the feature properly" vs "Implement POST /api/users with email validation using express-validator, returning 201 on success."
- *Dispatching before merging dependencies:* If Task B depends on Task A's output and A was on a separate branch, A must be merged before B's branch is created.
- *Assuming base branch name:* Read the base branch from the Tracker's Version Control table for the relevant repository. Do not assume `main` or `master`.

---

**End of Guide**
