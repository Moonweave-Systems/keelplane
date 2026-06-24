# V107: Depone Agent Fabric Control Plane Spec

Status: direction spec plus implemented contract/compiler slice
Date: 2026-06-24

## Purpose

V107 defines the intended end state for a world-class agent system that runs
with Depone without collapsing Depone into an agent runtime. The first
contract/compiler slice is now implemented; later adapter and paired-evaluation
work remains deliberately gated.

Depone remains the deterministic control plane:

- plan and policy contracts;
- evidence normalization;
- risk gates;
- decision and assurance;
- retry, repair, and approval boundaries.

The new Agent Fabric is a separate execution-plane layer:

- profile routing;
- role selection;
- concrete tool and MCP allocation;
- context loading;
- harness-specific compilation;
- native agent invocation;
- capture handoff back to Depone.

This spec is intentionally non-implementing. It records the complete product
direction, failure analysis, prior-art scan, architecture, and downstream
implementation prompt so another working context can build it without losing
the design intent.

## Executive Position

> Depone makes agent work governable. Agent Fabric makes agent teams
> effective. They run together, but they do not own the same responsibilities.

The final system should not be another prompt pack and should not be an OMO
clone. It should compile a task into the minimum useful agent team, with each
agent receiving only the tools, MCP servers, context, permissions, and evidence
obligations required for its role.

The main product claim is not "better agents by vibes." The claim is:

> Given the same task and harnesses, Agent Fabric can produce a narrower,
> safer, more inspectable agent run plan, and Depone can determine whether
> the run satisfied that plan from evidence rather than final-message claims.

## Current State

The repository already contains useful ingredients:

- `packaging/dwm-roles.json` defines coarse roles, allowed tool categories,
  output schemas, evidence obligations, and trust boundaries.
- `docs/v22-role-pack-spec.md` validates the first role pack contract.
- `depone-v105-final/docs/agent-team-spec-v1.md` defines strong profile
  rules, role independence, ownership, review independence, and retirement.
- `depone-v105-final/profiles/*.json` define reference profiles:
  `direct-small-fix`, `feature-pipeline`, `parallel-audit`,
  `cross-harness-review`, and `migration-team`.
- `docs/adoption/v105-final-adoption-plan.md` correctly says Depone should
  become a policy and evidence control plane, not a general model runtime.

The initial Agent Fabric material now includes deterministic contracts and
compiler coverage, but it is not yet the desired end state:

- `agents/openai.yaml` is interface metadata, not an agent system.
- V107 compiles profile roles into validated invocation packets and compile
  reports, but it does not launch live agents.
- V108-V112 provide fixture, capture, report, operator-view, and lifecycle-smoke
  coverage for the compile-to-report path.
- Exact Codex, Claude Code, and OpenCode/OMO native adapter behavior remains
  unproven unless a capability snapshot says otherwise.
- Hard MCP/tool allowlist enforcement is represented in contracts, not assumed
  for every harness.
- Context-loading policy is still contract-level and needs later adapter proof.
- There is no paired evaluation proving that a profile beats direct baseline
  for a specific task class.

## Prior Art Scan

The intended direction is aligned with current multi-agent practice, but the
Depone boundary should stay stricter than most frameworks.

OpenAI Agents SDK:

- Agents are configured with instructions, tools, handoffs, guardrails,
  lifecycle hooks, and MCP servers.
- MCP tool filtering exists so an agent can expose only the server functions it
  needs.
- This supports V107's hard toolbelt compiler direction.

Anthropic multi-agent research:

- The production research system uses a lead agent with specialized subagents
  working in parallel.
- The useful parts are orchestrator-worker decomposition, specific subagent
  mandates, separate context windows, careful tool design, and explicit cost
  awareness.
- Anthropic also warns that multi-agent systems can burn far more tokens and
  are not automatically appropriate for tightly coupled coding tasks.

LangChain/LangGraph:

- The supervisor pattern coordinates specialized worker agents.
- The framework recognizes subagents, handoffs, skills, and routers as
  distinct coordination patterns.
- V107 should use the same distinction: routing, delegation, and context
  loading are separate concerns.

CrewAI:

- Hierarchical processes let manager agents delegate and validate outcomes.
- Tools can be assigned at agent or task level for precise availability.
- V107 should not import the ceremony, but it should keep agent/task-level tool
  allocation.

