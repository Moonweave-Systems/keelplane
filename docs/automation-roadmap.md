# Depone Automation Roadmap

Status: V3 entry runtime implemented; V7.5 frontier result review implemented; V8 frontier review ingestion implemented; V9 human gate resolution implemented; V10 product CLI implemented; V11 operator guidance implemented; V12-V20 product roadmap implemented; V52-V87 product evidence, graph timing, activation, and brand boundary gates implemented; V88 roadmap reconciliation audit implemented; V89 command safety gate implemented; V90 activation v2 implemented; V91 contract tiering implemented; V92 evidence oracle implemented; V93 workflow narrative implemented; V94 control deck score implemented; V95 score history implemented; V96 metric ladder implemented; V97 benchmark readiness implemented; V98 wave operator implemented; V99 wave receipt implemented; V100 promotion evidence implemented; V101 promotion route implemented; V102 deterministic live-proof recorder implemented; V103 live-proof comparison schema implemented; V104 product direction implemented; V105 verify wedge implemented; V106 multi-wave validation implemented; V107 Agent Fabric contracts and compiler implemented; V108 Agent Fabric reference adapter fixture implemented; V109 Agent Fabric capture bridge implemented; V110 Agent Fabric report assurance implemented; V111 Agent Fabric operator view implemented; V112 Agent Fabric lifecycle smoke implemented; V94-V101 meta layer frozen; live proof n=1 completed
Date: 2026-06-20

## Purpose

Depone is the public product brand for the DWM Core large-task automation
control-plane: a system that can take a broad objective, decompose it into
inspectable work, execute bounded waves, verify results, resume after
interruption, and stop at human gates for risky actions.

This repo should not become a loose prompt pack or an unchecked agent launcher.
DWM's differentiator is a compiler-first control-plane: plans and execution
packets are explicit, hashed, reviewable, resumable, and falsifiable.

## Product Position

Depone should become the control-plane for large Codex workflows. DWM Core
remains the internal deterministic engine, and the skill name is now
`depone`. The `dwm_*.py` file prefix and GitHub repository slug remain
legacy/internal and intentionally deferred.

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
| Frontier dispatch | turn trusted runtime frontier packets into dispatch bundles | first loop-back slice implemented |
| Frontier result adapter | produce controlled next-phase worker evidence | first controlled slice implemented |
| Frontier result review | approve or reject next-phase worker evidence before ingestion | first review slice implemented |
| Frontier review ingestion | consume reviewed frontier results and emit the next frontier | first ingestion slice implemented |
| Human gate resolution | consume explicit human approval and complete human-gated frontier | first resolution slice implemented |
| Product surface | plugin, CLI, dashboard, and release packaging | first operator guidance slice implemented |
| Adapter command planner | generate exact next adapter commands without execution | planned V12, implemented |
| DWM Runner | execute read-only or pre-isolated DWM-approved packets through Codex CLI with evidence | planned V13, MVP implemented |
| Session/worktree runtime | durable sessions, worktree isolation, logs, and resume | planned V14, implemented |
| Runtime review/repair | runner-backed review, repair, and retry loops | planned V15, implemented |
| Multi-worker fanout | bounded parallel Codex workers and deterministic fan-in | planned V16, implemented |
| Dashboard/HUD | local evidence browser, human gates, and next-action UI | planned V17, read-only HUD implemented |
| Plugin/install packaging | installable CLI/plugin and migration surface | planned V18, first install packaging slice implemented |
| Adapter ecosystem | optional Codex, OMX, Claude, shell, and fixture adapters | planned V19, first registry slice implemented |
| 1.0 hardening | compatibility, migration, security, and acceptance gates | planned V20, first release-candidate gate implemented |
| Reviewer gate | independent release-candidate review artifact | planned V20.5, first reviewer gate implemented |
| Dogfood replay | deterministic replay evidence for canonical dogfood chain | planned V20.6, replay gate implemented |
| Product shell | memorable `plan`, `run`, and `resume` commands over safe artifacts | planned V21, first shell slice implemented |
| Role pack | role contracts for planner, explorer, worker, reviewer, verifier, and operator | planned V22, first registry implemented |
| Agent Fabric contracts | deterministic role, toolbelt, profile, harness, compile-report, invocation, and result contracts | planned V107, contract/compiler slice implemented |
| Agent Fabric reference adapter | fixture-only local shell adapter capture shape for self-report, diff/touched files, test output, and command receipts | planned V108, shell fixture implemented |
| Agent Fabric capture bridge | Depone-facing manifest with A0/A1 assurance labels and hash-bound observer capture | planned V109, passive bridge implemented |
| Agent Fabric report assurance | verification report decision/assurance fields sourced from capture manifests | planned V110, report surface implemented |
| Agent Fabric operator view | Markdown export for operator-readable report decision, assurance, and capture status | planned V111, operator view implemented |
| Agent Fabric lifecycle smoke | source-only compile-to-report smoke summary for V107-V111 regression coverage | planned V112, lifecycle smoke implemented |
| Harness benchmark | corpus and scoring gate for direct harness comparisons | planned V23, first benchmark gate implemented |
| README public page | source-bound benchmark graph on the GitHub landing page | planned V37, first publish slice implemented |
| Benchmark history | hash-bound report history ledger and trend graph artifacts | planned V38, first ledger slice implemented |
| Benchmark promotion | promotion gate for public upward trend claims | planned V39, first promotion gate implemented |
| Benchmark snapshot | release-bound benchmark snapshot recorder | planned V40, first snapshot slice implemented |
| Benchmark series | ordered release snapshot collection and history generation | planned V41, first series slice implemented |
| Benchmark candidate | promotion-ready pre-publish benchmark candidate | planned V42, first candidate slice implemented |
| Direction checkpoint | evidence-backed direction check and V44-V50 roadmap | planned V43, direction checkpoint written |
| Candidate review | pre-publish candidate review and overclaim gate | planned V44, first review gate implemented |
| README asset promotion | approved asset bundle and diff summary before tracked changes | planned V45, first promotion bundle implemented |
| Long-run workflow queue | ordered packets, resume, next safe action, and blocked reasons | planned V46, first queue gate implemented |
| Real dogfood corpus | local DWM maintenance tasks and comparison placeholders | planned V47, first corpus recorder implemented |
| Daily operator loop | ready action, blocked gates, and evidence freshness view | planned V48, first operator loop implemented |
| Adapter parity matrix | supported, planned, fixture-only, and unsupported adapter actions | planned V49, first parity matrix implemented |
| Release candidate cut | release notes and checklist from coherent operator and parity evidence | planned V50, first candidate cut implemented |
| Canonical demo | one local command showing the artifact loop without live adapters | planned V51, first demo implemented |

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

