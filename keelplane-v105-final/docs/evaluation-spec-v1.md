# Keelplane Agent Profile Evaluation Specification v1

Status: Proposed
Date: 2026-06-23

## 1. Objective

Determine whether a Keelplane profile improves real engineering outcomes enough
to justify coordination overhead. This is not a model leaderboard.

## 2. Questions

1. Does the profile improve accepted completion?
2. Does it reduce escaped defects or human correction?
3. Does fresh/cross-harness review find real issues with acceptable precision?
4. Does the verifier avoid false pass and false fail?
5. What wall-time/invocation overhead is introduced?
6. Which tasks should downgrade to direct execution?

## 3. Arms

- `codex-direct`;
- `codex-keelplane-profile`;
- `claude-direct`;
- `claude-keelplane-profile`;
- optional cross-harness implementation/review arm.

Baseline receives the same objective, repository guidance, and acceptance
criteria, but no Keelplane team decomposition.

## 4. Task corpus

Use versioned tasks with hidden checks:

1. localized bug fix;
2. cross-layer feature;
3. failing-test/root-cause diagnosis;
4. read-only security audit;
5. multi-module migration;
6. concurrency/stale-state defect;
7. compatibility/documentation check;
8. negative control that should route direct.

Each task records base commit, setup/environment digest, visible prompt, hidden
checks/rubric, risk class, profile eligibility, disallowed shortcuts, and task
hash. Freeze tasks before comparison.

## 5. Design

Preferred: paired randomized crossover.

- Same base commit for both treatments.
- Randomize treatment order.
- Fresh sessions/worktrees.
- Prevent one arm from seeing the other.
- Repeat enough to expose stochastic variation.
- Record pack/prompt/harness/tool versions.

For small dogfood, publish raw paired results rather than statistical claims.

## 6. Primary metrics

### Correctness

- hidden checks passed;
- maintainer acceptance;
- completion;
- escaped defects/regressions;
- confirmed security findings.

### Human effort

- active human minutes;
- steering interventions;
- manual corrections;
- adjudication time;
- merge-conflict resolution time.

### Workflow overhead

- wall-clock time;
- invocations/retries;
- files touched/churn;
- handoffs and coordination events;
- subscription limit events when observable.

### Verification quality

- false pass;
- false fail;
- inconclusive rate;
- stale-review detection;
- gate-replay detection;
- seal-tamper detection;
- evidence completeness.

### Review quality

- true/false positive findings;
- missed defects;
- severity calibration;
- duplicate rate;
- time to actionable finding.

## 7. Initial internal keep gates

For `feature-pipeline`:

- accepted completion is not worse than direct on medium tasks;
- escaped defects or human corrections improve on target classes;
- verifier false-pass remains below a predeclared threshold;
- median wall-time overhead remains within chosen tolerance;
- negative controls route direct;
- at least 80% of adjudicated reviewer findings are actionable/correct.

Predeclare exact thresholds before running. These are product gates, not
universal scientific standards.

## 8. Profile hypotheses

- `direct-small-fix`: team should not help enough; expected downgrade.
- `feature-pipeline`: exploration + fresh review should reduce rework/defects.
- `parallel-audit`: specialized read-only review should increase confirmed
  finding coverage but may add duplicates/false positives.
- `cross-harness-review`: diversity should reduce correlated blind spots.
- `migration-team`: parallel writers should reduce time only with stable
  interfaces and strong fan-in.

## 9. Run record

Preserve task/treatment IDs, base commit, harness/version, profile/pack hashes,
run contract, manifest/assurance, final subject digest, hidden-check result,
human intervention log, adjudicated findings, timing/invocations, and abort
reason.

## 10. Analysis rules

- Report paired task results, not averages alone.
- Separate task classes.
- Include failures and aborted runs.
- Never count inconclusive as pass.
- Report quality and cost together.
- Do not use readiness scores as productivity metrics.
- Preserve prompt/profile versions and disclose model/version changes.
- Do not cherry-pick traces.

## 11. Decisions

- **Keep:** repeatable quality/human-effort benefit with acceptable overhead.
- **Narrow:** benefit only on subset; tighten activation.
- **Simplify:** role adds overhead without independent value.
- **Remove:** no measurable benefit or safety regression.

## 12. First dogfood

Ten paired tasks: 3 localized/negative controls, 3 medium feature/bug, 2 audits,
2 migration/concurrency. This is an internal gate only; no broad superiority
claim from ten tasks.