Implication:

The strongest common pattern is not "many agents." It is:

1. route only when the task class justifies it;
2. make each role narrow;
3. expose only the tools needed by that role;
4. make handoffs structured;
5. verify output independently;
6. measure overhead against direct baseline.

Sources checked for this direction:

- OpenAI Agents SDK tools:
  <https://openai.github.io/openai-agents-python/tools/>
- OpenAI Agents SDK MCP:
  <https://openai.github.io/openai-agents-python/mcp/>
- Anthropic multi-agent research system:
  <https://www.anthropic.com/engineering/multi-agent-research-system>
- LangChain multi-agent subagents:
  <https://docs.langchain.com/oss/python/langchain/multi-agent/subagents-personal-assistant>
- CrewAI hierarchical process:
  <https://docs.crewai.com/en/learn/hierarchical-process>

## Product Boundary

### Depone Core

Depone Core is deterministic.

It owns:

- workflow and run contracts;
- role and toolbelt contract validation;
- evidence manifest validation;
- observed command and artifact receipts;
- policy decisions;
- assurance labels;
- safe progression and repair decisions.

It must not:

- call a model;
- become an agent loop;
- choose hidden model/provider routes;
- execute arbitrary agent tool calls;
- treat agent output as authoritative evidence;
- approve gates from agent prose.

### Agent Fabric

Agent Fabric is the agent execution planner and compiler.

It owns:

- task classification;
- profile selection;
- role graph selection;
- concrete toolbelt construction;
- context-pack selection;
- harness adapter selection;
- invocation packet generation;
- self-report schema enforcement;
- capture handoff to Depone.

It must not:

- write final Depone verdicts;
- write authoritative ledgers, seals, approvals, or final decisions;
- bypass harness-native permissions;
- hide unsupported controls;
- make superiority claims without paired evaluation.

### Native Harnesses

Native harnesses remain responsible for actual model execution and native
permission surfaces:

- Codex;
- Claude Code;
- OpenCode/OMO;
- shell and fixture backends;
- later LangGraph, Conductor, or other orchestrators.

Agent Fabric lowers into these harnesses. Depone verifies the evidence
returned from them.

## System Architecture

```text
User goal
  |
  v
Depone activation gate
  - direct vs governed vs team vs cross-harness vs long-run
  |
  v
Agent Fabric router
  - classify task shape
  - select profile
  - select role graph
  |
  v
Toolbelt compiler
  - role permissions
  - concrete tool names
  - MCP subset
  - context policy
  - forbidden tools
  |
  v
Harness adapter compiler
  - Codex config/agent prompt
  - Claude Code instructions
  - OpenCode/OMO agent config
  - shell/fixture packet
  |
  v
Native execution
  - agent self-report
  - logs, diffs, test output, touched files
  |
  v
Depone Capture
  - manifest
  - receipts
  - ledger
  - seal
  |
  v
Depone Verifier
  - pass | fail | inconclusive
  - assurance
  - repair/rerun/approve route
```

## Profiles

Profiles are selected by task shape, not by user excitement about multi-agent
work. Direct execution remains the default.

### direct-small-fix

Use when:

- one ownership region;
- localized acceptance claim;
- one writer is enough.

Shape:

```text
single native agent -> focused check -> optional fresh reviewer -> capture
```

Mandatory properties:

- max writers: 1;
- reviewer optional and read-only;
- no broad research fan-out;
- downgrade target: direct native agent.

### feature-pipeline

Use when:

- one primary write owner;
- nontrivial code path;
- separable exploration and verification.

Shape:

```text
explorer -> implementer -> freeze diff/source digest
  -> test verifier + code reviewer in parallel
  -> optional security/adversarial reviewer
  -> capture
```

Mandatory properties:

- implementer is the only writer;
- reviewer cannot repair in the same invocation;
- test verifier records exact commands and not-run gaps;
- all reviews bind to the current source digest.

### parallel-audit

Use when:

- task is read-only;
- multiple independent failure modes exist.

Shape:

```text
surface mapper
  -> correctness reviewer
  -> security reviewer
  -> adversarial reviewer
  -> synthesis
  -> capture
```

Mandatory properties:

- max writers: 0;
- remediation is a separate run;
- every finding must cite evidence;
- synthesis deduplicates but does not erase minority concerns without reason.

