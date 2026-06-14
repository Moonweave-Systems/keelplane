# V0 Fixture Smoke

Status: pass
Date: 2026-06-14

These records exercise the current `SKILL.md` contract against one
codebase-facing fixture and one non-code/meta fixture. They are not evidence that
the requested downstream work was executed; they only verify that the workflow
blueprint shape satisfies the v0 release contract.

## Fixture 1

Fixture type: codebase-facing
Local context inspected: not-needed

Prompt:

```text
Design a workflow to audit every API route for missing auth.
```

Selected patterns:

- Pipeline
- Parallel Fan-Out / Fan-In
- Adversarial Verify
- Human Gate

Generated workflow output:

- Objective: find API routes that lack required authorization checks.
- Surface: route files, middleware, auth helpers, route tests, and framework
  routing config.
- Assumptions: the repo has discoverable route definitions and auth conventions;
  verify by inspecting routing and middleware entry points before fan-out.
- Phases: route inventory, auth-rule extraction, per-route audit, independent
  refutation, dedupe, final report.
- Workers: inventory worker, per-surface auditors, adversarial verifier, fan-in
  reporter.
- Handoffs: route inventory table, finding records with file/line evidence,
  verifier decisions, final confirmed/refuted/unverified ledger.
- Parallelism: per-package or per-route-batch fan-out with a fixed concurrency
  cap; fan-in only after verifier output is complete.
- Verification: verifier attempts to disprove each missing-auth claim using route
  tests, middleware traces, and call-site evidence.
- Risk gates: read-only by default; ask before editing auth logic, changing
  public API behavior, adding dependencies, or touching secrets.
- Budget: cap batches, retry count, files per worker, and synthesis pass count.
- Resume: cache route inventory and per-batch ledgers by input hash.
- Execution path: direct Codex audit or subagent plan; no runtime required.
- Falsifiable verification: sample confirmed findings must be traceable to route
  definitions and must survive an independent verifier trying to find existing
  auth middleware, tests, or wrapper enforcement.
- Safe default: produce a read-only report and stop before edits.

Failed criteria: none
Resulting change: none
Overclaims execution: no

## Fixture 2

Fixture type: non-code/meta
Local context inspected: not-needed

Prompt:

```text
Stress-test three architecture options before we pick one.
```

Selected patterns:

- Judge Panel
- Adversarial Verify
- Human Gate
- Resume And Cache

Generated workflow output:

- Objective: compare three architecture options and expose decision risks before
  implementation.
- Surface: architecture notes, constraints, current system boundaries, quality
  attributes, and stakeholder success criteria.
- Assumptions: the options are comparable under a shared rubric; verify by
  extracting explicit constraints before judging.
- Phases: context intake, option normalization, independent option briefs,
  rubric scoring, adversarial challenge, synthesis.
- Workers: option advocates, judge, adversarial reviewer, synthesis writer.
- Handoffs: normalized option sheets, rubric scores, challenge notes, decision
  matrix, residual-risk ledger.
- Parallelism: one advocate per option, then a judge barrier, then verifier.
- Verification: adversarial reviewer tries to refute each high score and checks
  whether claimed tradeoffs follow from evidence.
- Risk gates: ask before committing to implementation, public API changes,
  migrations, dependency changes, production deploys, or paid external research.
- Budget: cap option count, review rounds, external lookups, and synthesis size.
- Resume: cache option sheets and rubric scores; rerun only changed options.
- Execution path: conversation blueprint or saved spec; plugin/runtime backlog
  only if repeated architecture tournaments become common.
- Falsifiable verification: each option score must cite a constraint or evidence
  source, and the adversarial reviewer must try to refute the top option's
  claimed strengths before synthesis.
- Safe default: stop at a decision report and ask before implementation.

Failed criteria: none
Resulting change: none
Overclaims execution: no