### V6.5: Frontier Dispatch

Status: first loop-back slice implemented.

Purpose: consume trusted V6 frontier packets and emit owned dispatch bundles
without executing them.

First loop-back slice done means:

- `scripts/dispatch_frontier.py` consumes one trusted V6 frontier directory.
- V6.5 requires V6 `status: frontier-ready` and clean resume.
- V6.5 verifies the selected packet and prompt hashes against V6 state.
- V6.5 emits `dispatch.json`, `packet.json`, `prompt.md`, `hashes.json`,
  `status.json`, and `resume.md` under owned `out/v6.5/`.
- V6.5 resume detects tampered dispatch, packet copy, prompt copy, and hashes.
- V6.5 dogfood over `out/v6/v32-semantic-dogfood` prepares
  `release_decision`.
- V6.5 does not execute the frontier packet.

Full loop-back done means:

- prepared frontier dispatches can enter a controlled worker-result adapter,
- reviewed next-phase results can be ingested by V6 again,
- the runtime can repeat until no selected phases remain or a human gate stops
  the workflow.

### V7: Controlled Frontier Result Adapter

Status: first controlled frontier-result slice implemented.

Purpose: execute one trusted V6.5 frontier dispatch through an allowlisted
fixture worker and record next-phase evidence under owned `out/v7/`.

First controlled slice done means:

- `scripts/run_frontier_result.py` consumes one trusted V6.5 dispatch
  directory.
- V7 supports only `--fixture release-decision`.
- V7 runs the fixture in `out/v7/<run_id>/work/`, not in the repository root.
- V7 writes `result.json`, `stdout.txt`, `stderr.txt`, `hashes.json`,
  `status.json`, and `resume.md`.
- V7 produces `release-decision.md` for the `release_decision` dogfood packet.
- V7 resume detects tampered produced outputs through hash mismatch.
- V7 dogfood over `out/v6.5/v32-semantic-dogfood` produces
  `status: executed`.

