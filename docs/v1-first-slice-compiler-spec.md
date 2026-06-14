# V1 First-Slice Compiler Spec

Status: draft
Date: 2026-06-14

## Purpose

V0.5 proved that `dynamic-workflow-designer` can emit deterministic,
schema-valid workflow plans and evaluate them against a tracked fixture corpus.
V1 should close the next practical gap without pretending to be a full workflow
runtime: compile an activated `workflow.plan.json` into one inspectable
first-slice packet plus the files needed to audit, manually hand off, block, or
revalidate that first-slice packet deterministically.

V1 is a packet compiler, not a runner. It does not execute shell commands,
spawn subagents, advance between phases, or mark work complete. Those behaviors
belong to V2 after the file contract is proven.

## Product Position

| Layer | Responsibility | V1 stance |
| --- | --- | --- |
| `workflow-router` | choose the smallest suitable workflow | unchanged |
| `dynamic-workflow-designer` | design phases, workers, gates, handoffs | source of `workflow.plan.json` |
| V1 first-slice compiler | materialize the first inspectable packet and safety files | implement now |
| Future runtime | durable orchestration, packet advancement, monitoring, subagent scheduling | defer |

V1 should make a workflow easier to start after context loss. It should not
claim Claude Dynamic Workflow-style orchestration. The measurable value is that
another Codex agent can open a run directory, read `README.md`, inspect the
first-slice prompt and packet JSON, see blocked gates, and tell whether manual
handoff is blocked by V1 checks.

## Goals

- Accept only activated V0.5 `workflow.plan.json` artifacts.
- Compile the plan's `execution_path.first_slice` into one packet JSON and one
  prompt Markdown file.
- Preserve enough plan graph context to explain where the first slice sits,
  without compiling the whole workflow into runnable packets.
- Emit deterministic gate, handoff, and packet identifiers.
- Store canonical hashes for plan, packet, prompt, first-slice inputs, handoff
  schemas, and approval state.
- Block risky first slices by default with machine-readable approval state.
- Emit structured error codes for every rejected compile, resume-check, and
  self-test case.
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
- Exactly one inspectable packet is generated: `001-first-slice`.
- Later phases, workers, barriers, and handoffs are copied as context and schema
  references, not as runnable packet state.