### cross-harness-review

Use when:

- medium/high-risk change;
- two native harnesses are available;
- independent review is worth the cost.

Shape:

```text
Harness A implements -> freeze digest -> Harness B blind-first reviews
  -> adjudication -> capture
```

Mandatory properties:

- reviewer sees acceptance claims and exact diff before implementer rationale;
- harness identity is recorded as observed, unknown, or unverified;
- different harness is a review-independence signal, not proof of correctness.

### migration-team

Use when:

- two independent workstreams;
- stable shared interface;
- low shared-file ratio;
- worktree isolation is available.

Shape:

```text
mapper/interface contract
  -> writer A + writer B in isolated worktrees
  -> integration owner
  -> test verifier
  -> independent reviewer
  -> capture
```

Mandatory properties:

- start with two writers, not an unbounded swarm;
- one integration owner;
- stable interface contract before fan-out;
- rollback strategy before writes.

## Roles

Every role must define:

- purpose;
- when to use;
- when not to use;
- allowed tools;
- allowed MCP servers;
- forbidden tools;
- context policy;
- output schema;
- evidence obligations;
- trust boundary;
- stop rules.

### lead

Purpose:

- select profile;
- restate acceptance claims and falsifiers;
- assign ownership;
- freeze interfaces;
- adjudicate conflicts;
- request capture.

Allowed:

- read/search;
- status;
- spawn/delegate only through an approved profile;
- no direct product writes unless acting as the single writer in
  `direct-small-fix`.

Forbidden:

- approving own risky side effects;
- hiding unsupported controls;
- treating consensus as completion.

### planner

Purpose:

- produce workflow/run contracts;
- identify phases, workers, gates, budgets, and evidence.

Allowed:

- read/search;
- plan rendering;
- no source edits.

Forbidden:

- implementation;
- claiming execution evidence.

### explorer

Purpose:

- map local code, symbols, tests, runtime state, and ownership.

Recommended toolbelt:

- filesystem read;
- text search;
- file glob;
- codegraph when available;
- LSP when symbol-level precision matters;
- ast-grep for structural searches.

Forbidden:

- edit/apply_patch/write;
- network unless explicitly upgraded for a repo-dependent reason;
- browser/computer use;
- final review.

Output:

- source map;
- entry points;
- relevant files;
- symbol/test references;
- assumptions;
- unresolved questions;
- recommended routing.

### librarian

Purpose:

- external documentation, upstream library behavior, and official-source
  verification.

Recommended toolbelt:

- context7;
- fetch/web;
- grep_app or GitHub source search;
- no local product write.

Forbidden:

- editing local source;
- relying on stale snippets without source fetch;
- replacing local codebase exploration.

Output:

- source-backed research with URLs, versions, and uncertainty.

### implementer

Purpose:

- make the smallest correct change inside one owned region.

Recommended toolbelt:

- read/search;
- apply_patch/edit;
- shell for tests and build commands;
- LSP rename only when supported and scoped;
- no broad web unless explicitly delegated.

Forbidden:

- editing outside ownership;
- approving own change;
- writing observer-owned evidence paths;
- widening public APIs or dependencies without gates;
- repair outside assigned findings.

Output:

- changed files;
- commands run;
- verification output;
- blockers;
- self-reported claims.

### test-verifier

Purpose:

- run or review focused checks without repairing source in the same invocation.

Recommended toolbelt:

- shell/test runner;
- browser or curl when the surface requires it;
- read logs/artifacts.

Forbidden:

- source edits;
- replacing failing checks with weaker checks;
- treating skipped checks as pass.

Output:

- exact command;
- cwd;
- source snapshot;
- pass/fail/not-run;
- artifact refs;
- coverage gaps.

### code-reviewer

Purpose:

- blind-first review of correctness, regressions, missing tests, and contract
  drift.

Recommended toolbelt:

- read;
- diff;
- test logs;
- LSP diagnostics;
- no edit.

Forbidden:

- repairing own findings;
- style-only noise;
- reviewing stale diff;
- trusting implementer rationale before initial findings.

Output:

- findings by severity;
- file/path/symbol;
- concrete failure;
- reproduction/evidence;
- disposition.

### security-reviewer

Purpose:

