---
name: workflow-router
description: Use when a request is broad, ambiguous, or multi-step and the right workflow (implementation, debugging, review, GitHub, research, workflow design, system triage, artifacts) must be chosen before execution.
---

# Workflow Router

Use this skill as a thin control layer. Classify the request, pick the smallest
workflow that can finish it, call specialized skills or roles only when useful,
and close with concrete verification evidence.

Do not turn this into a general autonomous loop engine. Keep the loop bounded,
reversible, and tied to the user's current goal.

## Activation Contract

This skill activates when the user names `$workflow-router`, asks for workflow
routing, or the description matches broad, ambiguous, or multi-step work. It
is not a background policy, daemon, or global override.

Once active, use `SKILL.md` plus `references/router-map.md` as the runtime
contract. If the request is clearly a one-step task, keep routing lightweight:
classify it, act directly, and verify without extra ceremony. When another
loaded skill imposes stricter limits, the stricter rule wins.

## Start Here

1. Restate the operational goal in one sentence for yourself.
2. Inspect local context before deciding if the request depends on repo,
   machine, GitHub, or installed skill state.
3. Classify the task using `references/router-map.md`.
4. Load any triggered specialized skill before acting.
5. Execute the chosen workflow end to end when the action is reversible and
   within scope.
6. Verify with the smallest meaningful command, UI check, artifact metric, or
   source citation that proves the requested behavior.

If the user asks only for options, market research, or a strategy, stop after
the decision and do not create files or run write actions.

## Routing Rules

Prefer a single specialized path over several overlapping ones.
If two routes seem plausible, choose the route that provides the earliest verifiable evidence; a failing CI request is a debugging route with GitHub context.

- Implementation: read relevant files, make a minimal diff, run focused tests,
  then summarize changed files and verification.
- Debugging: reproduce first, minimize the failing surface, instrument
  only as needed, fix, then add or run a regression check.
- Review: findings first, ordered by severity, with file and line references.
  Summaries are secondary.
- GitHub: resolve repo and branch state, inspect PR/issue/CI context,
  then use GitHub-specific workflows or `gh` for gaps.
- Research: prefer official/current sources and cite URLs. For local
  repo decisions, local architecture beats generic web guidance.
- Workflow design: decide whether the right artifact is a skill, plugin, MCP,
  script, repo doc, or direct implementation path, then validate the
  decision with a real prompt, command, or documented evaluation path.
- System triage: sample live state before explaining causes. Do not
  rely on stale summaries for process, storage, config, or runtime claims.
- Artifact: prove the artifact changed in the consumer-visible layer,
  such as rendered pixels, DOCX XML/text, slide render, or spreadsheet cells.

## Loop Discipline

Use bounded repair loops:

- A repair attempt is one action/check cycle: a command, patch, tool call,
  browser check, or external call followed by its observed result.
- The first failed action counts as attempt 1.
- Retry the same approach at most two additional times when the failure is
  clearly transient or mechanical.
- If the same error appears across three attempts, change strategy instead of
  repeating.
- Stop after five total repair attempts in one workflow. A new signal
  justifies a strategy switch inside the cap, never extending it.
- Preserve the strongest evidence gathered before reporting a blocker.

Each loop must improve at least one of: reproduction fidelity, fault
localization, patch quality, or verification strength. A loop that only reruns
the same command is not progress.

## Risk Gate

Proceed autonomously with reversible local reads, new files, small edits, local
tests, local commits when requested, and normal pushes when the user requested
publishing.

Pause for explicit confirmation before destructive or externally visible work:

- force push, hard reset, clean, branch deletion, or history rewrite
- deleting files or directories
- package installs or dependency changes
- database migrations
- production deploys
- payments, subscriptions, secret access, or external messages
- public API changes when not clearly requested

Secrets must never be committed. Before pushing a new or changed public repo, run a
lightweight secret pattern scan or a stronger available scanner.

Never fabricate data to satisfy validation. If evidence is missing, say what is
missing and what was verified instead.

## Completion Gate

Before claiming completion:

1. Run the smallest meaningful verification step available.
2. Confirm the output directly, not from memory.
3. Separate passing evidence from blocked or skipped checks.
4. Give the user the result, changed paths, and any remaining risk.

Include browser or screenshot verification for visual work with a local
target, actual command behavior for command-line work, and cited sources for
research.