- `ready` means "not blocked by V1 checks and available for manual review." It
  does not mean the compiler will run or dispatch it, and it is not proof that
  execution is safe.

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
python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/<suite_id>
python scripts/compile_workflow.py --self-test
```

Mode semantics:

- `--mode compile`: validate the plan, clear or create a fresh run directory,
  write all V1 artifacts, and exit without executing anything.
- `--resume`: read an existing run directory, recompute hashes, update only
  `status.json` and `resume.md`, and exit without executing anything.
- `--manifest`: run a tracked V1 fixture manifest, compile or resume-check each
  fixture in deterministic fixture subdirectories, write
  `out/v1/<suite_id>/summary.json`, and fail if any required fixture is missing,
  skipped, or failed.
- `--self-test`: run positive and negative in-memory cases plus tracked V1
  fixtures once they exist.

There is no `first-slice` execution mode in V1. The first slice is compiled, not
run.

The `--plan` path must resolve under the repository root. V1 stores
`run.json.source_plan_path` as a repository-relative path and rejects tampered
absolute or parent-traversal source-plan paths during resume.
The ownership sentinel also records the compile-time `source_plan_path`,
`source_plan_hash`, `plan_hash`, status sections, and snapshot hashes so
`status.json` never becomes the resume trust anchor.

## Output Path Safety

By default, `--out` must resolve under the repository-local `out/v1/` directory.
The compiler must use resolved real paths for containment checks. The same
containment and ownership rules apply to `--resume` before it writes
`status.json` or `resume.md`.

The compiler must reject:

- `.`
- repository root
- `out/`
- `out/v1/`
- paths outside repository-local `out/v1/`
- any symlink in the run-directory path, even if it points inside `out/v1/`
- existing non-directory paths
- existing directories that do not contain `.compile_workflow-owned.json`
- existing directories whose ownership sentinel has a different `run_id` or
  `tool`
- symlinked leaf files for any file the compiler will overwrite, including
  `status.json` and `resume.md`

The compiler may create a new selected `out/v1/<run_id>` directory. It may
clear and recreate an existing selected run directory only when that directory
contains `.compile_workflow-owned.json` with:

- `tool`: `"compile_workflow.py"`
- `schema_version`: `"1.0"`
- `run_id`: matching the requested run ID

It must not delete any path outside that resolved, compiler-owned run directory.
It must write files with no-follow semantics where available, or by writing a
new regular file in the owned directory and atomically replacing only a
non-symlink regular file.

For `--manifest`, the selected owned directory is `out/v1/<suite_id>`. The suite
root sentinel uses `run_id: "<suite_id>"` and `mode: "manifest"`. Each fixture
subdirectory must also contain a sentinel with run ID
`<suite_id>/<fixture_id>` and `mode: "fixture"`. A rerun may clear the suite root
only when the root sentinel matches; individual fixture compiles may clear only
their own matching fixture subdirectory.

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
├── .compile_workflow-owned.json
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
does not execute the workflow. If any packet is `blocked-risk-gate`, the README
must say that V1 has no machine approval path; the operator must return to the
user or wait for V2 tooling before treating the packet as actionable.

`.compile_workflow-owned.json` is the deletion sentinel. It must be written as
canonical JSON with these fields:

- `tool`: `"compile_workflow.py"`
- `schema_version`: `"1.0"`
- `run_id`
- `mode`: `"compile"`, `"manifest"`, or `"fixture"`
- `created_at`

## Canonical Hashing

All compiler hashes use SHA-256 over UTF-8 bytes.

Canonical JSON means JSON serialized with sorted object keys, no insignificant
whitespace, LF line endings, and deterministic ordering for arrays whose schema
defines a sort key. Arrays without an explicit sort key keep source order.

Hash preimages:

- `plan_hash`: canonical JSON of `plan.snapshot.json`.
- `prompt_hash`: exact UTF-8 bytes of the generated prompt Markdown after CRLF
  normalization to LF. The prompt must contain the literal placeholder
  `{{PROMPT_SHA256}}`; the compiler does not substitute the prompt hash into the
  prompt body.
- `packet_hash`: canonical packet JSON. Packet JSON includes `prompt_hash` and
  does not include `packet_hash`, so there is no cycle.
- `input_snapshot_hash`: canonical JSON of `input_snapshots`, sorted by
  `input_id`.
- `input_snapshots[].hash`: canonical JSON of one input snapshot record with the
  `hash` field omitted. For `path` and `glob`, this includes
  `snapshot_entries`; for `literal` and `url`, this includes the single
  normalized-value entry.
- `canonical_input_record`: canonical JSON of `{ "source_index",
  "input_label", "input_kind", "normalized_value", "exists_at_compile_time",
  "snapshot_entries" }`. It excludes `input_id` and `hash` to avoid
  self-reference.
- `handoff_schema_hash`: canonical JSON of the handoff schema file.
- `approval_state_hash`: canonical JSON of `gates/approval-state.json`.
- `gate_approval_hash`: canonical JSON of one gate record inside
  `approval-state.json`.
- `gate_snapshot_hash`: canonical JSON of the ordered packet `risk_gate_refs`
  gate IDs plus each referenced `gate_approval_hash`.

## Deterministic IDs

All IDs are derived from canonical JSON plus source position. Indexes are
zero-based integers formatted as four decimal digits: `0000`, `0001`, and so on.

- packet ID: always `001-first-slice`
- handoff ID: `handoff-<zero-padded-index>-<sha8(canonical_handoff_json)>`
- gate ID: `gate-<zero-padded-index>-<sha8(canonical_gate_json)>`
- synthetic gate ID:
  `gate-synthetic-<risk-category>-<sha8(canonical_detection_record)>`

For source handoffs and gates, the source index is the item order in
`workflow.plan.json`; the hash is computed from the canonical JSON object after
sorting object keys. Reordering handoffs or gates is therefore a semantic change
for V1 resume purposes and invalidates related snapshots.

Synthetic gates are generated only for detected risk categories that do not have
a matching source gate. Their detection record must include `risk_category`,
`source_field`, `source_id`, and `normalized_token`.

Gate ordering is source gates first in original source order, followed by
synthetic gates sorted by `risk_category`, then `source_field`, then `source_id`,
then `normalized_token`. `risk_gate_refs`, `gate_statuses`, Markdown approval
files, and `approval-state.json.gates` must all use that order.

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
- `source_plan_hash`
- `plan_hash`
- `compiler_version`
- `mode`: `"compile"`
- `risk_policy`: `"block-all"`
- `status_path`
- `packet_paths`
- `approval_state_path`

`source_plan_hash` is the canonical hash of the original file at
`source_plan_path` at compile time. `plan_hash` is the canonical hash of
`plan.snapshot.json`.

`source_plan_path` must be repository-relative in V1.

`risk_policy` is fixed to `block-all` in V1. Approved execution is outside V1;
approval files exist only to make manual gates explicit and machine-checkable.
`run.json` is immutable after compile. `--resume` must not edit `run.json`; it
records its result only in `status.json` and `resume.md`.

## `status.json`

Required fields:

- `run_id`
- `plan_hash`
- `source_plan_hash`
- `resume_state`: `fresh`, `resumable`, or `invalidated`
- `packet_statuses`
- `handoff_statuses`
- `gate_statuses`
- `snapshots`
- `invalidators`
- `last_resume_checked_at`: timestamp or `null`
- `last_resume_result`: `null`, `resumable`, or `invalidated`

`snapshots` schema:

- `plan_hash`
- `packet_hashes`: object keyed by packet ID
- `prompt_hashes`: object keyed by prompt path
- `input_snapshot_hashes`: object keyed by packet ID
- `handoff_schema_hashes`: object keyed by handoff ID
- `approval_state_hash`
- `gate_approval_hashes`: object keyed by gate ID
- `compiler_version`

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
- `source`: `plan` or `compiler-synthetic`
- `source_index`: integer or `null`
- `risk_category`

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
- `input_snapshot_hash`
- `prompt_contract`
- `prompt_path`
- `prompt_hash`

`phase_context` must include phase IDs, `depends_on`, and whether a phase is
included for context only. `worker_refs` can list multiple workers; V1 must not
collapse multi-worker phases into a single `worker_id`.

First-slice derivation is deliberately conservative:

- `source_first_slice` is exactly `execution_path.first_slice` from the source
  plan.
- V1 does not infer that one phase or worker owns the first slice.
- `phase_context` includes every source phase in original order with
  `context_only: true`.
- `worker_refs` includes every source worker in original order with
  `context_only: true`.
- `handoff_refs` includes every generated handoff ID in source order with
  `context_only: true`.
- `risk_gate_refs` includes every generated gate ID in the deterministic gate
  ordering defined above; status decides whether each gate is required for this
  packet.
- `objective` is copied from top-level `objective`.
- `surface_refs` includes every source surface in original order as
  `{ "surface_id", "kind", "locator", "access_mode" }`.
- `allowed_tools` is the union of every source worker's `tool_permissions`:
  boolean permissions are `true` if any worker has `true`; `mcp_connectors` and
  `requires_escalation_for` are unique sorted lists.
- `forbidden_actions` is the unique ordered union of
  `execution_path.first_slice.forbidden_actions` followed by every worker's
  `forbidden_actions`.
- `verification` is copied from top-level `verification` in source order.
- `completion_check` is copied from
  `execution_path.first_slice.completion_check`.
- `prompt_contract` contains `{ "inputs", "required_output_schema",
  "stop_conditions" }` where `inputs` is copied from
  `execution_path.first_slice.inputs`, `required_output_schema` is
  `execution_path.first_slice.expected_output`, and `stop_conditions` is the
  unique ordered union of the first slice forbidden actions plus blocked gate
  triggers.

This avoids fabricating executable assignment semantics that do not exist in the
V0.5 plan schema.

`input_snapshots` schema:

- `input_id`: `input-<zero-padded-source-index>-<sha8(canonical_input_record)>`
- `source_index`
- `input_label`
- `input_kind`: `literal`, `path`, `glob`, `url`, or `unknown`
- `normalized_value`
- `hash`
- `exists_at_compile_time`
- `snapshot_entries`

V0.5 first-slice inputs are arbitrary labels, so V1 treats all inputs as
`literal` unless they match one of these deterministic recognizers:

- `workflow.plan.json`: the source plan path.
- `blueprint.md`: a sibling blueprint path if one exists; otherwise literal.
- `original prompt`: the source prompt text when available; otherwise literal.
- `repository path`: the repository root path.
- strings beginning with `path:`: path input after trimming the prefix.
- strings beginning with `glob:`: glob input after trimming the prefix.

For `literal` and `url` inputs, `snapshot_entries` contains one record with the
normalized value and its hash. For `path` inputs, `snapshot_entries` contains one
record `{ "path", "exists", "sha256" }`; `sha256` is `null` when the path is
missing or is a directory. Directories are not recursively hashed in V1 and must
be called out in `resume.md`. For `glob` inputs, the compiler expands matching
files, sorts them by POSIX-style relative path, and hashes canonical JSON of
records `{ "path", "exists", "sha256" }`. Bare directories inside a glob result
are recorded with `sha256: null`.

Duplicate `input_label` values are allowed because V0.5 treats inputs as
arbitrary labels. Resume invalidators must target `input_id`, not label text.

## Context Artifacts

`context/phases.json` is canonical JSON with:

- `schema_version`: `"1.0"`
- `source_plan_id`
- `phases`: every source phase in original order, each with `phase_id`,
  `depends_on`, `worker_ids`, `handoffs_in`, `handoffs_out`, and
  `context_only: true`

`handoffs_in` and `handoffs_out` are lists of generated handoff IDs calculated
from source handoffs whose `to_phase` or `from_phase` matches the phase ID.

`context/workers.json` is canonical JSON with:

- `schema_version`: `"1.0"`
- `source_plan_id`
- `workers`: every source worker in original order with `worker_id`, `role`,
  `ownership`, `tool_permissions`, `forbidden_actions`, `context_budget`, and
  `prompt_contract`

`context/parallelism.json` is canonical JSON with:

- `schema_version`: `"1.0"`
- `source_plan_id`
- `parallelism`: the top-level `parallelism` object copied from the source plan

`handoffs/<handoff-id>.schema.json` is canonical JSON with:

- `schema_version`: `"1.0"`
- `handoff_id`
- `source_index`
- `from_phase`
- `to_phase`
- `artifact`
- `artifact_schema`

The handoff ID hash uses the full source handoff record. The
`handoff_schema_hash` uses the generated handoff schema file above.

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

The prompt must also include one fenced JSON block under `## Handoff Context`
with info string `packet_contract_digest`. The compiler parses this block and
compares it against packet JSON before writing final artifacts.