- review auth/authz, secrets, parser/eval, network boundaries, storage,
  dependencies, destructive actions, and deployment risks.

Recommended toolbelt:

- read;
- diff;
- dependency metadata;
- static search;
- no edit.

Forbidden:

- broad security theater when no sensitive surface is present;
- inventing risk without exploit preconditions;
- approving deployment gates.

### adversarial-reviewer

Purpose:

- challenge concurrency, stale state, rollback, partial failure, alternate
  platform/config, timeout paths, compatibility, and untested claims.

Recommended toolbelt:

- read;
- targeted command/test inspection;
- artifact comparison;
- no edit.

Forbidden:

- duplicating ordinary code review;
- adding unbounded speculative branches.

### qa-executor

Purpose:

- execute user-visible scenarios and record artifacts.

Recommended toolbelt:

- browser automation;
- curl;
- tmux transcripts;
- screenshots;
- CLI invocation.

Forbidden:

- product source edits;
- inferred pass;
- not_applicable pass.

## Toolbelt Compiler

The key product feature is the toolbelt compiler. It turns abstract roles into
concrete, minimal, harness-specific tool surfaces.

Input:

```json
{
  "profile": "feature-pipeline",
  "role": "explorer",
  "harness": "codex",
  "task": {
    "surface": "repo",
    "languages": ["python", "typescript"],
    "needs_external_docs": false,
    "needs_browser": false,
    "risk_codes": ["code-change"]
  }
}
```

Output:

```json
{
  "allowed_tools": ["read", "search", "glob"],
  "allowed_mcp": ["codegraph", "lsp"],
  "forbidden_tools": ["edit", "apply_patch", "write", "browser", "network"],
  "context_policy": "local-code-only",
  "output_schema": "source-map-v1",
  "evidence_obligations": [
    "files_inspected",
    "symbols_checked",
    "tests_identified",
    "open_questions"
  ]
}
```

Rules:

1. Start from no tools.
2. Add only tools required by the role and task surface.
3. Prefer read-only tools for planning, exploration, review, and QA setup.
4. Give write tools only to a designated writer.
5. Give network/web tools only to librarian or explicitly upgraded roles.
6. Give browser/computer tools only to QA or UI-focused verification.
7. Hide disabled tools from the model where the harness supports it.
8. If the harness cannot hide a forbidden tool, record it as
   `approximated` or `unsupported-critical` in the compile report.
9. Never rely on prompt text alone when runtime filtering is available.
10. Tool name collisions must be resolved by server-prefixed names or explicit
    adapter mapping.

## MCP Allocation

Recommended default MCP allocation:

| Role | MCP | Reason |
|---|---|---|
| explorer | `codegraph`, `lsp` | local structure, symbols, references |
| planner | `codegraph` optional | plan from repo topology only when useful |
| librarian | `context7`, `grep_app`, fetch/web | external docs and source-backed research |
| implementer | none by default, `lsp` optional | avoid tool overload during edits |
| test-verifier | none by default | tests should be explicit shell/browser/curl |
| code-reviewer | `lsp` optional | diagnostics and references |
| security-reviewer | dependency/static search optional | sensitive-surface inspection |
| adversarial-reviewer | none by default | reduce speculative tool sprawl |
| qa-executor | browser/curl/computer tools, not codegraph | surface verification |

Every MCP server must declare:

- purpose;
- allowed roles;
- allowed tool names;
- forbidden tool names;
- startup cost;
- timeout;
- cache policy;
- failure behavior;
- whether failures are model-visible or hard errors.

## Context Policy

World-class agent behavior depends as much on context restriction as on prompt
quality.

Policies:

- `local-code-only`: repo files, symbols, tests, local docs; no web.
- `external-docs-only`: official docs, source permalinks, versioned APIs; no
  local edits.
- `diff-review-only`: acceptance claims, exact diff, source digest, test
  receipts; implementer rationale withheld until first findings.
- `qa-surface-only`: URL/CLI/surface, expected behavior, credentials/gates if
  approved; no implementation rationale unless needed.
- `repair-only`: accepted findings, exact ownership, failing evidence, allowed
  files; no unrelated refactor context.
- `integration-only`: interface contract, writer outputs, merge base, fan-in
  tests, rollback plan.

Context must be loaded by policy and task, not by dumping every available
instruction into every agent.

## Harness Adapters

