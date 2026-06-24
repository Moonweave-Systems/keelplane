# Keelplane Upstream Gap Map

Status: Proposed implementation guide
Based on the public repository state inspected on 2026-06-23.

## 1. `keelplane/verify/engine.py` — critical

Current risks:

- adversarial verification is a path-existence heuristic;
- required claims can appear unrefuted without an evaluator;
- gates are plan-level and repeated across phases;
- budget agent count is inferred from filenames;
- verdict does not expose evidence origin/assurance.

Required changes:

1. Introduce `ClaimEvaluation` states:
   `supported`, `refuted`, `not-evaluated`, `stale`,
   `unsupported-evaluator`.
2. A required non-supported state yields `inconclusive`, except refuted yields
   `fail`.
3. Replace marker-only gate logic with action-bound event evaluation.
4. Count invocation IDs from a manifest.
5. Add authoritative `decision` and `assurance`; render legacy verdict only for
   compatibility.
6. Add stable issue codes and source evidence references.

First regression fixture:

> A plan has a required claim and an existing ground-truth path, but no claim
> evaluator result. Expected decision: `inconclusive`, never `pass`.

## 2. `keelplane/verify/adapters/generic.py` — high

Current risks:

- reads every file into memory;
- expands binary data to hex;
- lacks file count/size/depth policy;
- lacks symlink/special-file/collision handling;
- may collect sensitive contents unnecessarily.

Required changes:

- separate discovery from optional content loading;
- streaming SHA-256;
- path containment and collision checks;
- reject symlinks/devices/sockets/FIFOs by default;
- configurable max files, bytes, depth, and time;
- metadata-only default;
- content allowlist and redaction policy;
- before/after stat check while hashing.

## 3. `keelplane/cli/design.py` — high product semantics

Current behavior is deterministic keyword/template selection. It is a useful
scaffold, not a context-aware planner.

Recommended transition:

```text
keelplane plan scaffold
keelplane plan import
keelplane plan validate
keelplane plan explain
```

Keep `design` as a compatibility alias until users migrate. Do not claim broad
objective decomposition superiority until a real planner producer and eval
exist.

## 4. `keelplane/core/plan_schema.py` — high maintainability

Current strict validation dynamically imports `scripts/evaluate_plan.py` when
present and falls back to an embedded contract otherwise. This creates two
validation authorities and package/repository behavior drift.

Required changes:

- one package-owned schema/validator;
- fixture scripts call package code, never the inverse;
- explicit schema migration registry;
- duplicate-key-safe JSON loader where security relevant;
- unknown major version fails closed;
- validation issues have stable codes and JSON Pointer paths.

## 5. `keelplane/compile/*` — high

Required changes:

- replace “bijection” language with lowering;
- add target capability manifests and `compile-report.json`;
- fail on unsupported critical controls;
- remove targets from CLI choices until implemented or mark them experimental;
- do not hardcode a provider in generated output;
- validate generated target artifacts with the target's official parser/CLI;
- avoid a handwritten YAML emitter becoming the semantic source of truth.

## 6. `keelplane/__main__.py` — medium

Add commands only when their package implementation and end-to-end fixtures are
ready:

```text
capture
report
plan scaffold/import/explain
```

Do not advertise unimplemented compile targets as normal choices.

## 7. Product shell and runner — critical boundary clarification

Existing roadmap work includes runner, worktrees, Codex CLI execution, fan-out,
and repair loops, while the newer README says Keelplane does not execute agents.

Recommended module boundary:

```text
keelplane-core      deterministic policy/verification
keelplane-capture   passive local observation/import
keelplane-runner    optional external-harness launcher/custodian
```

The CLI may expose all three, but docs and reports must identify which component
produced each observation.

## 8. `pyproject.toml` and release versioning — medium

Avoid using internal milestone count as package SemVer. Recommended:

- package versions: `0.5.0`, `0.6.0`, then `1.0.0` after compatibility promise;
- plan/evidence/report schemas versioned independently;
- milestone “V105” retained only in roadmap documents;
- optional integration extras contain real dependencies or are omitted.

## 9. `scripts/dwm_*.py` — high complexity

Freeze new one-concept scripts. Classify existing scripts:

- package source to migrate;
- release/evaluation fixtures;
- compatibility wrappers;
- archive/delete.

Public docs should emphasize one supported path. Internal evidence tooling can
remain, but must not dominate the user-facing product.

## 10. README and claims — medium

README should state:

- current `design` intelligence honestly;
- which targets are actually runnable;
- assurance limits of local evidence;
- optional runner boundary;
- no direct-agent productivity claim without paired results;
- one five-minute workflow that creates a real report.

## 11. Recommended PR sequence

### PR 1 — Semantic safety

- no-evaluator => inconclusive;
- decision + assurance data model;
- regression fixtures.

### PR 2 — Safe discovery

- streaming generic adapter;
- path/size/privacy fixtures.

### PR 3 — Evidence manifest v1

- schemas;
- local A1 capture;
- seal verification;
- report skeleton.

### PR 4 — Reference pack

- native agents/profiles;
- installer;
- no runtime integration yet.

### PR 5 — Native lowering

- capability reports;
- Codex and Claude run contracts.

### PR 6 — Paired dogfood

- direct vs profile runs;
- activation policy adjustments;
- remove roles that do not pay for themselves.