Required digest fields:

- `packet_id`
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
- `input_snapshot_hash`
- `prompt_contract`

The digest values must equal the corresponding packet JSON values after
canonical JSON normalization. The digest deliberately excludes `prompt_path` and
`prompt_hash` because those are file metadata, not operator instructions.
Mismatch is a compile failure with `ERR_PROMPT_PACKET_DRIFT`.

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
- `risk_category`
- `source`: `plan` or `compiler-synthetic`
- `safe_default`
- `requires_user_approval`
- `status`: `blocked` or `not-required`
- `approved`: `false`
- `approval_source`: `null`

V1 never treats hand-edited Markdown as approval. Even if a user edits
`*.approval.md`, `approval-state.json` remains blocked unless a future V2 command
changes it. This avoids surprising execution behavior.

## Risk Model

The compiler uses a closed risk category vocabulary:

- `write`
- `shell-process`
- `network`
- `dependency-install`
- `database-migration`
- `production-deploy`
- `public-api-change`
- `external-message`
- `paid-api`
- `secret-access`
- `history-rewrite`
- `delete`

Risk detection uses only structured source fields and exact normalized token
sequences. Normalization lowercases text and treats spaces, underscores, and
hyphens as the same separator. It must not use broad prose substring search:
`networking` does not match `network`, and `shellfish` does not match `shell`.