Adapters translate the same role/toolbelt contract into native harness
configuration.

### Codex adapter

Responsibilities:

- create role instructions;
- pass tool constraints when supported;
- configure working directory and sandbox;
- compile role output schema;
- capture command logs, git diff, touched files, test logs, and self-report.

Open issue:

- if Codex exposes broad built-in tools that cannot be hidden per subagent, the
  adapter must mark forbidden tools as prompt-enforced approximations.

### Claude Code adapter

Responsibilities:

- generate role instructions or agent pack entries;
- express tool restrictions through native config where available;
- support blind-first review by controlling input order;
- capture transcripts and artifacts without treating them as seals.

Open issue:

- exact managed-agent and local Claude Code capabilities may vary by account,
  beta surface, and client version. Capability snapshots are required.

### OpenCode/OMO adapter

Responsibilities:

- compile OMO-compatible role prompts and model categories;
- map MCP availability to role toolbelts;
- disable or avoid broad hooks where they conflict with Depone evidence
  policy;
- preserve OMO's useful planner/explorer/reviewer patterns without importing
  uncontrolled autonomous loops.

Open issue:

- current OMO-style setups often register MCP globally and rely on prompts for
  role separation. V107 requires a compile report stating whether hard
  filtering was enforced, approximated, or unsupported.

### Shell/fixture adapter

Responsibilities:

- deterministic self-tests and CI;
- no model dependency;
- validate contracts, fixtures, and failure cases.

## Compile Report

Every adapter compilation must emit a report:

```json
{
  "schema_version": "1.0",
  "target": "codex",
  "profile": "feature-pipeline",
  "roles": [
    {
      "role": "explorer",
      "toolbelt_status": "exact",
      "unsupported_critical": [],
      "approximations": []
    },
    {
      "role": "code-reviewer",
      "toolbelt_status": "approximated",
      "unsupported_critical": [],
      "approximations": [
        "write tools hidden by instruction, not runtime allowlist"
      ]
    }
  ],
  "decision": "compile-with-approximations"
}
```

Decision values:

- `compile-exact`;
- `compile-with-approximations`;
- `blocked-unsupported-critical`.

Unsupported critical controls must block execution when they affect secrets,
destructive actions, production deployment, database migration, external
messaging, or reviewer write access.

## Evidence Bridge

Agent Fabric outputs are self-reports until Depone Capture observes or
imports evidence.

Minimum artifacts per invocation:

- `agent-result.json`;
- `source-snapshot.json`;
- `toolbelt.json`;
- `compile-report.json`;
- `command-receipts.jsonl` when commands run;
- `git-diff.patch` and `git-diff-name-only.txt` when source changes;
- `test-output.log` or explicit not-run reason;
- `review-report.md` for reviewers;
- `qa-artifacts/` for visible surface checks.

Depone must decide:

- `pass`;
- `fail`;
- `inconclusive`.

Depone must also label assurance:

- `A0-claims-only`;
- `A1-local-observed`;
- `A2-isolated-observed`;
- `A3-externally-attested`.

No agent may upgrade assurance. No agent may write authoritative seals.

## Safety Gates

Risk gates are required for:

- source writes;
- shell execution;
- network access;
- browser/computer use with authenticated accounts;
- dependency installation;
- secret access;
- external messaging;
- database migrations;
- production deployment;
- destructive operations;
- history rewrite;
- public publishing;
- cost-increasing model/provider changes.

Safe default:

- stop;
- preserve artifacts;
- emit a blocked decision;
- request human or external policy approval.

## Failure Modes And Countermeasures

### Tool overload

Failure:

- every agent sees every MCP/tool;
- model wastes context and misselects tools.

Countermeasure:

- hard allowlists where supported;
- dynamic MCP filtering;
- compile-report approximation when only prompt control exists.

### Prompt-only security

Failure:

- reviewer is told not to edit, but edit tools remain callable.

Countermeasure:

- runtime tool hiding or sandbox restriction;
- prompt-only restriction marked `approximated`;
- critical restrictions marked blocking when not enforceable.

### Agent evidence forgery

Failure:

- agent writes logs, seals, approvals, or final decision.

Countermeasure:

- deterministic capture owns authoritative evidence;
- agent self-reports stay `A0` until observed/imported.

### Over-orchestration

Failure:

- small tasks are routed through unnecessary teams.

Countermeasure:

- direct execution default;
- activation thresholds;
- profile retirement when measured benefit is absent.

### Parallel writer conflict

Failure:

- multiple writers edit coupled files or unstable interfaces.

Countermeasure:

- one active writer by default;
- migration team only after stable interface and disjoint ownership;
- integration owner and rollback plan.

### Stale review

Failure:

- reviewer approves a diff that changed after review.

Countermeasure:

- source/diff digest binding;
- stale review invalidates pass.

### Harness capability drift

Failure:

- a target harness changes tool, MCP, or permission behavior.

Countermeasure:

- capability snapshots;
- adapter smoke tests;
- compile reports;
- versioned support matrix.

### Public overclaim

Failure:

- docs claim productivity, quality, or superiority without paired evidence.

Countermeasure:

- paired dogfood requirement;
- public claims blocked until promotion evidence and human review.

## Evaluation Plan

Agent Fabric must prove value by task class, not globally.

Evaluation arms:

- direct Codex;
- Codex through Agent Fabric + Depone;
- direct Claude Code;
- Claude Code through Agent Fabric + Depone;
- OpenCode/OMO through Agent Fabric + Depone when isolated.

Task classes:

- localized bug fix;
- auth/permission audit;
- docs-code consistency;
- UI/render regression;
- multi-file migration;
- cross-harness review.

Metrics:

- escaped defects;
- review precision;
- missing evidence rate;
- unsupported critical controls;
- human interventions;
- elapsed time;
- token/tool-call cost where observable;
- file-scope drift;
- false-pass rate;
- user-useful completion rate.

Rules:

- keep inconclusive separate from pass;
- do not promote a profile that only adds ceremony;
- retire roles or profiles with no measured value;
- direct baseline remains valid for small tasks.

## Implementation Roadmap

### Implementation Status As Of V112

Implemented:

- V107 contract validators for role, toolbelt, profile, harness capability,
  compile report, invocation packet, and agent result self-report.
- `compile_agent_fabric(...)`, including exact, approximated, and
  `blocked-unsupported-critical` decisions.
- V108 fixture-only shell reference adapter output shape.
- V109 passive Depone capture manifest bridge with A0/A1 assurance labels.
- V110 verification report assurance fields from capture manifests.
- V111 deterministic operator Markdown view/export path.
- V112 source-only lifecycle smoke across the V107-V111 path.

Still deferred:

- live Codex, Claude Code, and OpenCode/OMO adapter execution;
- hard per-harness tool hiding claims without capability evidence;
- profile routing from arbitrary goals;
- paired direct-vs-governed dogfood evaluation;
- public benefit, quality, speed, or superiority claims.

### Phase 0: Spec freeze

Completed by the original V107 direction/spec slice.

Exit:

- V107 spec and decision exist;
- no code behavior changes;
- contract checks pass.

### Phase 1: Contract schemas

Status: implemented in V107.

Add schemas for:

- role;
- toolbelt;
- profile;
- harness capability;
- compile report;
- invocation packet;
- agent result.

Exit:

- fixture validation covers positive and negative cases;
- reviewer write access is blocked;
- undeclared MCP is blocked;
- missing evidence obligation is blocked.

### Phase 2: Toolbelt compiler MVP

Status: implemented in V107 for deterministic profile-role compilation.

Implement deterministic compiler:

```text
profile + role + task surface + harness capability -> toolbelt + compile report
```

Exit:

- exact/approximated/unsupported-critical decisions are deterministic;
- fixtures cover Codex, Claude Code, OpenCode/OMO, and shell capabilities.

### Phase 3: Harness adapter reference

Status: partially implemented by the V108 fixture-only shell reference adapter;
live Codex adapter behavior remains deferred.

Add first reference adapter for local Codex.

Exit:

- compiles `feature-pipeline` and `parallel-audit`;
- captures self-report, diff, touched files, and test output;
- cannot claim hard tool hiding unless proven.

### Phase 4: Claude and OpenCode/OMO adapters

Add reference adapters after capability snapshots.

Exit:

- cross-harness review can be represented;
- OMO global-MCP approximation is explicit;
- unsupported critical controls block.

### Phase 5: Depone capture bridge

Status: implemented for passive fixture/capture/report/operator-view flow in
V109-V112; live adapter capture remains deferred.

