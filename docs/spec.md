# Depone / DWM Core Spec

Status: V1 implemented, V2 release candidate, V2.5 first loop implemented, V3 entry runtime implemented, V12-V20 product slices implemented, V87 brand boundary audit implemented, V88 roadmap reconciliation, V89 command safety, V90 activation v2, V91 contract tiering, V92 evidence oracle, V93 workflow narrative, V94 control deck score, V95 score history, V96 metric ladder, V97 benchmark readiness, V98 wave operator, V99 wave receipt, V100 promotion evidence, V101 promotion route, V102 deterministic live-proof recorder, V103 live-proof comparison schema, V104 product direction, V105 verify wedge, V106 multi-wave validation, V107 Agent Fabric compiler, V108 reference adapter fixture, V109 capture bridge, V110 report assurance, V111 operator view, V112 lifecycle smoke, V116 Agent Fabric smoke CLI, V117 Agent Fabric harness snapshot, Last updated: 2026-06-24

## Purpose

Depone is the public product brand. DWM Core, the Deterministic Workflow
Machine, helps Codex design and operate large, situation-aware workflows for
work that is too broad for a single normal agent turn. The installed skill
entrypoint is `depone`. Depone
fills the gap between a thin route selector and a full workflow runtime.

The skill entrypoint should produce a concrete workflow architecture: phases,
workers, parallelism, handoff artifacts, verification gates, safety gates,
budgets, and resume strategy. The broader DWM control-plane now also compiles,
dispatches, records, reviews, ingests, and resumes workflow artifacts.

## Product Position

The existing `workflow-router` skill chooses the smallest suitable workflow and
keeps execution bounded. This skill does a different job: it designs the
workflow itself for a very large task.

Positioning:

- `workflow-router`: classify and route ordinary broad work.
- DWM / `depone`: design an ultracode-style workflow for
  major work before execution, then move through deterministic control-plane
  artifacts.
- DWM Runner: execute approved packets through bounded adapters while returning
  normalized evidence to DWM Core.
- DWM Product Shell: expose `run`, `resume`, `status`, `next`, installation,
  HUD, and approval workflows without making any harness the source of truth.
- Optional harness adapters: Codex CLI, Claude Code, OpenCode/OMO, local shell,
  fixtures, or future tools may execute work only through declared adapter
  capabilities and DWM gates.
- V0.5 continuation gate: prove the machine-readable `workflow.plan.json`
  contract, deterministic fixture corpus, and evaluator before plugin/runtime
  work begins. V0.5 validates tracked sample artifacts; it does not run a live
  model against `SKILL.md`.
- V1 compiler gate: prove deterministic first-slice packet generation, blocked
  risk gates, and resume invalidation before execution work begins.
- V2 execution-adapter gate: execute exactly one trusted first-slice packet in a
  controlled backend, record evidence, and derive packet-scoped verification
  status without claiming a full runtime.
- V2.5 review/repair gate: consume one trusted V2 packet attempt, store
  structured review findings, optionally prepare or run one bounded repair, and
  hand only trusted terminal states to V3.
- V3 runtime-entry gate: consume trusted V2.5 terminal states, write a runtime
  journal and next-packet candidate, and reject stale or unsafe continuation
  states without executing later packets.
- V12-V20 product gate: make the product usable as a local control-plane over
  real tools without copying a full agent harness. The product path is command
  planning, runner execution, session/worktree durability, review/repair,
  bounded fanout, HUD, install packaging, adapter registry, and release
  hardening.
- V86-V100 brand, roadmap, command safety, activation, contract tier, evidence oracle, narrative, score, history, and metric gates:
  make Depone the public product brand, preserve DWM Core and
  the `depone` skill name, keep the spec, roadmap, and
  release history aligned through audit artifacts, prevent command planning from
  trusting declared `risk_codes` alone, require that evidence before
  next-workflow activation, and keep iterative verification fast enough to use.

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
- Oh-My-OpenAgent/OMO shows that agent harnesses become useful when they provide
  low-friction commands, role presets, hooks, LSP/AST tools, background workers,
  and a persistent "keep going" execution loop.
- OMO also shows the cost of a harness-first approach: install footprint,
  provider/model drift, hook compatibility issues, scratch-space leakage,
  telemetry and global-config concerns, and difficulty separating model claims
  from verified state transitions.
- DWM should not become an OMO clone. It should treat OMO, Codex, Claude Code,
  OpenCode, shell, and local fixtures as optional execution backends behind a
  deterministic control-plane whose source of truth remains plans, packets,
  evidence, reviews, hashes, gates, and resume state.

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

### V2: First-Slice Execution Adapter