Structured risk sources:

- `surfaces[].access_mode` other than `read-only` maps to `write`.
- `workers[].tool_permissions.write: true` maps to `write`.
- `workers[].tool_permissions.shell: true` maps to `shell-process`.
- `workers[].tool_permissions.network: true` maps to `network`.
- non-empty `workers[].tool_permissions.mcp_connectors` maps to
  `external-message`.
- `workers[].tool_permissions.requires_escalation_for[]` tokens are copied into
  `allowed_tools` and may help match source gates, but they do not by themselves
  make a first-slice packet blocked unless another structured risk source is
  present.
- `risk_gates[].trigger` token sequences map to the risk vocabulary and aliases.
- `execution_path.first_slice.instruction`,
  `execution_path.first_slice.expected_output`, and
  `execution_path.first_slice.completion_check` are scanned only for exact
  normalized risk tokens from the vocabulary.
- `execution_path.first_slice.forbidden_actions[]` tokens map to the risk
  vocabulary and aliases.

A source gate matches a detected category only when its normalized `trigger`
contains the exact normalized category token sequence or one of that category's
compatibility alias token sequences. Otherwise the detected category requires a
synthetic gate.

Compatibility aliases for existing V0.5 plans:

| Category | Accepted aliases |
| --- | --- |
| `write` | `write-action`, `source-edits` |
| `shell-process` | `shell`, `shell-action`, `process-execution` |
| `network` | `network-action`, `external-network-calls` |
| `dependency-install` | `dependency-install`, `dependency-installs`, `dependency-change`, `dependency-changes` |
| `database-migration` | `database-migration`, `database-migrations` |
| `production-deploy` | `production-deploy`, `production-deploys` |
| `public-api-change` | `public-api-change`, `public-api-changes` |
| `external-message` | `external-message-action`, `external-messages` |
| `paid-api` | `paid-api`, `paid-external-api-use` |
| `secret-access` | `secret`, `secret-access` |
| `history-rewrite` | `history-rewrite`, `force-push`, `hard-reset` |
| `delete` | `delete`, `deletion` |