Connect adapter outputs to Depone evidence manifests and assurance labels.

Exit:

- valid local capture reaches `A1-local-observed`;
- tamper/missing/stale/extra-file cases fail closed;
- agent self-report alone remains `A0-claims-only`.

### Phase 6: Paired dogfood

Run direct vs governed profile comparisons.

Exit:

- raw paired results exist;
- negative controls route direct;
- no public benefit claim without evidence;
- profile retirement rules applied.

## Downstream Implementation Prompt

Use this prompt to start the implementation in a separate working context:

```text
You are implementing Depone Agent Fabric V107.

Goal:
Build the first deterministic contract layer for a world-class agent system
that runs with Depone. Do not turn Depone Core into an agent runtime.
Depone owns contracts, evidence, decision, and assurance. Agent Fabric owns
profile routing, role/toolbelt compilation, harness adapter lowering, and
handoff of captured artifacts back to Depone.

Non-goals:
- Do not call live models in the first implementation slice.
- Do not add API keys, provider routing, exact model IDs, or global user config.
- Do not implement a dashboard.
- Do not claim productivity, quality, or superiority.
- Do not let agents write authoritative evidence, approvals, seals, or final
  decisions.
- Do not rely on prompt-only restrictions when a hard tool allowlist is
  available.

First slice:
1. Add JSON schemas for:
   - role contract;
   - toolbelt contract;
   - harness capability snapshot;
   - compile report;
   - agent invocation packet;
   - agent result self-report.
2. Add deterministic fixtures for:
   - explorer with codegraph+lsp read-only tools;
   - librarian with context7+grep_app+fetch and no local writes;
   - implementer with edit/test tools and no broad web by default;
   - reviewer with read/diff/test-log tools and no write tools;
   - OpenCode/OMO capability where MCP is global and therefore marked
     approximated unless hard filtering is proven.
3. Add a validator command that rejects:
   - reviewer write tools;
   - undeclared MCP tools;
   - missing output schema;
   - missing evidence obligations;
   - unsupported critical controls mislabeled as safe;
   - agents allowed to write observer-owned evidence paths.
4. Add no live execution. Use fixture capabilities only.
5. Update docs with the exact command and fixture evidence.

Required verification:
- Run the new validator self-test.
- Run `python scripts/check_contract.py --tier changed`.
- Run `git diff --check`.
- Run a secret scan over changed files.

Completion:
Open a PR that states this is contract-only and does not yet prove agent
quality. The PR must list unsupported controls, approximations, and the next
adapter slice.
```

## Spec Self-Review

### Resolved gaps

- Separates Depone Core from Agent Fabric.
- Keeps direct execution as the default.
- Defines role-specific tool/MCP allocation.
- Requires concrete toolbelts instead of broad abstract tool labels.
- Requires compile reports for exact, approximated, and unsupported-critical
  mappings.
- Keeps agent outputs self-reported until deterministic capture observes them.
- Preserves assurance levels.
- Requires paired evaluation before public benefit claims.
- Handles OpenCode/OMO global-MCP behavior as an approximation unless hard
  filtering is proven.
- Blocks reviewer-write and evidence-curator trust failures.

### Remaining open questions

- Exact Codex per-subagent tool hiding support must be capability-tested.
- Exact Claude Code managed-agent/local tool restriction support must be
  capability-tested.
- Exact OpenCode/OMO per-agent MCP filtering support must be capability-tested.
- Whether Agent Fabric lives in this repo or a sibling repo should be decided
  after Phase 1 contract schemas.
- Whether profile routing is deterministic, model-assisted, or hybrid should
  be deferred until paired dogfood fixtures exist.

### Safe defaults for open questions

- Unknown hard restriction support is `approximated`, not exact.
- Unknown critical restriction support is `blocked-unsupported-critical`.
- Unknown harness identity is `unknown`, not independent.
- Unknown review freshness is stale.
- Unknown evidence origin is `A0-claims-only`.

## Original Acceptance Criteria

- V107 spec exists and captures the complete product direction.
- V107 decision exists and explicitly recorded the original direction-only PR.
- Later V107 implementation adds contract/compiler behavior only; it still does
  not call live models or claim agent quality.
- No agent pack is claimed production-ready.
- Existing contract verification still passes.
