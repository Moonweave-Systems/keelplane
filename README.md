# dynamic-workflow-designer

> Design ultracode-style, situation-aware multi-agent workflows for large tasks before execution starts.

[![License: MIT](https://img.shields.io/badge/License-MIT-4F46E5.svg)](LICENSE)
[![Agent skill](https://img.shields.io/badge/agent%20skill-Codex-4F46E5.svg)](SKILL.md)

`dynamic-workflow-designer` is a Codex skill for designing large workflows:
phases, workers, parallelism, handoffs, verification gates, risk gates, budgets,
and resume strategy.

It is deliberately not the same as `workflow-router`. The router chooses the
smallest suitable workflow. This skill designs a larger workflow when the task
itself needs dynamic orchestration.

## Why

Claude Code Dynamic Workflows changed the useful abstraction: for large work,
the plan can live outside the chat as an inspectable workflow. Codex does not
currently have the same native workflow runtime in this environment, so this
repo starts with the part we can make checkable now: a workflow design contract.

The first slice defines the skill contract and deterministic V0.5 sample
evidence for workflow blueprints and specs. The next slice is a first-slice
compiler, not a plugin runtime; plugin or runtime work can follow once compile
and resume contracts prove useful.

## Use

Example prompts:

```text
Use $dynamic-workflow-designer to design a workflow for auditing every route for missing authorization.
```

```text
Use $dynamic-workflow-designer to plan a 500-file migration with verification gates and rollback boundaries.
```

## Repository layout

```text
.
├── SKILL.md                         # Runtime skill instructions
├── scripts/check_contract.py         # Release contract smoke check
├── scripts/evaluate_plan.py          # V0.5 schema and benchmark evaluator
├── scripts/compile_workflow.py        # V1 first-slice packet compiler
├── scripts/execute_packet.py          # V2 first-slice execution adapter
├── scripts/run_workflow.py             # V3 runtime entry loop
├── scripts/orchestrate_workflow.py      # V4 scheduler
├── scripts/dispatch_worker.py           # V4.5 dispatch preparation
├── scripts/run_worker_result.py         # V5 fixture worker-result adapter
├── scripts/review_worker_result.py      # V5.5 worker-result review
├── scripts/ingest_worker_review.py      # V6 runtime ingestion
├── references/workflow-patterns.md  # Pattern guide for workflow designs
├── references/workflow-plan-schema.md
│                                      # workflow.plan.json contract
├── fixtures/v0.5/manifest.json       # Benchmark fixture manifest
├── samples/v0.5/                     # Deterministic candidate/baseline samples
├── docs/fixture-smoke/v0-smoke.md    # Auditable fixture smoke results
├── docs/v0.5-plan-schema-evaluator-spec.md
│                                      # V0.5 evaluator spec
├── docs/v0.5-decision.md             # Keep/kill decision
├── docs/v1-first-slice-compiler-spec.md
│                                      # First-slice compiler spec
├── docs/v1-decision.md                # V1 keep/kill decision
├── docs/automation-roadmap.md         # Large-task automation roadmap
├── docs/v2-execution-adapter-spec.md  # V2 execution-adapter spec
├── docs/v2-decision.md                # V2 keep/kill decision
├── docs/v2.5-review-repair-spec.md    # V2.5 review/repair spec
├── docs/v2.5-decision.md              # V2.5 keep/kill decision
├── docs/v3-runtime-entry-spec.md      # V3 runtime-entry spec
├── docs/v3-decision.md                # V3 keep/kill decision
├── docs/v6-runtime-ingestion-spec.md  # V6 runtime-ingestion spec
├── docs/v6-decision.md                # V6 keep/kill decision
├── docs/github-research.md          # Prior-art survey and import decisions
├── docs/spec.md                     # Product spec and release criteria
├── agents/openai.yaml               # UI metadata
├── LICENSE
└── README.md
```

## Prior Art

The initial survey looked at:

- `lxcong/awesome-claude-dynamic-workflows`
- `peymanvahidi/awesome-claude-dynamic-workflows`
- `Timmy6942025/opencode-dynamic-workflows`
- `scasella/claude-dynamic-workflows-codex`
- `andrueandersoncs/open-workflows`
- local `claude-skills/engineering/agent-workflow-designer`
- local `claude-skills/orchestration/ORCHESTRATION.md`

See [`docs/github-research.md`](docs/github-research.md) for what to reuse and
what not to vendor.

## Releasing

Run from the repository root:

```bash
python scripts/quick_validate_skill.py .
python scripts/quick_validate_skill.py --self-test
python scripts/check_contract.py
python scripts/check_contract.py --self-test
python scripts/evaluate_plan.py --self-test
python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5
python scripts/compile_workflow.py --self-test
python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final
python scripts/execute_packet.py --self-test
python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final
python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final
python scripts/run_workflow.py --self-test
python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final
python scripts/orchestrate_workflow.py --self-test
python scripts/dispatch_worker.py --self-test
python scripts/run_worker_result.py --self-test
python scripts/review_worker_result.py --self-test
python scripts/ingest_worker_review.py --self-test
python scripts/check_whitespace.py .
python scripts/check_release_text.py .
python scripts/check_release_text.py --self-test
```

For V2 release-candidate verification, also run two manual smokes after the V2
manifest command: perform a V2 dry run on
`out/v1/v2-final-dry-run-ready-readonly` and require
`repo_tracked_diff_unchanged: true`, then run the blocked smoke against
`out/v1/v2-final-dry-run-blocked-risk` and prove V2 refuses execution with
`ERR_EXEC_BLOCKED_RISK`. Refresh
[`docs/v2-decision.md`](docs/v2-decision.md) from the generated
`out/v2/final/summary.json` values after the V2 manifest command.

The contract check requires passing fixture records under
[`docs/fixture-smoke/`](docs/fixture-smoke/).

The V0.5 manifest uses tracked baseline source snapshots under
[`samples/v0.5/baseline-sources/`](samples/v0.5/baseline-sources/) so the
manifest gate is reproducible from this repository.

The V0.5 evaluator regenerates repo-local `out/v0.5/` from tracked fixtures and
samples. That directory is verification evidence, not source of truth. Raw
records are bound to the current `SKILL.md` hash, baseline observations require
source-backed excerpts, and consumer reports require blinded sample-review
provenance with field-level support. The manifest run exits nonzero if the
keep/kill decision is not `keep` or if `docs/v0.5-decision.md` does not match the
freshly regenerated summary.

The V0.5 keep/kill decision is
[`docs/v0.5-decision.md`](docs/v0.5-decision.md).

V1 is the first-slice compiler described in
[`docs/v1-first-slice-compiler-spec.md`](docs/v1-first-slice-compiler-spec.md).
V1 compiles an activated `workflow.plan.json` into one inspectable
first-slice packet, prompt, gate state, and resume/status files without claiming
a full automatic workflow runtime.

The V1 first-slice compiler release gate adds:

```bash
python scripts/compile_workflow.py --plan workflow.plan.json --out out/v1/<run_id>
python scripts/compile_workflow.py --resume out/v1/<run_id>
python scripts/compile_workflow.py --self-test
python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final
```

V1 expects `workflow.plan.json` to live under this repository root; resume treats
absolute or parent-traversal source-plan paths as stale.

The V1 keep/kill decision is
[`docs/v1-decision.md`](docs/v1-decision.md).

The large-task automation roadmap is
[`docs/automation-roadmap.md`](docs/automation-roadmap.md). The current
implementation target is the V2 first-slice execution adapter described in
[`docs/v2-execution-adapter-spec.md`](docs/v2-execution-adapter-spec.md).
V2 Slice 1 adds `scripts/execute_packet.py` dry-run evidence generation and V1
trust precondition checks. V2 Slice 2 adds manifest-scoped `local-shell`
execution fixtures, deterministic worktree creation, stdout/stderr capture, and
dirty-worktree blocking. V2 Slice 3 adds manifest-scoped verification commands
that can promote a successful attempt to `verified` or fail it with
`ERR_EXEC_VERIFY_FAILED`. V2 Slice 4 adds the Codex CLI backend with worktree
isolation, transcript capture, backend auth detection, configurable timeout,
fixture-command mode, and optional installed-Codex live smoke command support.
Public `--manifest` is limited to `fixtures/v2/manifest.json`; command-bearing
fixtures are release-test inputs, not a general command runner.
The V2 release candidate adds stale source-plan
invalidation, malformed attempt invalidation, required-fixture failure policy,
and the `fixtures/v2/manifest.json` keep gate recorded in
[`docs/v2-decision.md`](docs/v2-decision.md). V2 still does not execute OMX,
merge worktrees, or advance multi-slice workflows.

V2.5 execute-review-repair is the next completed control-plane loop:
[`docs/v2.5-review-repair-spec.md`](docs/v2.5-review-repair-spec.md) defines
the review, repair, evidence, and status model, while
[`docs/v2.5-to-v3.workflow.plan.json`](docs/v2.5-to-v3.workflow.plan.json)
is the machine-readable workflow plan that hands trusted V2.5 terminal states
to the future V3 multi-slice runtime. `scripts/execute_packet.py` now supports
`--review`, `--review-resume`, and `--repair` for one trusted V2 packet
attempt, and the keep gate is:

```bash
python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final
```

The V2.5 keep/kill decision is
[`docs/v2.5-decision.md`](docs/v2.5-decision.md). V2.5 still does not advance
later packets or run backend repair execution; it prepares bounded repair
prompts and records review/repair contract ledgers.

V3 runtime entry is the current multi-slice bridge:
[`docs/v3-runtime-entry-spec.md`](docs/v3-runtime-entry-spec.md) defines how
trusted V2.5 terminal states become a deterministic runtime journal and next
packet candidate. `scripts/run_workflow.py` supports `--start`, `--resume`,
`--self-test`, and the keep gate:

```bash
python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final
```

The V3 keep/kill decision is
[`docs/v3-decision.md`](docs/v3-decision.md). V3 still does not execute later
packets, orchestrate parallel workers, merge worktrees, or claim fully
autonomous large-task completion.

V4 through V6 extend the runtime bridge without opening unrestricted execution:
V4 schedules ready phase packets, V4.5 prepares dispatch bundles, V5 records
fixture-only worker result evidence, V5.5 reviews that result, and V6 ingests
approved reviewed results into the next frontier. The current dogfood chain
ends with `out/v6/v32-semantic-dogfood/status.json` reporting
`status: frontier-ready` and selecting `release_decision`.

The V6 runtime-ingestion spec and decision are
[`docs/v6-runtime-ingestion-spec.md`](docs/v6-runtime-ingestion-spec.md) and
[`docs/v6-decision.md`](docs/v6-decision.md). V6 still does not execute the
next packet, run arbitrary worker backends, merge worktrees, or claim fully
autonomous large-task completion.

## License

[MIT](LICENSE)
