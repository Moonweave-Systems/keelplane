# V105 Final Adoption Plan

Status: proposed execution plan
Date: 2026-06-23

## Purpose

This plan turns `keelplane-v105-final/` from a reviewed design bundle into an
ordered Keelplane adoption path. The adoption target is not a broader agent
runtime. The target is a policy/evidence control plane that can say, with an
explicit assurance limit, whether an AI coding run satisfied declared evidence
policy.

The central rule is unchanged: agent output is a claim. Deterministic capture,
origin-aware evidence, independent review, and verifier policy decide whether a
claim is supported, refuted, stale, or unevaluated.

## Re-Review Summary

The full bundle was reviewed, including the audit, final review, product
direction, threat model, evidence protocol, team spec, evaluation spec,
implementation roadmap, ADRs, integration guide, upstream gap map, ecosystem
positioning, examples, profiles, schemas, tools, tests, and native Codex/Claude
packs.

The direction is sound. The bundle corrects the main product risk in earlier
Keelplane work: confusing orchestration activity with trust. Keelplane should not
compete with Codex, Claude Code, LangGraph, Conductor, CI, OpenTelemetry, or
Sigstore. Keelplane should own the portable contract, evidence normalization,
claim policy, decision, assurance, and human-readable explanation.

The current repo already has a useful trust wedge: V105 verifies evidence-contract
bundles from logs, diffs, touched-file lists, exit codes, and root control files;
V106 lifts selected V105 cases into a gated `wave-1` receipt. That proves part of
the thesis, but it is not yet the full V105-final product direction.

## Product Boundary

Keelplane Core is deterministic. It validates plans, evaluates evidence policy,
and renders decision plus assurance. It must not call a model or become a general
model loop.

Keelplane Capture observes or imports execution facts. A1 local capture can prove
post-capture byte integrity under local-machine assumptions, but it cannot prove
provider identity, command process custody, or resistance to a malicious local
administrator.

Keelplane Runner is optional and later. If it exists, it launches external native
harnesses under a run contract and owns process/workspace/log custody. It still
does not own model reasoning, provider authentication, or native tool behavior.

Native harnesses such as Codex and Claude Code remain responsible for model
execution, tools, sessions, permission prompts, sandboxing, worktrees, and native
transcripts.

Reference packs are downstream consumers. They are not the trust root.

## Non-Goals

- Do not build a new model runtime or provider router.
- Do not start with a dashboard.
- Do not add more agent personas before evidence shows value.
- Do not claim productivity, quality, or superiority before paired evaluation.
- Do not treat hash integrity as provider or command authenticity.
- Do not let agents write authoritative manifests, ledgers, seals, approvals, or
  final decisions.
- Do not add runtime dependencies to core/reference scripts without explicit
  approval.

## Execution Principles

1. Stop semantic false-pass first.
2. Harden discovery before manifest or seal work.
3. Add evidence manifests and A1 capture before native packs.
4. Keep native packs reference-only until policy/evidence semantics exist.
5. Lower to native harnesses with capability reports, not bijection claims.
6. Run paired dogfood before changing activation defaults or making product
   benefit claims.

## Phase Plan

### Phase 1: Semantic Safety Contract

Goal: prevent required claims or adversarial checks from passing when no real
evaluator exists.

Work:

- Add or identify regression fixtures where a required claim has an apparent
  ground-truth path but no evaluator result.
- Introduce authoritative `decision`: `pass`, `fail`, `inconclusive`.
- Introduce explicit `assurance`: `A0-claims-only`, `A1-local-observed`,
  `A2-isolated-observed`, `A3-externally-attested`.
- Keep legacy `verified`, `refuted`, and `insufficient-evidence` only as
  compatibility rendering.

Exit gate:

- Missing evaluator yields `inconclusive`, never `pass`.
- Refuted required evidence yields `fail`.
- Existing V105 and V106 self-tests still pass.
- `python scripts/check_contract.py --tier changed` passes.

### Phase 2: Safe Discovery Contract

Goal: make generic evidence discovery safe enough to feed manifests.

Work:

- Replace whole-file default loading with metadata-first streaming hashes.
- Add path containment, symlink rejection, special-file rejection, collision
  detection, depth limits, file-count limits, per-file limits, and total-byte
  limits.