If any structured source maps to a risk category, packet status is
`blocked-risk-gate` and at least one gate status must be `blocked`. If the plan
does not contain a matching source gate for a detected category, the compiler
must emit a synthetic blocked gate for that category. Otherwise packet status is
`ready` and all gate statuses are `not-required`.

V1 has no approval command. A blocked packet remains blocked even if a human
edits Markdown approval notes.

## Resume Check

`--resume out/v1/<run_id>` recomputes:

- source plan hash from `source_plan_path`
- plan snapshot hash from `plan.snapshot.json`
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

If `source_plan_path` no longer exists, is not a regular file, or hashes
differently from `run.json.source_plan_hash`, resume must emit
`ERR_RESUME_STALE_PLAN`. If `plan.snapshot.json` differs from
`status.json.snapshots.plan_hash`, resume must also emit
`ERR_RESUME_STALE_PLAN` with `id: "plan.snapshot.json"`.

`invalidators` must be a list of structured records:

- `kind`: `plan`, `packet`, `prompt`, `input`, `handoff`, `gate`, or `compiler`
- `id`
- `code`
- `expected_hash`
- `actual_hash`
- `message`

V1 does not resume completed work. It only tells the operator whether the
compiled first-slice packet is still trustworthy.

Required resume invalidator codes:

- `ERR_RESUME_STALE_PLAN`
- `ERR_RESUME_STALE_PACKET`
- `ERR_RESUME_STALE_PROMPT`
- `ERR_RESUME_STALE_INPUT`
- `ERR_RESUME_STALE_HANDOFF`
- `ERR_RESUME_STALE_GATE`
- `ERR_RESUME_STALE_COMPILER`
- `ERR_RESUME_MISSING_ARTIFACT`

## Compile Errors

Compile and fixture failures must be structured as `CompileError` records:

- `code`
- `message`
- `path`: optional source or output path
- `fixture_id`: optional fixture ID

Required error codes:

- `ERR_PLAN_DOWNGRADE`: input is a downgrade artifact, not an activated plan.
- `ERR_PLAN_INVALID`: V0.5 plan validation failed.
- `ERR_OUT_PATH_UNSAFE`: output or resume path is outside the allowed V1 area or
  is a forbidden root.
- `ERR_OUT_PATH_SYMLINK`: any path component in the run-directory path is a
  symlink.
- `ERR_OUT_PATH_NOT_OWNED`: existing run directory lacks a matching ownership
  sentinel.
- `ERR_PROMPT_PACKET_DRIFT`: prompt digest and packet JSON disagree.
- `ERR_RISK_GATE_BLOCKED`: fixture expected a ready packet but the compiler
  correctly blocked a risk gate, or a fixture expected a blocked gate that was
  not blocked.
- `ERR_RESUME_STALE_PLAN`
- `ERR_RESUME_STALE_PACKET`
- `ERR_RESUME_STALE_PROMPT`
- `ERR_RESUME_STALE_INPUT`
- `ERR_RESUME_STALE_HANDOFF`
- `ERR_RESUME_STALE_GATE`
- `ERR_RESUME_STALE_COMPILER`
- `ERR_RESUME_MISSING_ARTIFACT`
- `ERR_SELF_TEST_WRONG_REASON`: a negative self-test failed, but not for the
  expected code.

## Evaluation

Add fixtures under `fixtures/v1/` when the compiler exists.

Minimum fixture set:

- positive: activated repo-wide migration compiles first-slice packet
- positive: read-only research plan compiles ready first-slice packet
- negative: downgrade artifact is rejected
- negative: output path outside `out/v1/<run_id>` is rejected
- negative: symlink escape from `out/v1/` is rejected
- risk: one fixture for each closed risk category becomes `blocked-risk-gate`
- risk: detected risk without a matching source gate emits a synthetic blocked
  gate
- risk: compatibility aliases match current V0.5 gate triggers without creating
  duplicate synthetic gates