Implement the execution adapter specified in
`docs/v2-execution-adapter-spec.md`: accept a trustworthy V1 run directory,
refuse stale or blocked packets, execute exactly one first-slice packet through
a controlled backend, and record append-only evidence.

V2 is not a multi-slice workflow runtime. It is the first real automation bridge
between the compiler and Codex/OMX/local backends. Current V2 slices support
dry-run evidence, manifest-scoped local-shell execution, worktree isolation,
dirty-worktree blocking, manifest-scoped verification commands, and Codex CLI
fixture-command execution with transcript/evidence capture. The installed Codex
path exists as optional live-smoke evidence, not as part of the fixture keep
gate. The V2 release fixture gate also covers stale source-plan invalidation,
malformed attempt evidence, append-only attempts, and required-fixture failure
policy.

### V2.5: Execute-Review-Repair Loop

Implement the review and repair loop specified in
`docs/v2.5-review-repair-spec.md` and planned in
`docs/v2.5-to-v3.workflow.plan.json`.

V2.5 consumes exactly one trusted V2 packet attempt. The first implemented loop
stores deterministic structured review artifacts, derives `review-approved`,
`changes-requested`, `repair-prepared`, `needs-human`, or `invalid` from
evidence, and preserves parent-level review and repair contract ledgers. It does
not select later packets, execute backend repairs, or claim full workflow
completion.

### V3: Runtime Entry

Implement the runtime entry specified in `docs/v3-runtime-entry-spec.md`: accept
only trusted V2.5 terminal states, write a deterministic runtime journal,
prepare the next packet candidate, and make resume invalidation explicit.

V3 entry accepts only `review-approved` and `repair-verified`. It rejects
`failed`, `invalid`, `review-pending`, `changes-requested`, `repair-prepared`,
and `needs-human`, even when `--human-approved` is present, until a later slice
defines a stronger human override contract.

V3 entry still does not execute later packets. Full runtime work remains future
scope:

- generated workflow scripts or JSON plans
- phase graph and status file
- subagent spawn adapters
- durable journal
- resume from completed phase outputs
- viewer or textual progress map

See `docs/automation-roadmap.md` for the full roadmap from V0 through product
packaging.

### V12-V20: Product Control-Plane Extension

V12-V20 extend the early workflow contract into a product-level control-plane.
The extension is not a new product thesis; it is the operational form of the
same DWM rule: agents may act, but artifacts decide.

The product stack is:

```text
DWM Product Shell
-> DWM Core
-> DWM Runner
-> optional execution adapters
-> normalized evidence, review, gates, resume
```

Layer ownership:

- DWM Core owns plans, packets, gates, hash ledgers, review state, ingestion,
  and next-action decisions.
- DWM Runner owns process launch, session IDs, worktree/runtime directories,
  stdout/stderr/transcript capture, timeouts, retries, and runner-local logs.
- DWM Product Shell owns human commands, installation, HUD, approval queues, and
  evidence browsing.
- Adapters own harness-specific invocation only. They do not decide whether
  work is trusted.

The required operator commands are:

```bash
dwm run "<objective>"
dwm plan "<objective>"
dwm resume <run>
dwm status <run>
dwm next <run>
```

Each command must preserve the same safety contract as earlier slices: no
destructive, networked, dependency-installing, secret-reading, external-message,
database, production, or history-rewrite action occurs without a matching DWM
gate and a safe default.

### V86-V106: Brand, Roadmap, Command Safety, Activation, Contract Tiers, Evidence Oracle, Narrative, Score, History, Metrics, Live Proof, And Verifier Contracts