- Make content capture allowlisted rather than default.

Exit gate:

- Fixtures reject path traversal, symlinks, sockets/FIFOs/devices, Unicode/case
  collisions, oversized files, and excessive depth.
- Binary files are not expanded to hex by default.
- Unsafe evidence cannot satisfy policy.

### Phase 3: Evidence Manifest V1 And A1 Capture

Goal: add the first useful vertical loop around local evidence.

Work:

- Add manifest, command receipt, review, gate event, run contract, compile report,
  event, seal, and team-profile schema fixtures as package-owned contracts.
- Implement or migrate A1 local capture from the bundle as repo-native tooling.
- Add ledger and seal verification.
- Add a report skeleton that separates decision from assurance.

Exit gate:

- Tamper, extra-file, missing-file, duplicate-ledger, and manifest/seal mismatch
  fixtures fail closed.
- Valid local capture produces `A1-local-observed` with explicit limitations.
- Passive verification does not execute artifact-provided commands.

### Phase 4: Reference Native Pack

Goal: provide Codex/Claude reference agents and profiles only after trust
semantics exist.

Work:

- Add profiles such as `direct-small-fix`, `feature-pipeline`, `parallel-audit`,
  `cross-harness-review`, and `migration-team` as reference artifacts.
- Add project-scoped Codex and Claude agent packs without exact model IDs, API
  keys, provider routes, global settings, third-party MCP servers, or permission
  bypasses.
- Add a non-destructive installer or validation path only if it fits the current
  repo dependency rules.

Exit gate:

- Packs validate structurally.
- Agent outputs are self-reported by contract.
- Agents cannot write observer-owned evidence paths.
- Claude Agent Teams remains opt-in and experimental.

### Phase 5: Native Lowering Contracts

Goal: compile Keelplane policy/evidence expectations into native runbooks without
pretending the mapping is lossless.

Work:

- Add capability snapshots for native harness targets.
- Add `compile-report.json` with `exact`, `approximated`,
  `omitted-noncritical`, and `unsupported-critical` classifications.
- Add run-contract fixtures that bind plan hash, target, profile, workers,
  required claims, gates, budgets, and compile report digest.

Exit gate:

- Unsupported critical controls block the compile result.
- Approximation is visible in the report.
- Generated run contracts validate deterministically.

### Phase 6: Paired Dogfood Evaluation

Goal: prove or narrow the profile value before claiming product benefits.

Work:

- Run paired direct-vs-profile tasks on frozen task fixtures.
- Record base commit, treatment, profile/pack hash, harness version when
  observable, hidden check result, human interventions, reviewer findings,
  invocations, timing, and abort reasons.
- Keep inconclusive separate from pass.

Exit gate:

- Raw paired results exist.
- Negative controls route direct.
- Unhelpful roles are removed or narrowed.
- No public productivity or quality claim is made without adequate evidence.

## Worker Model

The first phase should be executed as a small direct coding slice. Later phases
may use subagents, but only with explicit ownership and current-snapshot
handoffs.

Workers:

- semantic-safety worker: verifier semantics and false-pass fixtures;
- discovery worker: safe filesystem/evidence discovery;
- evidence worker: manifest, ledger, seal, capture, report skeleton;
- native-pack worker: reference profiles, agent packs, installer boundaries;
- lowering worker: capability reports and run contracts;
- evaluation worker: paired dogfood records and activation recommendations;
- documentation worker: gap ledger, risk register, and final adoption report.

No worker may approve its own risky side effects or write authoritative evidence
paths unless it is the deterministic capture/seal tool being tested.

## Handoffs

Each phase must produce a small receipt-like handoff:

- Phase 1: false-pass fixture IDs, expected decisions, actual decisions, command
  output.
- Phase 2: unsafe-path rejection matrix and accepted safe discovery examples.
- Phase 3: manifest/seal examples, tamper failure receipts, report skeleton.
- Phase 4: profile inventory, pack validation result, installer dry-run receipt.
- Phase 5: capability report examples and run-contract validation output.
- Phase 6: paired evaluation table and activation recommendation.

## Parallelism

Early phases are intentionally mostly sequential. Semantic safety and safe
discovery are prerequisites for trustworthy manifests.

