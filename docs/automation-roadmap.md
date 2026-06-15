# Large-Task Automation Roadmap

Status: draft; V3 entry runtime implemented
Date: 2026-06-15

## Purpose

The final product goal is large-task automation: a system that can take a broad
objective, decompose it into inspectable work, execute bounded slices, verify
results, resume after interruption, and stop at human gates for risky actions.

This repo should not become a loose prompt pack or an unchecked agent launcher.
Its differentiator is a compiler-first control plane: plans and execution
packets are explicit, hashed, reviewable, resumable, and falsifiable.

## Product Position

`dynamic-workflow-designer` should become the control plane for large Codex
workflows.

| Layer | Responsibility | Repo stance |
| --- | --- | --- |
| Skill | design large workflows with phases, workers, gates, and handoffs | implemented |
| Plan evaluator | prove the workflow plan contract on fixtures | implemented in V0.5 |
| First-slice compiler | materialize one safe packet and resume contract | implemented in V1 |
| Execution adapter | run one compiled packet through a controlled backend | V2 release candidate |
| Runtime loop | advance packet by packet with verification and resume | V3 entry implemented |
| Parallel orchestration | schedule ready phase packets under a concurrency cap | first scheduler slice implemented |
| Worker dispatch | prepare reviewed dispatch bundles for scheduled packets | first dispatch slice implemented |
| Worker result adapter | execute fixture-only worker result bundles under owned output | first controlled slice implemented |
| Worker result review | approve or reject worker results before runtime advancement | first review slice implemented |
| Runtime ingestion | consume reviewed worker results and emit the next frontier | first ingestion slice implemented |
| Product surface | plugin, CLI, dashboard, and release packaging | last |

Prior art such as `oh-my-codex` already covers a broad Codex runtime layer:
launch UX, worktree/tmux operation, durable state, and team execution. This repo
should not copy that whole surface first. The useful position is above or beside
those runtimes: compile a safe packet, gate it, then hand it to Codex CLI, OMX,
or another backend through a narrow adapter.

## Roadmap

### V0: Skill Contract

Status: done.

Purpose: define the human-facing workflow design skill.

Done means:

- `SKILL.md` explains when to design a large workflow.
- `references/workflow-patterns.md` defines reusable workflow patterns.
- `docs/spec.md` records product scope, safety, fixtures, and release criteria.
- release checks validate skill packaging.

### V0.5: Plan Schema And Evaluator

Status: done.

Purpose: convert workflow designs into a machine-checkable
`workflow.plan.json` contract and fixture corpus.

Done means:

- `references/workflow-plan-schema.md` documents the plan contract.
- `scripts/evaluate_plan.py` validates plans and downgrade artifacts.
- `fixtures/v0.5/manifest.json` proves positive, negative, borderline, and
  meta cases.
- `docs/v0.5-decision.md` records a `keep` decision from regenerated evidence.

### V1: First-Slice Compiler

Status: done.

Purpose: compile one activated plan into one inspectable first-slice packet
without executing it.

Done means:

- `scripts/compile_workflow.py` compiles activated V0.5 plans.
- output is deterministic, repo-local, sentinel-owned, and symlink-safe.
- `--resume` detects stale source, snapshot, packet, prompt, input, handoff,
  gate, approval, compiler, and run metadata.
- risk gates block unsafe first slices by default.
- `fixtures/v1/manifest.json` passes with `decision: "keep"`.
- `docs/v1-decision.md` records the generated summary.

### V2: First-Slice Execution Adapter

Status: release candidate; fixture gate keep.

Purpose: execute exactly one V1 compiled packet through a controlled backend and
record evidence, without pretending to be a full workflow runtime.

Spec: `docs/v2-execution-adapter-spec.md`.

Done means:

- a new adapter accepts only trustworthy V1 run directories.
- blocked or stale packets cannot execute.
- execution happens in an isolated worktree or explicit read-only mode.
- every attempt writes evidence: prompt, backend command, stdout/stderr or
  transcript, exit status, git diff summary, verification command outputs, and
  hashes.