V86-V106 align the product surface after the control-plane became broader than a
single skill, harden the command boundary that follows next-action selection,
make next-workflow activation consume those later evidence gates, and split
verification into practical tiers. V92 adds a read-only evidence oracle so later
scores and graphs can be tied to specific artifact assertions instead of status
strings alone. V93 renders those signals as a Depone Control Deck so users
can see chart, gate, activation, oracle, and next-move state without treating
evocative labels as source truth. V94 derives a Control Deck readiness score
from those same artifacts while explicitly blocking public benchmark and upward
trend claims. V94-V101 are frozen as the meta layer and remain bounded to
artifact status, internal readiness, and human-gated publication routing. V95
records those scores as internal readiness history and can
render a local SVG without treating it as a public benchmark graph. V96 adds a
Metric Ladder so process, operator-readiness, and public-benchmark graph levels
stay separate. V97 adds a Benchmark Readiness report so internal readiness
can be scored without becoming a public benchmark graph. V98 adds a Wave
Operator that selects the next source-only product wave from readiness and
activation evidence. V99 adds a Wave Receipt that verifies the selected dogfood
evidence wave has usable acquisition evidence. V100 adds Promotion Evidence so
source artifacts can be recorded before any human review for README graph
publication. V101 adds Promotion Route so that evidence becomes either a
dogfood acquisition command plan or a README publication human gate. The V102
deterministic live-proof recorder now records one bounded live Codex-backed n=1
proof that passed red-green verification and independent review. V103 adds a
deterministic two-arm comparison schema for direct-codex versus dwm-controlled
evidence richness; the live comparison remains opt-in and makes no pass-rate,
speed, cost, or direct-agent superiority claim. V104 repositions Depone as a
workflow designer plus cross-platform evidence verifier. V105 adds the
evidence-contract verify wedge for harness-captured logs, diffs, and root
control files. V106 adds optional multi-wave execution-path validation while
preserving first-slice compatibility. The public
product brand is Depone. DWM Core remains the internal
deterministic engine. The skill name is now `depone`. The `dwm_*.py`
file prefix and GitHub repository slug remain legacy/internal and
intentionally deferred until a separate migration gate proves a rename will
not break install surfaces.

V87 added a brand boundary audit so README, command reference, release history,
and hero surfaces do not drift back to ambiguous public DWM naming or overclaim
autonomous execution.

V88 roadmap reconciliation keeps `docs/spec.md`, `docs/automation-roadmap.md`,
and `docs/release-history.md` aligned with the current implementation state.
This is still audit-only: it does not execute queued commands, run live
adapters, publish benchmark claims, rename packages, or claim autonomous
execution. Later Agent Fabric documentation syncs are part of this same
source-of-truth discipline: specs may describe implemented compiler, capture,
and verification surfaces, but generated `out/` evidence remains derived.

V89 command safety adds shared command-shape and inferred-risk checks for V75,
V76, and V77. Candidate-declared `risk_codes` are no longer authoritative on
their own; supported commands can still be blocked or gated.

V90 activation v2 makes V87 brand boundary, V88 roadmap reconciliation, and V89
command safety part of the readiness decision before DWM says the next workflow
can proceed.

V91 contract tiering adds `smoke`, `changed`, and `full` verification paths
while keeping full release verification as the publishing boundary.

V92 evidence oracle verifies JSON fields, text evidence, artifact existence,
and source-hash links across existing artifacts. It is read-only and does not
execute queued commands, create worktrees, run live adapters, or publish
benchmark claims.

V93 workflow narrative renders a `workflow-narrative.json` and
`workflow-narrative.md` from V88, V89, V90, and V92 artifacts. It may use
Depone-flavored labels such as Chart, Gate, Oracle, and Next move, but those
labels are status rendering only. Artifact assertions and source hashes remain
the source of truth.

V94 control deck score renders `control-deck-score.json` and
`control-deck-score.md` from the narrative plus its source artifacts. It scores
Chart, Gate, Activation, Oracle, source integrity, and voice policy for operator
readiness only. It is not a public benchmark score and does not claim upward
trend performance.

V95 control deck score history renders `control-deck-score-history.json`,
`control-deck-score-history.md`, and `control-deck-score-history.svg` from one
or more V94 score artifacts. It records operator readiness history only. It is
not a public benchmark graph and does not claim upward product quality.

V96 metric ladder renders `metric-ladder.json` and `metric-ladder.md` from V95
readiness history, optional graph timing, and optional benchmark promotion
evidence. It treats readiness history as a real operator metric while blocking
public benchmark claims until promotion evidence exists.

V97 benchmark readiness renders `benchmark-readiness.json` and
`benchmark-readiness.md` from the V96 metric ladder. It records an internal
readiness score and the current public benchmark publication gate. The score is
not a public benchmark graph, and README benchmark publication still requires
promotion evidence plus human review.

V98 wave operator renders `wave-operator.json` and `wave-operator.md` from
benchmark readiness and workflow activation evidence. It chooses the next
source-only product wave, currently dogfood evidence acquisition while public
benchmark publication remains blocked. It does not execute commands, create
worktrees, use the network, or publish benchmark claims.

V99 wave receipt renders `wave-receipt.json` and `wave-receipt.md` from the
selected wave and dogfood acquisition evidence. It verifies that the selected
dogfood evidence wave has usable acquisition evidence. It does not execute
commands or publish benchmark claims.

V100 promotion evidence renders `promotion-evidence.json` and
`promotion-evidence.md` from V99 wave receipt and V97 benchmark readiness
evidence. It records whether source evidence can enter human review for README
graph publication while keeping public benchmark publication disabled by
default. It does not execute commands, publish assets, or claim upward
benchmark progress.

