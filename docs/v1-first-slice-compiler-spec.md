# V1 First-Slice Compiler Spec

Status: draft
Date: 2026-06-14

## Purpose

V0.5 proved that `dynamic-workflow-designer` can emit deterministic,
schema-valid workflow plans and evaluate them against a tracked fixture corpus.
V1 should close the next practical gap without pretending to be a full workflow
runtime: compile an activated `workflow.plan.json` into one inspectable
first-slice execution packet plus the files needed to audit, dispatch, block,
or resume that first slice safely.

V1 is a packet compiler, not a runner. It does not execute shell commands,
spawn subagents, advance between phases, or mark work complete. Those behaviors
belong to V2 after the file contract is proven.

## Product Position

| Layer | Responsibility | V1 stance |
| --- | --- | --- |
| `workflow-router` | choose the smallest suitable workflow | unchanged |
| `dynamic-workflow-designer` | design phases, workers, gates, handoffs | source of `workflow.plan.json` |
| V1 first-slice compiler | materialize the first executable packet and safety files | implement now |
| Future runtime | durable orchestration, packet advancement, monitoring, subagent scheduling | defer |

V1 should make a workflow easier to start after context loss. It should not
claim Claude Dynamic Workflow-style orchestration. The measurable value is that
another Codex agent can open a run directory, read `README.md`, inspect the
first-slice prompt and packet JSON, see blocked gates, and know exactly what is
safe to do next.

## Goals

- Accept only activated V0.5 `workflow.plan.json` artifacts.
- Compile the plan's `execution_path.first_slice` into one packet JSON and one
  prompt Markdown file.
- Preserve enough plan graph context to explain where the first slice sits,
  without compiling the whole workflow into executable packets.
- Emit deterministic gate, handoff, and packet identifiers.
- Store canonical hashes for plan, packet, prompt, first-slice inputs, handoff
  schemas, and approval state.
- Block risky first slices by default with machine-readable approval state.
- Provide deterministic self-tests and fixtures that fail for weak prompt/packet
  agreement, stale resume state, unsafe output paths, and unapproved risk gates.

## Non-Goals

- Do not automatically spawn subagents.
- Do not execute shell commands from the plan.
- Do not execute validation commands listed in handoff schemas.
- Do not compile all phases into runnable packets.
- Do not maintain `running`, `completed`, or `failed` status.
- Do not implement a viewer, background daemon, or persistent service.
- Do not treat a compiled packet as evidence that workflow work has been done.
- Do not vendor Claude Dynamic Workflow runtimes.

## Scope Boundary

V1 compiles only the first slice:

- Input must be an activated V0.5 plan.
- Downgrade artifacts are rejected. There is no `--allow-downgrade` path in V1.
- Exactly one executable packet is generated: `001-first-slice`.
- Later phases, workers, barriers, and handoffs are copied as context and schema
  references, not as runnable packet state.
- `ready` means "ready for a human or Codex agent to dispatch manually after
  reading the packet." It does not mean the compiler will run it.

V2 owns:

- packet-to-packet advancement
- automatic worker scheduling
- execution evidence ingestion
- status transitions for running/completed/failed work
- durable resume from completed intermediate outputs
- dashboard or viewer

## Command Contract

V1 adds one stdlib-only script:

```bash
python scripts/compile_workflow.py --plan workflow.plan.json --out out/v1/<run_id>
```

Required modes:

```bash
python scripts/compile_workflow.py --plan workflow.plan.json --out out/v1/<run_id> --mode compile
python scripts/compile_workflow.py --resume out/v1/<run_id>
python scripts/compile_workflow.py --self-test
```

Mode semantics:

- `--mode compile`: validate the plan, clear or create a fresh run directory,
  write all V1 artifacts, and exit without executing anything.
- `--resume`: read an existing run directory, recompute hashes, update only
  `status.json` and `resume.md`, and exit without executing anything.
- `--self-test`: run positive and negative in-memory cases plus tracked V1
  fixtures once they exist.

There is no `first-slice` execution mode in V1. The first slice is compiled, not
run.

## Output Path Safety

By default, `--out` must resolve under the repository-local `out/v1/` directory.
The compiler must use resolved real paths for containment checks and reject:

- `.`
- repository root
- `out/`
- `out/v1/`
- paths outside repository-local `out/v1/`
- symlinks that escape repository-local `out/v1/`
- existing non-directory paths

The compiler may delete and recreate only the selected `out/v1/<run_id>`
directory. It must not delete any path outside that resolved run directory.

Future versions may add an explicit unsafe external output override, but V1 does
not include it.

## Generated Artifact Tree

Given an activated plan:

```text
workflow.plan.json
```

The compiler writes:

```text
out/v1/<run_id>/
├── README.md
├── run.json
├── status.json
├── resume.md
├── plan.snapshot.json
├── plan.sha256
├── packets/
│   ├── 001-first-slice.packet.json
│   └── 001-first-slice.prompt.md
├── handoffs/
│   └── <handoff-id>.schema.json
├── gates/
│   ├── approval-state.json
│   └── <gate-id>.approval.md
└── context/
    ├── phases.json
    ├── workers.json
    └── parallelism.json
```

`README.md` is the operator entry point. It must name the packet prompt to read
first, the blocked gates, the allowed next manual action, and the fact that V1
does not execute the workflow.

## Deterministic IDs

All IDs are derived from canonical JSON plus source position:

- packet ID: always `001-first-slice`
- handoff ID: `handoff-<zero-padded-index>-<sha8(canonical_handoff_json)>`
- gate ID: `gate-<zero-padded-index>-<sha8(canonical_gate_json)>`

The source index is the item order in `workflow.plan.json`; the hash is computed
from the canonical JSON object after sorting object keys. Reordering handoffs or
gates is therefore a semantic change for V1 resume purposes and invalidates
related snapshots.

## Validation Interface

`compile_workflow.py` must validate plans by importing the existing stdlib
validator function from `scripts/evaluate_plan.py`:

```python
from evaluate_plan import EvaluationError, validate_plan
```

The compiler must call `validate_plan(plan)` before generating artifacts. It
must not shell out to `evaluate_plan.py` for validation, and it must not duplicate
the V0.5 schema rules.

If `evaluate_plan.py` changes its public validation function, this spec and the
compiler must be updated in the same change.

## `run.json`

Required fields:

- `run_id`
- `schema_version`: `"1.0"`
- `created_at`
- `source_plan_path`
- `plan_hash`
- `runner_version`
- `mode`: `"compile"` or `"resume-check"`
- `risk_policy`: `"block-all"`
- `status_path`
- `packet_paths`
- `approval_state_path`

`risk_policy` is fixed to `block-all` in V1. Approved execution is outside V1;
approval files exist only to make manual gates explicit and machine-checkable.

## `status.json`

Required fields:

- `run_id`
- `plan_hash`
- `resume_state`: `fresh`, `resumable`, or `invalidated`
- `packet_statuses`
- `handoff_statuses`
- `gate_statuses`
- `snapshots`
- `invalidators`

Packet status schema:

- `packet_id`
- `status`: `ready`, `blocked-risk-gate`, or `invalidated`
- `reason`
- `packet_hash`
- `prompt_hash`
- `input_snapshot_hash`
- `gate_snapshot_hash`

Handoff status schema:

- `handoff_id`
- `schema_hash`
- `source_index`

Gate status schema:

- `gate_id`
- `trigger`
- `status`: `blocked`, `not-required`, or `invalidated`
- `approval_hash`
- `source_index`

V1 status never records `running`, `completed`, or `failed`. Those states require
execution evidence and belong to V2.

## Packet JSON

`packets/001-first-slice.packet.json` required fields:

- `packet_id`: `001-first-slice`
- `source_plan_id`
- `source_first_slice`
- `objective`
- `surface_refs`
- `phase_context`
- `worker_refs`
- `allowed_tools`
- `forbidden_actions`
- `risk_gate_refs`
- `handoff_refs`
- `verification`
- `completion_check`
- `input_snapshots`
- `prompt_contract`
- `prompt_path`
- `prompt_hash`

`phase_context` must include phase IDs, `depends_on`, and whether a phase is
included for context only. `worker_refs` can list multiple workers; V1 must not
collapse multi-worker phases into a single `worker_id`.

`input_snapshots` schema:

- `input_label`
- `input_kind`: `literal`, `path`, `glob`, `url`, or `unknown`
- `normalized_value`
- `hash`
- `exists_at_compile_time`

For path and glob inputs, the compiler hashes the normalized path string and, if
the file exists, the file content. Directories are not recursively hashed in V1;
they must be recorded as `input_kind: "path"` with `exists_at_compile_time` and
a note in `resume.md` that directory content drift is not detected.

## Packet Prompt

`packets/001-first-slice.prompt.md` must use these exact headings:

```markdown
# Packet 001-first-slice
## Objective
## Inputs
## Ownership
## Allowed Tools
## Forbidden Actions
## Risk Gates
## Required Output
## Verification
## Handoff Context
## Stop Conditions
```

The prompt must include the packet ID, source plan ID, prompt hash placeholder,
all forbidden actions, all referenced gate IDs, and the completion check. The
compiler must verify prompt/packet agreement structurally by checking these
heading sections and mirrored IDs, not by loose substring search alone.

## Approval State

`gates/approval-state.json` is canonical. Markdown files are human-readable
views only.

Required top-level fields:

- `run_id`
- `plan_hash`
- `risk_policy`: `"block-all"`
- `gates`

Each gate record requires:

- `gate_id`
- `trigger`
- `safe_default`
- `requires_user_approval`
- `status`: `blocked` or `not-required`
- `approved`: `false`
- `approval_source`: `null`