Full frontier result adapter done means:

- non-fixture next-phase workers remain behind explicit trust contracts,
- V7 results can be routed into a generalized review layer,
- reviewed results can return to runtime ingestion until workflow completion or
  a human gate.

### V7.5: Frontier Result Review

Status: first review slice implemented.

Purpose: review V7 frontier-result evidence before any runtime ingestion treats
the `release_decision` phase as complete.

Spec: `docs/v7.5-frontier-result-review-spec.md`.

Workflow plan: `docs/v7.5-frontier-result-review.workflow.plan.json`.

First review slice done means:

- `scripts/review_frontier_result.py` consumes one trusted V7 result directory,
- V7.5 requires V7 `status: executed` and clean resume,
- V7.5 validates the V7 -> V6.5 -> V6 lineage before review,
- V7.5 approves only the first `v6-frontier-0001-release_decision` fixture
  result with `release-decision.md`,
- V7.5 writes review, markdown, hashes, status, and resume artifacts under
  owned `out/v7.5/`,
- V7.5 resume detects stale V7 source evidence and tampered review artifacts,
- V7.5 does not ingest runtime state or execute workers.

Full frontier result review done means:

- reviewed frontier results can be ingested by the next V6-style loop,
- unsupported frontier output schemas route to `needs-human`,
- rejected frontier results route to bounded repair instead of guessed
  approval,
- only reviewed frontier results can complete next-phase runtime work.

### V8: Frontier Review Ingestion

Status: first ingestion slice implemented.

Purpose: ingest V7.5 reviewed frontier-result evidence into runtime frontier
state so `release_decision` can complete without trusting unreviewed V7 output.

Spec: `docs/v8-frontier-review-ingestion-spec.md`.

Workflow plan: `docs/v8-frontier-review-ingestion.workflow.plan.json`.

First ingestion slice done means:

- `scripts/ingest_frontier_review.py` consumes one trusted V7.5 review
  directory,
- V8 requires V7.5 `status: review-approved` and clean resume,
- V8 validates the V7.5 -> V7 -> V6.5 -> V6 lineage before ingestion,
- V8 appends `release_decision` to `completed_phase_ids`,
- V8 preserves previous `reviewed_phase_ids` and appends `release_decision`,
- V8 recomputes the next ready frontier from the original plan,
- V8 dogfood selects `human_gate` rather than claiming workflow completion,
- V8 writes run, state, packet, prompt, journal, hashes, status, and resume
  artifacts under owned `out/v8/`,
- V8 resume detects stale source evidence and tampered generated artifacts,
- V8 does not execute workers or satisfy human gates.

Full frontier review ingestion done means:

- reviewed frontier results can continue through repeated loops,
- multi-result fan-in has deterministic ordering and conflict handling,
- human gates are explicit packets, not silent completions,
- workflow completion is declared only when no ready or blocked phase remains.

### V9: Human Gate Resolution

Status: first resolution slice implemented.

Purpose: resolve the V8 `human_gate` frontier through a tracked approval
artifact without treating chat text as runtime evidence.

Spec: `docs/v9-human-gate-resolution-spec.md`.

Workflow plan: `docs/v9-human-gate-resolution.workflow.plan.json`.

First resolution slice done means:

- `scripts/resolve_human_gate.py` consumes one trusted V8 frontier and one
  tracked approval artifact,
- V9 requires V8 `status: frontier-ready`, clean resume, and selected
  `human_gate`,
- V9 requires the approval to match the V8 run, packet, and phase,
- V9 appends `human_gate` to `completed_phase_ids`,
- V9 records `human_approved_phase_ids`,
- V9 recomputes the frontier from the original plan and rejects nonterminal
  cases in the first slice,
- V9 dogfood reports `workflow-complete`,
- V9 writes run, state, approval markdown, journal, hashes, status, and resume
  artifacts under owned `out/v9/`,
- V9 resume detects stale source evidence and tampered generated artifacts,
- V9 does not execute workers, merge worktrees, deploy, or call external
  services.

Full human gate resolution done means:

- multiple human gates can be resolved with deterministic ordering,
- rejected and deferred gates route to bounded follow-up states,
- approval artifacts can be produced by a real UI or CLI prompt,
- workflow completion remains hash-bound and replayable.

### V10: Product Packaging

Status: first CLI packaging slice implemented.

Purpose: make the system usable as a durable tool, not only as scripts.