V101 promotion route renders `promotion-route.json` and `promotion-route.md`
from V100 promotion evidence. It plans the next dogfood acquisition command
when promotion evidence is not ready, or emits a human gate when README graph
publication can enter review. It does not execute commands, publish assets, or
approve public benchmark publication.

### V107-V117: Agent Fabric Compiler, Capture, Report, Operator View, Lifecycle Smoke, Smoke CLI, And Harness Snapshot

V107-V117 add the first implemented Agent Fabric control-plane layer without
turning Depone into an agent runtime. V107 validates role, toolbelt, profile,
harness, compile-report, invocation, and result contracts, then compiles
profile roles into deterministic invocation packets and compile reports. V108
adds a fixture-only shell reference adapter shape. V109 bridges that shape into
Depone capture manifests with `A0-claims-only` and `A1-local-observed`
assurance labels. V110 surfaces capture checks in verification reports. V111
renders those report fields as a deterministic operator Markdown view. V112
threads the V107-V111 path together as a source-only lifecycle smoke helper. V116 exposes that source-only smoke as `depone agent-fabric-smoke` so operators can export the JSON summary and optional Markdown view without writing Python. V117 exports static harness capability snapshots from shipped fixtures and tool mappings through `depone agent-fabric-harness-snapshot`.

These slices do not call live models, execute arbitrary commands, hide harness
permission limitations, or claim direct-agent superiority. Unsupported critical
controls still block compilation, approximations stay visible in compile
reports, and Depone verification remains evidence-contract based. The next
Agent Fabric product step should focus on paired dogfood evidence and adapter
smoke evidence before any live adapter or superiority claim.

### Harness Strategy

DWM should learn from multi-agent harnesses without depending on one. The
default product posture is:

- start with one worker, one independent reviewer, and one verifier;
- expand to two or three workers only when packets have independent ownership;
- require deterministic fan-in before any synthesis or merge recommendation;
- record backend, model/provider, prompt, cwd, files touched, commands,
  verification output, transcript path, and adapter hash for every attempt;
- keep all scratch, caches, worktrees, and downloaded assets under a declared
  run-local or repo-local root unless the user approves another location;
- disable or explicitly disclose telemetry in benchmark and release contexts;
- prefer subscription-backed official provider paths when available, but do not
  make API keys or third-party subscription workarounds required for DWM.

Harness-specific decisions:

- Codex CLI is the first native adapter target because it matches the primary
  local operating environment.
- Claude Code is an adapter target for direct Claude workflows, not a backend
  that DWM should proxy through unofficial subscription workarounds.
- OpenCode/OMO is optional prior art and a possible adapter target. DWM may
  reuse its ideas around role presets, LSP/AST tooling, manual-QA loops, and
  low-friction commands, but must not inherit global config mutation, opaque
  hook chains, unrestricted team launch, or unbounded model fallback as product
  defaults.
- Shell and fixture adapters remain necessary for deterministic tests and local
  smoke runs.

### Role Pack

DWM role presets are thin contracts, not personality branding. Each role must
declare allowed tools, context limits, output schema, and evidence obligations.

Required roles:

| Role | Purpose | Trust boundary |
| --- | --- | --- |
| `planner` | turn objective into packets, gates, budgets, and ownership | cannot mark execution complete |
| `explorer` | inspect repo/docs/runtime state and produce evidence-backed maps | read-only unless explicitly upgraded |
| `worker` | perform one bounded packet | result is untrusted until reviewed and verified |
| `reviewer` | find bugs, regressions, missing tests, and contract drift | cannot repair its own findings without a repair packet |
| `verifier` | run tests, browser checks, artifact renders, or command smokes | reports evidence, not product success |
| `operator` | summarize status and next safe action | cannot bypass gates |

The first useful DWM "ulw-like" mode is not an unrestricted keep-going loop. It
is a bounded packet loop:

```text
plan -> packet -> execute -> evidence -> review -> repair -> verify -> ingest -> next
```

Every loop has max rounds, retry limits, file-touch limits, and a stop condition
for repeated failures, missing credentials, unsafe actions, or unavailable
verification.

## Non-Goals

- Do not replace `workflow-router`.
- Do not vendor external runtime code.
- Do not auto-spawn many subagents without explicit user authorization.
- Do not hide destructive or costly actions behind workflow generation.
- Do not treat a workflow blueprint as proof that work is complete.
- Do not compete with Codex, Claude Code, OpenCode, or OMO as a monolithic
  all-in-one harness.
- Do not require API keys when an official subscription-backed local tool path
  can be used directly.