- execution status is derived from evidence, not from agent claims.
- failed attempts are resumable without rewriting prior evidence.
- fixture and smoke tests cover ready, blocked, stale, failed, and successful
  execution paths.

V2 release candidate currently means:

- `scripts/execute_packet.py --self-test` covers ready dry-run, blocked-risk
  refusal, stale-prompt refusal, stale-source refusal, malformed attempt
  invalidation, symlinked or renamed attempt refusal, missing hash-key
  invalidation, sidecar tamper rejection, tampered V1 hash rejection, tampered
  status rejection, resume, local-shell success, local-shell public CLI refusal,
  untrusted public manifest refusal, and local-shell failure,
  verification pass, verification failure, dangerous verification-command
  refusal, Codex CLI success fixture, Codex auth-block fixture, and Codex
  worktree-required refusal.
- `fixtures/v2/manifest.json` covers dry-run/trust, local-shell success/failure,
  worktree-required refusal, dirty-worktree refusal, automatic verification
  pass/fail, append-only attempts, stale source detection, malformed attempt
  detection, dangerous fixture-command refusal, dangerous verification-command refusal,
  omitted-required default handling, optional-fixture failure handling, and
  required-fixture failure policy.
- V2 writes append-only dry-run attempt evidence for trusted ready packets.
- V2 can execute deterministic manifest-scoped local-shell commands in isolated
  git worktrees and record stdout/stderr/exit status.
- V2 can execute deterministic manifest-scoped verification commands and derive
  `verified` or `failed` from their exit status.
- Public `--manifest` is limited to `fixtures/v2/manifest.json`; command-bearing
  fixtures use approved release-fixture snippets, not arbitrary shell commands.
- V2 can execute Codex fixture-command mode in an isolated worktree, capture
  transcript/stdout/stderr, detect authentication failures, and preserve timeout
  or backend failures as evidence; installed codex path remains optional live smoke evidence
  until local auth can be assumed by a release gate.
- `docs/v2-decision.md` records the generated `decision: "keep"` summary.
- OMX execution, verification commands from plan handoff schemas, and
  multi-slice advancement remain future slices.

### V2.5: Execute-Review-Repair Loop

Status: first loop implemented; backend repair execution deferred.

Purpose: add one supervised correction cycle after a packet execution.

Spec: `docs/v2.5-review-repair-spec.md`.

Workflow plan: `docs/v2.5-to-v3.workflow.plan.json`.

First-loop done means:

- a deterministic reviewer consumes trusted V2 execution evidence.
- findings are stored as structured review artifacts.
- a repair prompt can be prepared only when the packet remains trusted and the
  latest review has actionable findings.
- the loop has strict retry caps and stops on repeated failure.
- final status separates `review-approved`, `changes-requested`,
  `repair-prepared`, `needs-human`, and `invalid`.
- review and repair artifacts have parent-level contract ledgers so coherent
  evidence rewrites invalidate resume.
- `fixtures/v2.5/manifest.json` passes with `decision: "keep"`.
- `docs/v2.5-decision.md` records the generated summary.

Implemented first slice:

1. add `fixtures/v2.5/manifest.json` with deterministic review fixtures,
2. add review and repair contracts with `review-contracts.json` and
   `repair-contracts.json`,
3. implement `--review`, `--review-resume`, and `--repair`,
4. prepare repair prompts without launching a backend,
5. prove coherent review tamper invalidates resume.

Next V2.5 slice:

1. add one manifest-scoped repair backend only after review trust is proven,
2. derive `repair-executed` and `repair-verified`,
3. add retry-cap fixtures for repeated failures.

### V3: Runtime Entry

Status: entry runtime implemented; full multi-slice execution deferred.

Purpose: advance beyond the first slice while preserving the V1/V2 trust model.

Spec: `docs/v3-runtime-entry-spec.md`.

V3 consumes only trusted V2.5 terminal states. It rejects `failed`, `invalid`,
`review-pending`, `changes-requested`, `repair-prepared`, and `needs-human`
packet states. `--human-approved` is recorded and type-checked, but it is not
sufficient to advance without a later explicit human-override contract.

Entry-runtime done means:

- `scripts/run_workflow.py` accepts only trusted V2.5 evidence.
- accepted states write `run.json`, `next/0001.packet.json`,
  `next/0001.prompt.md`, `journal/0000.json`, `status.json`, and `resume.md`.
- accepted states select the next phase after the reviewed first slice.
- accepted states require reviewed V2 evidence with automatic verification pass.
- unmatched first-slice output is rejected instead of guessed.
- `--resume` detects stale V2.5 status and tampered next-packet artifacts.
- `--resume` refuses non-owned runtime directories and malformed
  `human_approved` values.
- `needs-human` remains rejected even with explicit `--human-approved`.
- `fixtures/v3/manifest.json` passes with `decision: "keep"`.
- `docs/v3-decision.md` records the generated summary.
- the entry runtime does not execute the next packet.

Full runtime done means:

- later packets are compiled from the original plan plus verified prior
  outputs.
- packet advancement is deterministic and hash-bound.
- each phase has entry criteria, exit criteria, handoff artifacts, and
  invalidation rules.
- resume skips valid completed packets and reruns only invalidated packets.
- human gates can pause the workflow without losing completed evidence.

### V4: Parallel Worker Orchestration

Status: first scheduler slice implemented.

Purpose: run independent packets in parallel with fan-in verification.

First scheduler slice done means:

- `scripts/orchestrate_workflow.py` consumes trusted V3 runtime output.
- V4 emits `schedule.json`, packet prompts, a journal, status, and resume docs.
- V4 selects every currently ready phase up to the plan concurrency cap.
- V4 preserves handoff schemas, worker contracts, expected outputs, and stop
  conditions in generated packets.
- V4 resume detects tampered schedule, packet, prompt, and journal artifacts.
- V4 self-test covers linear scheduling, fan-out scheduling, concurrency caps,
  clean resume, and tampered schedule invalidation.
- V4 dogfood over `out/v3/v32-semantic-dogfood` schedules `evidence_review`.

Full worker orchestration done means:

- workers have isolated worktrees and bounded context.
- concurrency caps are explicit.
- handoffs use shared schemas.
- fan-in runs only after required branches finish or are marked non-blocking.
- conflicting diffs are detected before merge.
- independent reviewers can refute worker outputs before synthesis.

### V4.5: Worker Dispatch Preparation

Status: first dispatch slice implemented.

Purpose: bridge scheduled V4 packets to future worker execution without opening
execution yet.

First dispatch slice done means:

- `scripts/dispatch_worker.py` consumes one trusted V4 packet.
- V4.5 writes `dispatch.json`, `packet.json`, `prompt.md`, `hashes.json`,
  `status.json`, and `resume.md`.
- V4.5 requires the packet and prompt hashes to match V4 status snapshots.
- V4.5 requires the packet phase to be selected by V4 `schedule.json`.
- V4.5 resume detects tampered dispatch, packet copy, prompt copy, and hashes.
- V4.5 dogfood over the `evidence_review` packet produces `status: prepared`.

Full dispatch done means:

- prepared dispatches can be handed to a bounded worker backend,
- worker outputs return through V2/V2.5-style reviewed evidence,
- V3/V4 advancement consumes only reviewed worker results,
- execution remains blocked for destructive, external, costly, production,
  secret, dependency, database, public API, delete, and history-rewrite actions.

### V5: Controlled Worker Result Adapter

Status: first controlled worker-result slice implemented.

Purpose: execute one trusted V4.5 dispatch through an allowlisted fixture worker
and record evidence under owned `out/v5/`.

First controlled slice done means:

- `scripts/run_worker_result.py` consumes one trusted V4.5 dispatch directory.
- V5 supports only `--fixture semantic-review`.
- V5 runs the fixture in `out/v5/<run_id>/work/`, not in the repository root.
- V5 writes `result.json`, `stdout.txt`, `stderr.txt`, `hashes.json`,
  `status.json`, and `resume.md`.
- V5 produces `verification.md` for the `evidence_review` dogfood packet.
- V5 resume detects tampered produced outputs through hash mismatch.
- V5 dogfood over `out/v4.5/v32-semantic-dogfood` produces `status: executed`.

Full worker result adapter done means:

- worker outputs can be routed into a V2.5-style review contract,
- reviewed worker results can satisfy phase exit criteria,
- V3/V4 can advance from reviewed worker results,
- non-fixture backends remain behind explicit trust and human gate contracts.

### V5.5: Worker Result Review

Status: first review slice implemented.

Purpose: review V5 worker-result evidence before any runtime treats a later
phase as complete.

First review slice done means:

- `scripts/review_worker_result.py` consumes one trusted V5 result directory.
- V5.5 validates V5 ownership, status, hashes, stdout/stderr, and produced
  outputs.
- V5.5 approves only the dogfood `evidence_review` result with
  `verification.md`.
- V5.5 writes `review.json`, `review.md`, `hashes.json`, `status.json`, and
  `resume.md`.
- V5.5 resume detects stale source evidence and tampered review artifacts.
- V5.5 does not advance runtime or execute workers.
- V5.5 dogfood over `out/v5/v32-semantic-dogfood` produces
  `status: review-approved`.

Full worker result review done means:

- reviewed worker results can satisfy phase exit criteria,
- unsupported output schemas produce `needs-human` instead of guessed approval,
- rejected worker results can route to a bounded repair workflow,
- only reviewed results can be consumed by future runtime ingestion.

### V6: Runtime Ingestion

Status: first ingestion slice implemented.

Purpose: consume reviewed V5.5 worker results as completed phase evidence and
emit the next scheduler frontier without executing it.

First ingestion slice done means:

- `scripts/ingest_worker_review.py` consumes one trusted V5.5 review directory.
- V6 requires V5.5 `status: review-approved` and clean resume.
- V6 reconstructs V5 -> V4.5 -> V4 -> V3 -> V1 lineage before ingestion.
- V6 marks the reviewed source phase complete only when it was selected by the
  original V4 schedule.
- V6 emits `state.json`, frontier packet prompts, journal, hashes, status, and
  resume docs under owned `out/v6/`.
- V6 resume detects tampered state, packet, prompt, journal, hashes, and stale
  source review evidence.
- V6 dogfood over `out/v5.5/v32-semantic-dogfood` produces
  `status: frontier-ready` and selects `release_decision`.
- V6 does not execute the next packet.

Full runtime ingestion done means:

- multiple reviewed worker results can fan in safely,
- rejected worker results route to repair instead of blocking manually,
- human-gated phases preserve completed evidence while waiting,
- the scheduler can loop from V6 frontier back to V4/V4.5/V5/V5.5.

### V7: Product Packaging

Status: planned.

Purpose: make the system usable as a durable tool, not only as scripts.

Done means:

- package as a Codex skill/plugin or CLI surface.
- expose run status, gates, evidence, and resume actions.
- include migration guides from V1/V2 artifacts.
- publish stable command contracts and compatibility notes.
- keep external runtime integrations optional and adapter-based.

## Strategic Decisions

- Build the compiler/control-plane path before a full runtime.
- Treat execution backends as adapters, not as the source of truth.
- Prefer OMX/Codex integration over copying an existing runtime surface.
- Never mark work complete from a model message alone; require evidence and
  verification.
- Keep destructive, external, costly, production, secret, dependency, database,
  public API, and history-rewrite actions behind human gates.
- Preserve old attempt evidence instead of rewriting it.

## Success Criteria For The Final System

The system is final enough for real large-task automation when it can:

1. accept a broad objective and produce a valid workflow plan,
2. compile the next executable packet deterministically,
3. refuse stale or risky packets,
4. execute approved packets in isolation,
5. collect evidence automatically,
6. run verification that can falsify the result,
7. review and repair bounded failures,
8. advance to the next packet without losing traceability,
9. resume after interruption from stored artifacts, and
10. stop at human gates with completed work preserved.

## Non-Goals

- Do not build an unchecked autonomous agent that can mutate arbitrary repos.
- Do not make `--dangerously-bypass-approvals-and-sandbox` the default path.
- Do not require OMX, tmux, or any specific external runtime for the core
  compiler contract.
- Do not hide backend-specific state inside opaque logs.
- Do not treat a clean exit code as sufficient proof of correctness.