V1 never treats hand-edited Markdown as approval. Even if a user edits
`*.approval.md`, `approval-state.json` remains blocked unless a future V2 command
changes it. This avoids surprising execution behavior.

## Risk Model

The compiler treats these as gated by default:

- write actions outside the run directory
- shell or process execution
- dependency installation
- database migration
- production deploy
- public API change
- external network calls
- external messages
- paid API usage
- secret access
- force push, branch deletion, hard reset, history rewrite
- deletion of files or directories outside `out/v1/<run_id>`

If the first slice, worker permissions, or risk gates mention any of these
categories, packet status is `blocked-risk-gate`. Otherwise packet status is
`ready`.

## Resume Check

`--resume out/v1/<run_id>` recomputes:

- plan hash from `plan.snapshot.json`
- packet JSON hash
- prompt hash
- input snapshot hash
- handoff schema hashes
- approval-state hash

It then updates only `status.json` and `resume.md`.

Resume outcomes:

- `resumable`: all stored hashes match recomputed hashes
- `invalidated`: any hash differs, any required artifact is missing, or the
  current compiler version cannot parse the run

`invalidators` must be a list of structured records:

- `kind`: `plan`, `packet`, `prompt`, `input`, `handoff`, `gate`, or `compiler`
- `id`
- `expected_hash`
- `actual_hash`
- `message`

V1 does not resume completed work. It only tells the operator whether the
compiled first-slice packet is still trustworthy.

## Evaluation

Add fixtures under `fixtures/v1/` when the compiler exists.

Minimum fixture set:

- positive: activated repo-wide migration compiles first-slice packet
- positive: read-only research plan compiles ready first-slice packet
- negative: downgrade artifact is rejected
- negative: output path outside `out/v1/<run_id>` is rejected
- negative: symlink escape from `out/v1/` is rejected
- risk: dependency-install first slice becomes `blocked-risk-gate`
- risk: shell/process execution first slice becomes `blocked-risk-gate`
- drift: prompt/packet mismatch is rejected by self-test
- resume: modified plan hash invalidates run
- resume: modified prompt hash invalidates run
- resume: modified gate approval-state hash invalidates run
- resume: missing handoff schema invalidates run

Each fixture must validate:

- generated file set
- deterministic IDs
- status values
- blocked risk gates
- prompt/packet structural agreement
- resume invalidation reasons

## Self-Test Requirements

`scripts/compile_workflow.py --self-test` must include:

- one valid activated plan compile
- downgrade rejection
- unsafe output path rejection
- symlink escape rejection
- blocked dependency install gate
- blocked shell/process gate
- prompt/packet drift failure
- stale plan hash resume failure
- stale prompt hash resume failure
- stale gate hash resume failure

The self-test must fail for the exact reason under test. It must not count a
failure caused by an unrelated missing required field as a pass.

## Decision Gate

The compiler must write `out/v1/<run_id>/summary.json` for fixture runs with:

- `fixture_count`
- `passed`
- `failed`
- `decision`: `keep` or `kill`
- `failures`

`docs/v1-decision.md` may record `keep` only when all required V1 fixtures pass,
all existing V0/V0.5 release checks still pass, and the generated summary has
`decision: "keep"`.

## Acceptance Criteria

V1 is releasable when:

- `scripts/compile_workflow.py --self-test` passes.
- Existing V0/V0.5 checks still pass.
- Required V1 fixtures pass through the compiler.
- Generated packet prompts structurally agree with packet JSON.
- Risky first slices are blocked in `approval-state.json` and `status.json`.
- Resume checks invalidate stale plan, prompt, input, handoff, gate, or compiler
  state.
- README documents compile and resume-check commands.
- `docs/v1-decision.md` records keep/kill from `summary.json`.

## Implementation Slices

1. Add `scripts/compile_workflow.py --self-test` with plan validation, activated
   plan enforcement, output path safety, and deterministic hashing.
2. Generate `run.json`, `plan.snapshot.json`, `plan.sha256`, `README.md`, and
   `status.json` from one activated V0.5 sample plan.
3. Generate `001-first-slice.packet.json` and `001-first-slice.prompt.md` with
   structural prompt/packet agreement checks.
4. Generate deterministic handoff schemas and `approval-state.json`.
5. Add risk-gate blocking for first-slice forbidden actions, shell/process
   execution, and risky worker permissions.
6. Add `--resume` mode that validates hashes and writes structured
   invalidators.
7. Add V1 fixtures, fixture summary generation, and `docs/v1-decision.md`.
8. Update `SKILL.md` only if the compiler changes the expected output contract.

## Open Questions

- Should V2 add a command that writes approvals into `approval-state.json`, or
  should approvals remain outside the local compiler forever?
- Should V2 compile all phase-worker pairs into packets, or should it require a
  V1.1 schema bump that adds packet IDs directly to `workflow.plan.json`?
- Should V2 introduce a viewer, or is textual `README.md` plus `status.json`
  enough for one more measured step?