Allowed parallelism:

- after Phase 3, reference-pack drafting and documentation drafting may run in
  parallel;
- read-only review can run in parallel with focused QA after each implementation
  slice;
- paired dogfood runs can fan out only after the evaluation task corpus is frozen.

Forbidden parallelism:

- parallel writers before interfaces and ownership are frozen;
- same-file writers;
- native pack or dashboard work before evidence semantics exist.

## Verification Gates

Run after every implementation slice:

```bash
python scripts/check_contract.py --tier changed
python scripts/dwm.py doctor
```

Run when the relevant files change:

```bash
python scripts/v105_verify_wedge.py --self-test
python scripts/v106_multi_wave.py --self-test
python -m keelplane validate --self-test
python scripts/check_readme_quality.py README.md
git diff --check
```

Run before claiming full adoption:

```bash
python scripts/check_contract.py
```

If the local Bash wrapper is blocked by the missing guard hook, use the already
established tmux/log workaround and record the exact status/output files.

## Risk Gates

| Gate | Safe Default | Trigger |
|---|---|---|
| Semantic false pass | return inconclusive | required claim lacks evaluator |
| Unsafe discovery | reject metadata/content | path escape, symlink, special file, collision, oversize |
| Evidence trust | fail closed | seal, ledger, manifest, or digest mismatch |
| Dependency | stop and ask | new runtime dependency needed |
| Native pack | reference-only | pack implies runtime authority or productivity benefit |
| External side effect | stop and ask | network, deployment, database, secret, paid API, messaging |
| Git history | stop and ask | commit, amend, reset, rebase, push, force-push |

## Budget

- Phase size: one PR-sized semantic unit.
- First slice: one verifier/test surface only.
- Runtime dependencies: zero new core/reference runtime dependencies.
- Concurrency: maximum two implementation workers only after Phase 3, and only on
  disjoint reference/docs surfaces.
- Claims: no superiority or productivity claims until Phase 6.

## Resume Plan

Resume from the last phase with a passing gate. Do not rerun earlier phases
unless their inputs changed.

Cached artifacts:

- fixture names and expected decisions;
- command output/status logs;
- manifest/seal examples;
- risk register rows;
- paired evaluation rows;
- final adoption docs.

Invalidators:

- verifier semantics change;
- generic discovery behavior change;
- schema version change;
- native pack format change;
- task corpus or baseline change.

## First Slice

Implement only Phase 1 first.

Instruction:

> Add regression coverage proving that a required claim or adversarial item with
> no evaluator cannot pass, then make the smallest verifier change so the result
> is `inconclusive` with explicit assurance rather than `pass`.

Inputs:

- repository path;
- `docs/v105-verify-wedge-spec.md`;
- `docs/v106-multi-wave-spec.md`;
- `keelplane-v105-final/docs/product-direction-v105.md`;
- `keelplane-v105-final/docs/evidence-protocol-v1.md`;
- `keelplane-v105-final/docs/upstream-gap-map.md`.

Expected output:

- failing fixture before fix;
- minimal verifier change;
- passing changed-tier contract;
- short first-slice report.

Forbidden actions:

- agent pack import;
- dashboard work;
- native runner work;
- dependency installation;
- productivity claims;
- git history rewrite.

## Documentation Artifacts To Add During Adoption

Recommended future docs:

- `docs/v107-semantic-safety-spec.md`
- `docs/v108-safe-discovery-spec.md`
- `docs/v109-evidence-manifest-spec.md`
- `docs/v110-reference-native-pack-spec.md`
- `docs/v111-native-lowering-spec.md`
- `docs/v112-paired-dogfood-spec.md`

This document is the umbrella adoption plan. Each phase spec should include its
own fixtures, command contract, decision record, and explicit limitations.

## Final Success Criteria

The adoption is complete only when:

- missing evaluator cannot produce pass;
- unsafe discovery cannot become trusted evidence;
- A1 local capture can produce and verify manifest/ledger/seal artifacts;
- reports separate decision and assurance;
- native packs are reference consumers, not trust authorities;
- paired dogfood exists before any productivity/quality claim;
- all relevant contract checks pass;
- limitations are documented without marketing overclaim.
