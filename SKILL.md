---
name: depone
description: Depone skill entrypoint. Design large, situation-aware multi-agent workflows for broad tasks that are too big for one normal agent turn. Use when a user asks for dynamic workflows, ultracode-style orchestration, large workflow design, multi-agent decomposition, codebase-wide audits, migrations, research sweeps, verification harnesses, or a plan that should scale across phases, subagents, gates, budgets, and resumable execution.
---

# Depone Skill Entrypoint

DWM means Deterministic Workflow Machine. Use this skill entrypoint to turn a
large objective into an executable workflow design. It is not a thin router. It
designs the workflow itself: phases, workers, parallelization, handoff
contracts, gates, budgets, evidence, and stop rules.

Do not run a large workflow just because a task is broad. First produce a
workflow design the user can inspect or that the current environment can execute.

## Start Here

1. Restate the objective, scope, constraints, and success criteria.
2. Inspect local context when the workflow depends on a repo, files, tools,
   branches, installed skills, or runtime state.
3. Decide the delivery layer:
   - Skill-only design when the current system lacks a workflow runtime.
   - Plugin when the workflow needs packaged skills, agents, scripts, or hooks.
   - Runtime/MCP when execution must be resumable, inspectable, and script-held.
4. Choose one or more patterns from `references/workflow-patterns.md`.
5. Write the workflow as phases with explicit worker prompts, inputs, outputs,
   verification gates, retry limits, and budget caps.
6. Identify which parts can run in parallel and which barriers are truly needed.
7. End with an execution path: direct Codex work, subagent plan, plugin
   scaffold, runtime execution, or backlog.

## Design Contract

Every workflow design must include:

- `objective`: the outcome, not the implementation guess.
- `surface`: repositories, paths, systems, or sources in scope.
- `assumptions`: guesses that affect the workflow and how to verify them.
- `phases`: ordered stages with clear entry and exit criteria.
- `workers`: roles, tool permissions, context limits, and ownership boundaries.
- `handoffs`: the exact artifacts passed between phases.
- `parallelism`: fan-out count, concurrency cap, and fan-in rules.
- `verification`: independent checks that can falsify the result.
- `risk gates`: approval points for destructive, external, costly, public API,
  dependency, database, production, secret, or history-rewrite actions.
- `budget`: time, token, model, retry, and file-touch limits.
- `resume plan`: what can be cached, replayed, skipped, or restarted.
- `execution path`: direct Codex work, subagent plan, plugin, runtime, or backlog.

## Pattern Rules

Prefer pipelines over barriers. A barrier is justified only when the next step
needs the complete prior set, such as global deduplication, cross-item ranking,
or final synthesis.

Use adversarial verification for claims, findings, migrations, and reviews.
A result is not trusted because a worker found it; it is trusted because an
independent verifier failed to refute it with evidence.

Use diverse reviewers when correctness depends on multiple failure modes:
correctness, security, performance, compatibility, UX, or reproducibility.

Use a loop-until-dry pattern for open-ended discovery, but cap the loop with
max rounds and a "no new findings" stop condition.

For every risk gate, state the safe default. When unsure, stop, preserve
completed artifacts, and ask the user before continuing.

## Output Format

For short requests, provide a compact workflow blueprint in the conversation.
For substantial work, emit both:

- `workflow.plan.json`: the machine-readable source of truth following
  `references/workflow-plan-schema.md`.
- rendered blueprint: a human-readable view derived from the same JSON.

The JSON and blueprint must agree on activation, the first wave containing one
or more slices, handoffs, verification, risk gates, budgets, and resume points.
Keep `first_slice` only as a compatibility alias when emitting JSON. If the
router-first rule does not justify activation, emit a downgrade artifact that
names the target: direct Codex, `workflow-router`, or a simple plan.

When writing a spec file, include:

1. Research and prior art.
2. Product position and non-goals.
3. Workflow architecture.
4. Execution model.
5. Safety and verification gates.
6. Evaluation fixtures.
7. Release or implementation plan.

If implementation follows, keep the first wave small enough to verify with real
slice reports, receipts, commands, fixtures, or generated workflow artifacts.