Spec: `docs/v10-product-packaging-spec.md`.

Workflow plan: `docs/v10-product-packaging.workflow.plan.json`.

First CLI packaging slice done means:

- `scripts/dwm.py` exposes `status`, `doctor`, `commands`, and `--self-test`,
- `status` summarizes a DWM run directory under repo-local `out/`,
- `doctor` checks the repo product surface and canonical V9 dogfood completion,
- `commands` prints release and dogfood command sets,
- V10 release checks include the DWM CLI self-test,
- V10 does not execute workflow stages, launch workers, call external runtimes,
  install dependencies, write artifacts, or use the network.

Full product packaging done means:

- package as a Codex plugin or installable CLI surface,
- expose run status, gates, evidence, and resume actions,
- include migration guides from V1/V2 artifacts,
- publish stable command contracts and compatibility notes,
- keep external runtime integrations optional and adapter-based.

### V11: Operator Guidance

Status: first operator guidance slice implemented.

Purpose: make the product CLI useful as a safe day-to-day operator loop, not
only a status dashboard.

Spec: `docs/v11-operator-guidance-spec.md`.

Workflow plan: `docs/v11-operator-guidance.workflow.plan.json`.

First operator guidance slice done means:

- `scripts/dwm.py next` verifies one run and recommends the next safe action,
- `next` returns trust checks, verified artifact hash count, blockers, safe
  default, approval requirement, and recommended commands,
- `commands --kind product` lists day-to-day DWM product commands,
- V11 release checks include `next` and product command discovery,
- V11 does not execute workflow stages, launch workers, create approvals, call
  external runtimes, install dependencies, write artifacts, or use the network.

Full operator guidance done means:

- recommend exact deterministic adapter commands for every V1-V9 terminal
  state,
- expose approval packet summaries and evidence paths for human review,
- provide machine-readable stop reasons for future UI/plugin surfaces,
- make stale, tampered, blocked, complete, and ready states visually distinct,
- keep every recommendation falsifiable through hash-bound evidence.

### V12-V20: Implemented Product Roadmap

Status: implemented.

Index: `docs/v12-to-v20-final-roadmap.md`.

The planned roadmap splits the remaining product into versioned specs:

- V12 adapter command planner:
  `docs/v12-adapter-command-planner-spec.md`,
- V13 DWM Runner MVP:
  `docs/v13-dwm-runner-mvp-spec.md`,
- V14 session and worktree runtime:
  `docs/v14-session-worktree-runtime-spec.md`,
- V15 runtime review and repair:
  `docs/v15-runtime-review-repair-spec.md`,
- V16 multi-worker fanout:
  `docs/v16-multi-worker-fanout-spec.md`,
- V17 dashboard and approval UI:
  `docs/v17-dashboard-hud-spec.md`,
- V18 plugin and install packaging:
  `docs/v18-plugin-install-packaging-spec.md`,
- V19 adapter ecosystem:
  `docs/v19-adapter-ecosystem-spec.md`,
- V20 1.0 release hardening:
  `docs/v20-1.0-release-hardening-spec.md`,
- V20.5 release reviewer gate:
  `docs/v20.5-reviewer-gate-spec.md`,
- V20.6 dogfood replay gate:
  `docs/v20.6-dogfood-replay-spec.md`,
- V21 product shell:
  `docs/v21-product-shell-spec.md`,
- V22 role pack:
  `docs/v22-role-pack-spec.md`,
- V23 harness benchmark:
  `docs/v23-harness-benchmark-spec.md`,
- V24 live benchmark evidence:
  `docs/v24-live-benchmark-evidence-spec.md`,
- V25 benchmark task materializer:
  `docs/v25-benchmark-task-materializer-spec.md`,
- V26 benchmark attempt harness:
  `docs/v26-benchmark-attempt-harness-spec.md`,
- V27 adapter smoke:
  `docs/v27-adapter-smoke-spec.md`,
- V28 live attempt planner:
  `docs/v28-live-attempt-planner-spec.md`,
- V29 live runner preflight:
  `docs/v29-live-runner-preflight-spec.md`,
- V30 live receipt ingestion:
  `docs/v30-live-receipt-ingestion-spec.md`.
- V31 live receipt judgment:
  `docs/v31-live-receipt-judgment-spec.md`.
- V32 live score verifier:
  `docs/v32-live-score-verifier-spec.md`.
