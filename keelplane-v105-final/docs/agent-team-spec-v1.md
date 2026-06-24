# Keelplane Native Agent Team Specification v1

Status: Proposed final draft
Date: 2026-06-23

## 1. Goal

Provide the smallest team shape that measurably improves implementation quality,
review independence, or context isolation. The team is a reference execution
profile, not Keelplane Core.

## 2. Non-goal

Do not simulate a company hierarchy, maximize agent count, or force every task
through planner/coder/tester/reviewer ceremony.

## 3. Rules

1. Direct execution is default.
2. Add a role only for a distinct decision/evidence product.
3. One active writer per ownership region.
4. Worktrees prevent file collisions, not semantic conflicts.
5. The author cannot be the sole reviewer.
6. Reviews bind to exact source/diff snapshots.
7. Prefer blind-first review before implementer rationale.
8. Missing evidence is inconclusive.
9. Agents produce self-reports; deterministic capture seals evidence.
10. Risky side effects require human/external policy approval.
11. Recursive spawning is disabled/depth-limited.
12. Profiles are retired when measured benefit is absent.

## 4. Activation

| Factor | Team signal | Direct/pipeline signal |
|---|---|---|
| independent workstreams | 2+ | 0–1 |
| shared-file ratio | low | high |
| interface stability | can freeze contract | changing rapidly |
| context isolation value | high | low |
| risk/diverse checks | multiple modes | one focused check |
| coordination cost | below expected benefit | likely dominant |

Routing:

- no independent stream: direct;
- one writer + separable checks: pipeline;
- read-only multi-angle work: parallel review;
- 2–3 disjoint writers + stable interface: team;
- same-file/tightly sequential work: never parallel writers.

## 5. Profiles

### Direct small fix

```text
main agent -> focused check -> fresh reviewer when warranted
```

### Feature pipeline (default nontrivial)

```text
lead
  -> explorer
  -> implementer
  -> test verifier + code reviewer
  -> conditional security/adversarial reviewer
  -> deterministic capture
```

### Parallel audit

```text
surface mapper
  -> correctness reviewer
  -> security reviewer
  -> performance/compatibility reviewer
  -> adversarial synthesis
```

All roles read-only; remediation is a new run.

### Cross-harness review

```text
Harness A implements
Harness B performs fresh blind-first review
Harness A or human adjudicates
Keelplane binds both to the same snapshot
```

Recommended for medium/high-risk work when both subscriptions are available.

### Migration team

```text
lead/integration owner
  -> mapper + interface contract
  -> writer A in worktree A
  -> writer B in worktree B
  -> integration owner
  -> test verifier
  -> independent reviewer
```

Start with two writers.

## 6. Roles

### Lead

Select profile, restate acceptance claims/falsifiers, assign ownership, freeze
shared interfaces, spawn only needed roles, reject unsupported claims,
adjudicate conflicts, request deterministic capture, report residual risk.

### Explorer

Read-only mapping. Return entry points, execution path, files/symbols/tests,
conventions, assumptions, unresolved questions, evidence refs, ownership
proposal, and recommended routing. Stop when implementer need not repeat broad
exploration.

### Implementer

Make the smallest change within one owned region. Inputs include objective,
claims, explorer handoff, write ownership, forbidden effects/gates, checks, and
source snapshot. Do not edit outside ownership, approve own change, or write
observer-owned evidence paths. Stop on interface ambiguity.

### Test verifier

Run/review focused checks without repairing source in the same invocation.
Record exact command, cwd, source snapshot, status, output refs, failures,
not-run checks, and coverage gaps. Test caches/build output may require
workspace-write; tracked source before/after must therefore be checked.

### Code reviewer

Blind-first sequence: acceptance claims -> exact diff/snapshot -> test receipts
-> findings -> optional rationale. Findings include severity, path/symbol,
concrete failure, evidence/reproduction, disposition. No style-only noise.

### Security reviewer

Trigger for auth/authz, secrets, parser/eval, network boundary, privacy/storage,
dependency/supply chain, destructive/database/deploy behavior. Return threat
surface, exploit preconditions, findings, missing tests, scope digest, verdict.

### Adversarial reviewer

Challenge concurrency, stale state, rollback, partial failure, alternate
platform/config, error/timeout paths, compatibility, and untested claims. Use
only when distinct from ordinary review.

## 7. Removed role: Evidence Curator

An agent may suggest references or write a self-report under staging. It may not
claim commands ran, upgrade origin, compute authoritative ledger, approve gates,
seal a run, or set final decision. Those belong to deterministic tools.

## 8. Ownership and integration

Writer assignment includes path/module boundary, consumed shared interfaces,
expected output, base snapshot, integration owner, and forbidden paths.

Parallel writer prerequisites:

1. stable interface contract;
2. disjoint ownership;
3. worktree/equivalent isolation;
4. deterministic fan-in checks;
5. integration owner;
6. rollback strategy.

Otherwise downgrade to sequential pipeline.

## 9. Handoff

Worker result conforms to `schemas/agent-result.schema.json` and records
run/attempt/invocation, role/harness, source snapshot, scope, status, claims,
artifact/command refs, blockers, and origin. It remains self-reported until
observed/imported under a stronger origin.

## 10. Review independence

Policy may require different invocation, fresh context, artifacts-only initial
input, different harness/model when observable, human review, and deterministic
checks. Review record stores every dimension as true/false/unknown; unknown is
not treated as independent.

## 11. Native mapping

| Role | Codex | Claude Code |
|---|---|---|
| explorer | `kp_explorer` | `kp-explorer` |
| implementer | `kp_implementer` | `kp-implementer` |
| isolated writer | native worktree/thread | `kp-worktree-implementer` |
| test verifier | `kp_test_verifier` | `kp-test-verifier` |
| code reviewer | `kp_reviewer` | `kp-code-reviewer` |
| security reviewer | `kp_security_reviewer` | `kp-security-reviewer` |
| adversarial reviewer | `kp_adversarial_reviewer` | `kp-adversarial-reviewer` |

Parent/runtime overrides may take precedence and must be reflected when
observable.

## 12. Parallelism and retry

Defaults: max four open threads, max two writers, no child recursive spawning,
one retry per role under unchanged scope. Retry gets a new invocation ID.
Changed scope/gate/snapshot requires reassignment.

## 13. Completion

Required handoffs exist; ownership holds; observed command receipts exist;
reviews match current digest; gates are action-bound/resolved; claims are
supported/refuted/inconclusive explicitly; deterministic capture creates valid
manifest/seal; lead reports residual risk. Consensus alone is not completion.

## 14. Retirement rule

Simplify or remove a profile when quality/human effort does not beat direct
baseline, escaped defects do not drop, overhead dominates, users ignore its
artifacts, or review precision is poor.
