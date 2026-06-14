# Dynamic Workflow Designer Skill Spec

Status: V0.5 implemented, Last updated: 2026-06-14

## Purpose

`dynamic-workflow-designer` helps Codex design large, situation-aware workflows
for work that is too broad for a single normal agent turn. It fills the gap
between a thin route selector and a full workflow runtime.

The skill should produce a concrete workflow architecture: phases, workers,
parallelism, handoff artifacts, verification gates, safety gates, budgets, and
resume strategy. It may later become a Codex plugin or runtime-backed system,
but v0 is a spec-first skill.

## Product Position

The existing `workflow-router` skill chooses the smallest suitable workflow and
keeps execution bounded. This skill does a different job: it designs the
workflow itself for a very large task.

Positioning:

- `workflow-router`: classify and route ordinary broad work.
- `dynamic-workflow-designer`: design an ultracode-style workflow for major
  work before execution.
- Future `workflow-orchestrator` plugin/runtime: execute saved workflow plans
  with resumability, monitoring, and subagent coordination.
- V0.5 continuation gate: prove the machine-readable `workflow.plan.json`
  contract, deterministic fixture corpus, and evaluator before plugin/runtime
  work begins. V0.5 validates tracked sample artifacts; it does not run a live
  model against `SKILL.md`.

## Users

Primary user: a local power user who wants Codex to structure large tasks
across repos, artifacts, research, and verification without losing control of
scope or evidence.

Secondary user: another agent instance that needs a compact design contract
before running many agents or starting a long implementation.

## Prior Art

See `docs/github-research.md`.

Key conclusions:

- Claude Dynamic Workflows move orchestration out of chat and into a script.
- Community repos already explore JavaScript harnesses, MCP runtimes, viewers,
  journals, and workflow command distribution.
- This repo should not copy a runtime yet. It should first define a checkable
  workflow-design contract and deterministic samples that can later be tested
  against live Codex output, existing subagent tools, a plugin, or a dedicated
  runtime.

## Scope

### V0: Skill And Spec

Deliver a Codex skill that designs workflows and writes inspectable specs.

Required behavior:

1. Identify when a task deserves dynamic workflow design instead of direct work.
2. Inspect relevant local context before designing repo-specific workflows.
3. Choose patterns from `references/workflow-patterns.md`.
4. Produce workflow blueprints with phases, workers, handoffs, gates, budgets,
   and verification.
5. Distinguish skill-only execution from plugin/runtime requirements.
6. Include evaluation fixtures for the generated designs.

### V1: First-Slice Compiler

Implement the first-slice compiler specified in
`docs/v1-first-slice-compiler-spec.md`: compile an activated
`workflow.plan.json` into one inspectable first-slice packet, prompt, gate
state, and resume/status files without claiming full automatic orchestration.

V1 may package reusable helper assets only when they support this compiler
contract. It must remain useful without a durable runtime, plugin daemon, or
automatic subagent dispatcher.

### V2: Runtime Prototype

Only after V0/V1 prove useful, consider a runtime with:

- generated workflow scripts or JSON plans
- phase graph and status file
- subagent spawn adapters
- durable journal
- resume from completed phase outputs
- viewer or textual progress map

## Non-Goals

- Do not replace `workflow-router`.
- Do not build a full durable runtime in the first slice.
- Do not vendor external runtime code.
- Do not auto-spawn many subagents without explicit user authorization.
- Do not hide destructive or costly actions behind workflow generation.
- Do not treat a workflow blueprint as proof that work is complete.

## Activation Contract

The skill activates when:

- the user names `$dynamic-workflow-designer`
- the user asks for dynamic workflows, ultracode-style orchestration, or a
  workflow that can handle a very large task
- the task clearly requires multi-phase, multi-agent design before execution

The skill should not activate for ordinary small implementation, debugging, or
review tasks. Those remain `workflow-router` or direct Codex work.

## Workflow Design Output

Every substantial design must include:

| Field | Meaning |
| --- | --- |
| Objective | Desired outcome, stated independently of implementation |
| Surface | Repos, paths, systems, APIs, artifacts, or sources in scope |
| Assumptions | Guesses that affect the workflow and must be verified |
| Phases | Named stages with entry and exit criteria |
| Workers | Roles, ownership, allowed tools, and context boundaries |
| Handoffs | Artifacts and schemas passed between phases |
| Parallelism | Fan-out shape, concurrency cap, and fan-in rules |
| Verification | Checks designed to falsify claims or edits |
| Gates | Human approval points and safe defaults |
| Budget | Token, time, retry, agent-count, and file-touch limits |
| Resume | Cacheable outputs and invalidation rules |
| Execution path | Direct Codex, subagent plan, plugin, runtime, or backlog |

## Pattern Selection

Use these defaults:

- Sequential for strict dependencies.
- Pipeline for repeated item-level stages.
- Parallel fan-out/fan-in for independent surfaces.
- Adversarial verify for findings and claims.
- Judge panel for alternatives.
- Loop until dry for open-ended discovery.
- Human gate for risky actions.
- Resume/cache for expensive prefixes.

Prefer pipeline over a barrier unless the next phase needs the complete prior
set. Barriers are allowed for global deduplication, ranking, cross-item
comparison, and final synthesis.

## Safety

Workflow designs must explicitly gate:

- force push, hard reset, branch deletion, or history rewrite
- deleting files or directories
- dependency installation
- database migrations
- production deploys
- public API changes
- paid external API usage
- secret access or external messages

The safe default is to stop, preserve artifacts, and ask the user.

## Verification

A workflow design is acceptable only when it names how success can be checked.

Examples:

- Code migration: changed call sites plus tests, typecheck, and independent
  review of missed call sites.
- Research: sources gathered independently, claims extracted, claims verified
  against sources, unsupported claims filtered.
- Bug hunt: candidate findings, adversarial refutation, reproduction evidence,
  and deduped confirmed findings.
- Artifact work: rendered or parsed artifact evidence, not only file edits.

## Evaluation Fixtures

Future changes should be tested against these prompts:

| Prompt | Expected output focus |
| --- | --- |
| "Design a workflow to audit every API route for missing auth." | pipeline scan, adversarial verify, read-only safety |
| "Plan a 500-file migration from legacyFetch to the new client." | discovery, batching, write gates, regression verification |
| "Research the current state of on-device LLM inference." | multi-angle research, source verification, citation filtering |
| "Stress-test three architecture options before we pick one." | judge panel, rubric, synthesis with tradeoffs |
| "Find every unsupported claim in this PR description." | claim extraction, repo-grounded verification, proof ledger |
| "Make a workflow runtime for this skill." | plugin/runtime boundary, small first slice, no overbuild |

For each fixture, record:

- selected patterns
- whether local context was inspected when needed
- whether risky actions were gated
- whether verification can falsify the result
- whether the plan overclaims execution

### Fixture Smoke Gate

Before calling v0 final, run at least two fixtures against the current skill
instructions:

1. one codebase-facing fixture, such as the API auth audit or 500-file migration
2. one non-code or meta fixture, such as research, architecture judging, or
   runtime planning

Each smoke output passes only if it includes every field in
`Workflow Design Output`, chooses patterns from `references/workflow-patterns.md`,
names at least one falsifiable verification check, gates risky actions with a
safe default, and does not imply the requested work has already been executed.

Record the prompt, selected patterns, generated workflow output, failed
criteria, and resulting spec/skill change if any under `docs/fixture-smoke/`. If
a fixture fails, update `SKILL.md`, `docs/spec.md`, or
`references/workflow-patterns.md`, then rerun the fixture category that failed.

## Release Criteria

V0 is releasable when:

- `scripts/quick_validate_skill.py` passes on the skill folder.
- `SKILL.md` has no placeholders.
- `agents/openai.yaml` matches the skill name and purpose.
- `docs/github-research.md` records prior-art decisions.
- `docs/spec.md` has fixtures and non-goals.
- `references/workflow-patterns.md` gives enough pattern guidance for v0.
- at least two fixture smoke checks pass, covering one codebase-facing fixture
  and one non-code or meta fixture, with records in `docs/fixture-smoke/`.