- V32-V35 live scoring workflow:
  `docs/v32-to-v35-live-scoring-workflow.md`.
- V33 live score aggregate:
  `docs/v33-live-score-aggregate-spec.md`.
- V34 live score review:
  `docs/v34-live-score-review-spec.md`.
- V35 live benchmark report:
  `docs/v35-live-report-spec.md`.
- V36 README benchmark graph:
  `docs/v36-readme-benchmark-graph-spec.md`.
- V37 README public page:
  `docs/v37-readme-public-page-spec.md`.
- V38 benchmark history:
  `docs/v38-benchmark-history-spec.md`.
- V39 benchmark promotion:
  `docs/v39-benchmark-promotion-spec.md`.
- V40 benchmark snapshot:
  `docs/v40-benchmark-snapshot-spec.md`.
- V41 benchmark series:
  `docs/v41-benchmark-series-spec.md`.
- V42 benchmark candidate:
  `docs/v42-benchmark-candidate-spec.md`.
- V43 direction check:
  `docs/v43-direction-check-roadmap.md`,
  `docs/v43-direction-check-roadmap.workflow.plan.json`.
- V44 candidate review:
  `docs/v44-candidate-review-gate-spec.md`.
- V45 README asset promotion:
  `docs/v45-readme-asset-promotion-spec.md`.
- V46 long-run workflow queue:
  `docs/v46-long-run-workflow-queue-spec.md`.
- V47 real dogfood corpus:
  `docs/v47-real-dogfood-corpus-spec.md`.
- V48 daily operator loop:
  `docs/v48-daily-operator-loop-spec.md`.

These specs define the implemented path to an independent Depone product
that can use Codex CLI directly through DWM Runner while keeping optional
adapter targets outside DWM Core.

### V43: Direction Check And Forward Roadmap

Status: direction checkpoint written.

Purpose: judge whether DWM is still moving toward meaningful product value and
define the next roadmap without turning benchmark graphs into decoration.

Spec: `docs/v43-direction-check-roadmap.md`.

Workflow plan: `docs/v43-direction-check-roadmap.workflow.plan.json`.

Done means:

- current direction is judged against implemented artifacts and remaining gaps;
- V44-V50 are ordered by user value and benchmark integrity;
- README and roadmap point to the checkpoint;
- tracked benchmark assets remain unchanged until a later candidate review gate.

### V44: Candidate Review Gate

Status: first review gate implemented.

Purpose: review V42 candidate evidence before any tracked README asset is
changed.

Spec: `docs/v44-candidate-review-gate-spec.md`.

Done means:

- `scripts/dwm_benchmark_candidate_review.py` writes `candidate-review.json`;
- candidate, promotion, series, and history hashes are recomputed;
- unsupported external benchmark or model-superiority claims are blocked;
- `fixtures/v44/manifest.json` proves ready, stale, missing-promotion,
  hash-drift, and overclaim paths.

### V45: README Asset Promotion

Status: first promotion bundle implemented.

Purpose: turn an approved V44 review into a reviewable README asset promotion
bundle before tracked assets or README are changed.

Spec: `docs/v45-readme-asset-promotion-spec.md`.

Done means:

- `scripts/dwm_readme_asset_promotion.py` writes `asset-promotion.json`;
- approved SVG and metadata are copied into an owned output bundle;
- `asset-diff.md` records the proposed tracked asset and README changes;
- stale review, missing asset, hash drift, non-approved review, and overclaim
  paths are blocked.

### V46: Long-Run Workflow Queue

Status: first queue gate implemented.

Purpose: let DWM continue from ordered roadmap packets without constant manual
nudges while still stopping on real gates.

Spec: `docs/v46-long-run-workflow-queue-spec.md`.

Done means:

- `scripts/dwm_workflow_queue.py` writes `queue.json` and `next-action.md`;
- the first safe non-terminal packet becomes `ready`;
- terminal packets can produce a `complete` queue state;
- missing evidence, unsafe actions, failed verification, human gates, and stale
  queue status are blocked.

### V47: Real Dogfood Task Corpus

Status: first corpus recorder implemented.

Purpose: define real local DWM maintenance tasks with evidence requirements and
comparison slots before running benchmark attempts.

Spec: `docs/v47-real-dogfood-corpus-spec.md`.

Done means:

- `scripts/dwm_dogfood_corpus.py` writes `dogfood-corpus.json`;
- tasks are local dogfood only, not external benchmark claims;
- direct Codex and DWM-controlled comparison slots start as `not-run`;
- unsafe tasks, public claims, missing required tasks, and missing evidence
  requirements are blocked;
- V46 queue packets are emitted for later measured attempts.

### V48: Daily Operator Loop

Status: first operator loop implemented.

Purpose: show the next safe daily action, blocked gates, and evidence freshness
across current queue and corpus artifacts.

Spec: `docs/v48-daily-operator-loop-spec.md`.

Done means:

- `scripts/dwm_daily_operator.py` writes `operator-loop.json` and `today.md`;
- ready queue actions are surfaced without executing them;
- blocked queues surface explicit blocked reasons;
- stale queue, missing corpus, and missing linked queue states are blocked.

### V49: Adapter Parity Matrix

Status: first parity matrix implemented.

Purpose: keep Codex, Claude, shell, and fixture adapter support honest before
the release-candidate cut.

Spec: `docs/v49-adapter-parity-matrix-spec.md`.

First adapter parity slice done means:

- `packaging/dwm-adapters.json` records support level, auth assumption, and
  isolation for each adapter;
- `scripts/dwm_adapters.py parity` writes `adapter-parity.json` and
  `adapter-parity.md`;
- planned live adapter actions are blocked with deterministic reasons;
- unsupported risk capabilities are blocked before execution;
- `fixtures/v49/manifest.json` passes with `decision: "keep"`.

### V50: Release Candidate Cut

Status: first release candidate cut implemented.

Purpose: prepare a public release candidate only from coherent operator and
adapter parity evidence.

Spec: `docs/v50-release-candidate-cut-spec.md`.

First release candidate cut done means:

- `scripts/dwm_release_candidate.py cut` consumes V48 operator and V49 parity
  artifacts;
- `release-candidate.json`, `release-notes.md`, and `release-checklist.md` are
  written under owned output;
- missing/stale evidence and unsupported overclaims block deterministically;
- `fixtures/v50/manifest.json` passes with `decision: "keep"`.

### V51: Canonical Demo

Status: first canonical demo implemented.

Purpose: give new users one command that demonstrates DWM's artifact loop before
they need to understand every internal V-slice.

Spec: `docs/v51-canonical-demo-spec.md`.

First canonical demo done means:

- `scripts/dwm_demo.py run` writes `demo.json`, `status.json`, and `README.md`;
- the demo records plan, compile, packet-review, adapter-parity, dogfood,
  daily-operator, and release-candidate artifacts;
- unsafe and non-owned output paths are blocked;
- `fixtures/v51/manifest.json` passes with `decision: "keep"`.

### V52-V106: Product Evidence And Control Deck

Status: implemented through V106 multi-wave validation, with V107-V110 Agent
Fabric contract, adapter, capture, and report-assurance slices recorded as the
next contract layer; the V103 live two-arm comparison remains behind explicit
approval; V94-V101 meta layer is frozen.

Purpose: move from a runnable demo into a product that can explain its current
state, measure real dogfood evidence, gate graph claims, continue safely across
several source-only waves, activate the next workflow, keep public positioning
coherent, and avoid trusting declared command risk alone.

Implemented continuation:

- V52-V53 made the README and demo inspect path product-facing.
- V54-V67 built dogfood attempts, measurements, pair comparisons, chart review,
  chart rendering, and process-progress asset promotion.
- V69-V72 added README quality and release timing evidence.
- V73-V77 added six-axis large-workflow control, dogfood control receipts,
  next-action selection, queue bridging, and queue preflight.
- V78-V79 separated process progress visibility from public benchmark trend
  claims.
- V80-V83 defined how far source-only work can continue before queued execution
  and live adapter execution must stop.
- V84-V85 verified the installed skill surface and activated the next workflow
  design path without executing queued commands.
- V86-V87 set Depone as the public brand and added the brand boundary audit.
- V88 roadmap reconciliation audit keeps this spec, roadmap, and release
  history aligned with implementation truth.
- V89 command safety gate adds shared command-shape and inferred-risk checks
  across next-action selection, queue bridging, and queue preflight.
- V90 activation v2 requires brand boundary, roadmap reconciliation, and
  command safety evidence before reporting next-workflow readiness.