- risk: near-miss tokens and unrelated prose do not create false positive gates
- risk: multiple synthetic gates sort by `risk_category`, `source_field`,
  `source_id`, then `normalized_token`
- drift: prompt/packet mismatch is rejected by self-test
- input: duplicate labels produce stable, distinct `input_id` values
- resume: untouched run remains `resumable` with empty `invalidators`
- resume: modified plan hash invalidates run
- resume: modified packet hash invalidates run
- resume: coherent packet, prompt, and `status.json` snapshot forgery still
  invalidates against compile-time anchors
- resume: packet `prompt_hash` or `prompt_path` metadata drift invalidates run
- resume: modified prompt hash invalidates run
- resume: modified input snapshot invalidates run
- resume: modified gate approval-state hash invalidates run
- resume: coordinated gate and `status.json` snapshot/status forgery still
  invalidates against compile-time anchors
- resume: forged `status.json` metadata or snapshot fields invalidate run
- resume: forged previous-invalidated status sections invalidate run, including
  full invalidated and impossible hybrid clean/invalidated status section shapes
- resume: missing, malformed, or invalid UTF-8 sentinel status-section anchors
  produce structured `ERR_RESUME_MISSING_ARTIFACT`
- resume: repo-relative `source_plan_path` retargeting invalidates run
- resume: a previously invalidated `status.json` remains invalidated even after
  artifact repair; rerun compile to restore trusted clean status sections
- resume: missing handoff schema invalidates run

Each fixture must validate:

- generated file set
- deterministic IDs
- exact canonical content or hash for packet JSON, handoff schema files, context
  artifacts, approval state, and status snapshots
- status values
- blocked risk gates
- prompt/packet structural agreement
- resume invalidation reasons
- exact `CompileError.code` or invalidator `code`

`fixtures/v1/manifest.json` must list required fixture IDs explicitly. Fixture
IDs must be unique. A skipped fixture is a failure. The manifest run writes
`out/v1/<suite_id>/summary.json`.

## Self-Test Requirements

`scripts/compile_workflow.py --self-test` must include:

- one valid activated plan compile
- downgrade rejection
- unsafe output path rejection
- symlink escape rejection
- one blocked gate case for each closed risk category
- synthetic gate generation when no source gate matches
- multiple synthetic gate ordering
- compatibility alias matching for current V0.5 trigger wording
- near-miss risk-token false-positive rejection
- duplicate input labels produce stable, distinct `input_id` values
- prompt/packet drift failure
- clean resume returns `resumable`
- stale plan hash resume failure
- stale packet hash resume failure
- packet prompt-metadata drift resume failure
- coherent packet/prompt/status forgery resume failure
- stale prompt hash resume failure
- stale input hash resume failure
- stale gate hash resume failure
- coordinated gate/status forgery resume failure
- status metadata or snapshot drift resume failure
- forged previous-invalidated status sections do not bypass resume invalidation
- repo-relative source-plan retargeting resume failure
- repaired artifact does not trust a previously invalidated `status.json`
- missing handoff schema resume failure

The self-test must fail for the exact reason under test. It must not count a
failure caused by an unrelated missing required field as a pass.

## Decision Gate

The compiler must write `out/v1/<suite_id>/summary.json` for manifest runs with:

- `suite_id`
- `fixture_count`
- `required_fixture_count`
- `required_passed`
- `passed`
- `failed`
- `skipped`
- `decision`: `keep` or `kill`
- `failures`

`docs/v1-decision.md` may record `keep` only when all required V1 fixtures pass,
all existing V0/V0.5 release checks still pass, and the generated summary has
`decision: "keep"`. The decision doc must name the exact manifest command used
to regenerate the summary and mirror the generated required-fixture totals.

## Acceptance Criteria

V1 is releasable when:

- `scripts/compile_workflow.py --self-test` passes.
- `python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out
  out/v1/final` passes and writes `summary.json`.
- Existing V0/V0.5 checks still pass.
- Required V1 fixtures pass through the compiler.
- Generated packet prompts structurally agree with packet JSON.
- Risky first slices are blocked in `approval-state.json` and `status.json`.
- Resume checks invalidate stale plan, prompt, input, handoff, gate, or compiler
  state.
- Resume checks compare live artifacts against compile-time anchors from the
  ownership sentinel, not mutable `status.json` snapshots.
- A previous invalidated `status.json` is not proof of compiler-authored
  invalidation. A repaired run with invalidated status sections remains
  `invalidated`; rerun compile to restore trusted clean status sections.
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