- V0.5 remains a separate continuation gate; V0 release does not claim the
  evaluator slice is complete.
- whitespace check passes.
- secret scan finds no committed secrets.

V0.5 is releasable when:

- `references/workflow-plan-schema.md` documents `workflow.plan.json`.
- `scripts/evaluate_plan.py --self-test` passes.
- `fixtures/v0.5/manifest.json` includes four positive, four negative, three
  borderline, and one meta/runtime fixture.
- tracked candidate samples under `samples/v0.5/candidates/` validate as
  schema-valid plans or valid downgrade artifacts.
- tracked raw outputs under `samples/v0.5/raw/` are distinct from parsed plans
  and contain `raw_kind`, `fixture_id`, the prompt, producer, current
  `SKILL.md` hash, packet hashes, parsed `workflow_plan`, and rendered blueprint
  that matches the parsed plan.
- each fixture has a structured consumer report under `samples/v0.5/consumer/`.
- both confirmed baseline snapshots, `workflow-router-skill` and
  `claude-agent-workflow-designer`, are scored through fixture-indexed,
  prompt-matched source-hashed normalization-failure records whose scores are
  derived by the evaluator from structured source-snapshot observations.
- `python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out
  out/v0.5` regenerates scorecards, parsed plans, raw outputs, skill hashes, and
  rendered blueprints, then validates and copies tracked consumer reports; the
  command exits nonzero if the keep/kill decision is not `keep` or if
  `docs/v0.5-decision.md` drifts from the regenerated summary.
- `docs/v0.5-decision.md` records the keep/kill outcome.

V1 is releasable when:

- `docs/v1-first-slice-compiler-spec.md` defines the compile and resume-check
  behavior.
- V1 `source_plan_path` must be repository-relative in V1; off-repo
  `workflow.plan.json` inputs are rejected at compile time.
- `scripts/compile_workflow.py --self-test` passes.
- `python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out
  out/v1/final` passes and writes `summary.json`.
- Existing V0/V0.5 release checks still pass.
- required V1 compiler fixtures pass, covering activated plans, downgrade
  refusal, output path safety, symlink escape rejection, risk gate blocking,
  prompt/packet drift, and resume invalidation.
- generated first-slice packet prompts structurally agree with packet JSON.
- `docs/v1-decision.md` records the keep/kill outcome.

### Reproducible Check

Run from the repository root:

```bash
python scripts/quick_validate_skill.py .
python scripts/quick_validate_skill.py --self-test
```

```bash
python scripts/check_whitespace.py .
```

```bash
python scripts/check_release_text.py .
```

```bash
python scripts/check_release_text.py --self-test
```

```bash
python scripts/check_contract.py
python scripts/check_contract.py --self-test
```

```bash
python scripts/evaluate_plan.py --self-test
python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5
```

V1 compiler checks:

```bash
python scripts/compile_workflow.py --plan workflow.plan.json --out out/v1/<run_id>
python scripts/compile_workflow.py --resume out/v1/<run_id>
python scripts/compile_workflow.py --self-test
python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final
```

The V0.5 manifest depends only on tracked baseline source snapshots named in
`fixtures/v0.5/manifest.json`. The manifest evaluator regenerates `out/v0.5/`
and verifies that `docs/v0.5-decision.md` matches the freshly generated summary.

## Open Questions

- Whether V2 should add Claude plugin packaging after the Codex-first
  first-slice compiler proves useful.
- Whether a future runtime should wrap existing projects such as
  `claude-dynamic-workflows-codex` after the smaller local adapter proves useful.
- Whether the V0.5 JSON schema should later compile to JavaScript workflow
  scripts, MCP runtime plans, or both.
- Whether forward-testing should use live subagents or fixture-only review for
  the first release.