- V91 contract tiering adds smoke, changed-surface, and full verification
  layers so iterative work is faster without weakening release approval.
- V92 evidence oracle verifies artifact existence, JSON field claims, text
  evidence, and source-hash links without executing commands.
- V93 workflow narrative renders a Depone Control Deck from artifact-backed
  chart, gate, activation, oracle, and next-move signals.
- V94 control deck score derives an operator-readiness score from the Control
  Deck and source hashes without creating a public benchmark or upward trend
  claim.
- V95 control deck score history records score movement as internal operator
  readiness history and can render a local SVG without creating a public
  benchmark graph.
- V96 metric ladder separates process, operator-readiness, and public-benchmark
  graph levels so real metrics can grow without overclaiming.
- V97 benchmark readiness reports the current internal readiness score and
  keeps README benchmark publication blocked until promotion evidence exists.
- V98 wave operator selects the next large product wave from readiness and
  activation evidence without executing commands.
- V99 wave receipt verifies the selected dogfood evidence wave against
  acquisition evidence without publishing benchmark claims.
- V100 promotion evidence records whether the source evidence can enter human
  review for README graph publication while keeping publication blocked by
  default.
- V101 promotion route turns that evidence into either the next dogfood
  acquisition command plan or a README publication human gate. V94-V101 are now
  frozen as the meta layer.
- V102 live proof adds a deterministic evidence schema and recorder for one
  bounded Codex-backed run. The first real `codex exec` n=1 completed with
  `decision: live-proof-pass`, red-green verification, and approved independent
  review.
- V103 live proof comparison adds a deterministic two-arm schema for direct-codex
  versus dwm-controlled evidence richness. It records no pass-rate, speed, cost,
  or direct-agent superiority claim; the live two-arm run remains opt-in.
- V104 repositioned Depone as a workflow designer plus cross-platform evidence
  verifier above existing agent execution engines.
- V105 added root-controlled evidence-contract wedge fixtures for missing logs,
  forbidden touches, test weakening, missing contracts, and control-file shadows.
- V106 added optional multi-wave execution-path validation while preserving
  first-slice compatibility and existing human gates.
- V107 added deterministic Agent Fabric role/toolbelt/profile/harness contracts,
  compile reports, invocation/result validation, and `compile_agent_fabric(...)`
  without live agent execution or public benefit claims.
- V108 added the first deterministic Agent Fabric reference adapter fixture for
  the local shell harness. It records self-report, diff/touched-file summary,
  test output, and command receipts as `A0-claims-only` material without
  executing commands or calling live models.
- V109 added a passive Agent Fabric capture bridge that emits a Depone-facing
  manifest. Self-report-only manifests remain `A0-claims-only`; hash-bound
  observer captures can reach `A1-local-observed` while tamper, stale-source,
  and unexpected-file cases fail closed.
- V110 surfaced Agent Fabric capture checks in verification reports. Reports
  now separate existing `verdict`, operator-facing `decision`, and capture
  `assurance`, and invalid capture manifests refute the report without hiding
  validation errors.
- V111 added the Agent Fabric operator-view/exporter. The view is
  presentation-only over V110 report fields, keeps invalid captures visible,
  preserves Depone branding, and writes deterministic Markdown through
  `depone verify --operator-view-out`.
- V112 added a source-only Agent Fabric lifecycle smoke helper that threads
  V107 compile output through V108 fixture shape, V109 capture manifest, V110
  verification report fields, and V111 operator view without executing commands
  or upgrading trust.

Next roadmap direction:

1. Run the V103 live two-arm comparison only after explicit approval, preserving
   the bounded evidence-richness claim.
2. Increase real dogfood acquisition so future graphs show measured process
   history rather than decorative upward motion.
3. Improve public install and quickstart flow without renaming packages until a
   migration gate proves compatibility.
4. Expand read-only or pre-isolated live execution only where V84/V85 and queue
   preflight evidence permit it.
5. Promote the V112 lifecycle smoke into a CLI/export surface only if operators
   need it outside tests; otherwise keep it as regression coverage for the
   compile-to-report path.

## Strategic Decisions

- Build the compiler/control-plane path before a full runtime.
- Treat execution backends as adapters, not as the source of truth.
- Prefer narrow adapter integration over copying an existing runtime surface.
- Keep DWM Core and DWM Runner as separate layers under one DWM product.
- Make external runtimes optional adapter targets, not required dependencies.
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
