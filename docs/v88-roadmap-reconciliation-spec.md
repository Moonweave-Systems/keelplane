# V88 Roadmap Reconciliation Spec

Status: implemented roadmap reconciliation audit in
`scripts/dwm_roadmap_reconciliation.py`.

## Objective

Keep the product spec, automation roadmap, and release history aligned with the
current Keelplane state. V88 prevents the project from looking half-planned and
half-implemented after V52-V87 added product evidence, dogfood measurement,
graph timing, activation, and brand boundary gates. The audit now reconciles
through V95 score history.

## Product Boundary

- Public product brand: `Keelplane`.
- Internal engine name: `DWM Core`.
- Latest reconciled version: `V95`.
- `docs/release-history.md` remains the implementation-history source.
- `docs/automation-roadmap.md` remains the operator-facing roadmap.
- `docs/spec.md` remains the product contract and safety boundary.

## Audit Rules

The audit reads the three roadmap surfaces and emits
`roadmap-reconciliation.json`, `roadmap-reconciliation.md`, and `status.json`.

It blocks when:

- `docs/spec.md` does not use the current Keelplane / DWM Core boundary.
- `docs/spec.md` lacks the V87 brand boundary audit, V88 roadmap
  reconciliation status, V89 command safety status, V90 activation v2
  status, V91 contract tiering status, V92 evidence oracle status, or V93
  workflow narrative status, or V94 control deck score status, V95 score history status.
- `docs/automation-roadmap.md` still says V12-V20 are planned but not
  implemented.
- `docs/automation-roadmap.md` lacks the V52-V95 continuation summary.
- `docs/release-history.md` lacks the V88, V89, V90, or V91 entry.

## Execution Policy

V88 is audit-only. It does not execute queued commands, create worktrees, run
live adapters, rename packages, publish benchmark claims, or claim autonomous
execution.

V88 does not claim autonomous execution.

## Verification

- `python scripts/dwm_roadmap_reconciliation.py --self-test`
- `python scripts/dwm_roadmap_reconciliation.py --manifest fixtures/v88/manifest.json --out out/roadmap-reconciliations/v88-final`
- `python scripts/dwm_roadmap_reconciliation.py audit --out out/roadmap-reconciliations/v88-canonical`