- Do not rely on unofficial subscription workarounds as a release requirement.
- Do not use provider fallback, parallelism, or role count as a proxy for
  quality.

## Activation Contract

The skill activates when:

- the user names `$depone`
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
| "Benchmark OMO against DWM on a failing-test repo." | isolated install, adapter evidence, footprint, hook/provider risks |
| "Run DWM over Codex and Claude Code without API keys." | subscription-aware adapter routing, no unofficial workaround dependency |
| "Use three workers to migrate independent modules." | bounded fanout, ownership, deterministic fan-in, reviewer queue |

For each fixture, record:

- selected patterns
- whether local context was inspected when needed
- whether risky actions were gated
- whether verification can falsify the result
- whether the plan overclaims execution
- which backend or adapter is in scope
- whether scratch, cache, worktree, and downloaded artifacts stay inside the
  declared sandbox
- whether provider/model fallback changed the result or reproducibility

### Harness Benchmark Gate

Any claim that DWM improves over direct Codex, Claude Code, OpenCode/OMO, or a
single-agent baseline must be backed by a small task corpus, not by narrative
comparison.

Minimum corpus:

- failing test fix,
- small refactor,
- auth or permissions audit,
- UI or rendered-artifact regression check,
- docs/code consistency check,
- multi-file migration with ownership conflicts.

For each task, compare applicable modes:

- direct Codex,
- Codex through DWM,
- Claude Code direct,
- Claude Code through DWM when supported,
- OpenCode/OMO when isolated and configured,
- fixture or shell adapter for deterministic control cases.

Record:

- install/runtime footprint,
- provider and model path,
- commands run,
- files touched,
- test and verification output,
- human interventions,
- failed or missing hooks,
- scratch locations,
- telemetry state,
- cost/time where observable,
- final trusted DWM state.

A benchmark passes only if DWM produces more inspectable evidence, safer resume,
or fewer unreviewed changes without hiding failures behind synthesized success.

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

V2 is releasable when:

- `docs/v2-execution-adapter-spec.md` defines the one-packet execution adapter
  behavior.
- `python scripts/execute_packet.py --self-test` passes.
- `python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out
  out/v2/final` records `decision: "keep"`.
- Existing V0.5 and V1 release checks still pass.
- A manual smoke uses a ready V1 packet, performs a V2 dry run, and records
  `repo_tracked_diff_unchanged: true`.
- A manual smoke reuses the blocked V1 run generated by the V2 manifest command
  and proves V2 refuses execution with `ERR_EXEC_BLOCKED_RISK`.
- `docs/v2-decision.md` records the exact V2 manifest command and generated
  summary values from `out/v2/final/summary.json`.
- V2 remains a one-packet adapter: it does not advance beyond the first slice,
  merge worktrees, or claim full large-task automation.

V3 entry is releasable when:

- `docs/v3-runtime-entry-spec.md` defines the trusted-entry behavior.
- `python scripts/run_workflow.py --self-test` passes.
- `python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out
  out/v3/final` records `decision: "keep"`.
- Existing V0.5, V1, V2, and V2.5 release checks still pass.
- required V3 fixtures pass, covering approved advancement, rejected
  `changes-requested`, rejected `repair-prepared`, `needs-human` approval being
  insufficient without verified evidence, next phase candidate selection after
  the reviewed first slice, clean resume,
  stale V2.5 invalidation, tampered next-packet invalidation, tampered journal
  invalidation, unmatched first-slice refusal, ownership sentinel refusal, and
  malformed `human_approved` invalidation.
- `docs/v3-decision.md` records the exact V3 manifest command and generated
  summary values from `out/v3/final/summary.json`.
- V3 entry remains a runtime entry loop: it does not execute later packets,
  orchestrate parallel workers, merge worktrees, or claim full large-task
  automation.

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

V2 execution-adapter checks:

```bash
python scripts/execute_packet.py --self-test
python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final
```

V2.5 execute-review-repair checks:

```bash
python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final
```

V3 runtime-entry checks:

```bash
python scripts/run_workflow.py --self-test
python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final
```

V2 manual smoke checks:

```bash
python scripts/execute_packet.py --run out/v1/v2-final-dry-run-ready-readonly --out out/v2/v2-ready-smoke
```

```bash
python scripts/execute_packet.py --run out/v1/v2-final-dry-run-blocked-risk --out out/v2/v2-blocked-smoke-risk
```

These manual smokes depend on running the V2 manifest command first. The ready
smoke must record `repo_tracked_diff_unchanged: true`. For the blocked smoke,
the V2 command must refuse execution with `ERR_EXEC_BLOCKED_RISK` and create no
attempt.

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
