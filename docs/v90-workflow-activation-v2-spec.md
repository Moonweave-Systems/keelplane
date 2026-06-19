# V90 Workflow Activation V2 Spec

Status: implemented product-evidence activation in
`scripts/dwm_workflow_activation.py`.

## Research and Prior Art

V85 answered whether DWM could move from a completed workflow into the next
workflow design using install audit, dry-run receipt, and completed run status.
Later gates added public brand boundaries, roadmap reconciliation, and shared
command safety. V90 closes the gap by making activation consume those newer
evidence surfaces before it says the next workflow can proceed.

## Product Position and Non-Goals

V90 is an activation gate, not an executor. It decides whether the next safe
action is workflow design after the current workflow, install surface, product
surface, roadmap, and command-safety evidence are all current.

Non-goals:

- do not execute commands,
- do not create worktrees or sessions,
- do not run live adapters,
- do not bypass human gates for live execution,
- do not treat generated artifacts as source truth.

## Workflow Architecture

`scripts/dwm_workflow_activation.py` still supports the V85 three-input gate.
The V90 path adds:

- `--brand-audit`,
- `--roadmap-reconciliation`,
- `--command-safety`.

The activation blocks if:

- the installed surface is stale or blocked,
- the runner receipt is not a non-executing dry-run,
- the current workflow is not complete or lacks the recorded human gate,
- the brand boundary audit is not `brand_boundary_ready`,
- the roadmap reconciliation is not `roadmap_reconciled`,
- the roadmap latest version is not `V90`,
- command safety did not keep all required fixtures.

## Execution Model

Run fixture coverage:

```bash
python scripts/dwm_workflow_activation.py --manifest fixtures/v90/manifest.json --out out/workflow-activations/v90-final
```

Run canonical activation v2:

```bash
python scripts/dwm_workflow_activation.py activate --audit out/installed-surface-audits/v84-canonical/installed-surface-audit.json --receipt out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json --status out/v9/v32-semantic-dogfood/status.json --brand-audit out/brand-boundary-audits/v87-canonical/brand-boundary-audit.json --roadmap-reconciliation out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --out out/workflow-activations/v90-canonical
```

## Safety and Verification Gates

V90 emits `ready_for_next_workflow_design` only when all inputs are current and
unblocked. It emits no execution command. Safe default: preserve artifacts and
fix blockers before continuing.

## Evaluation Fixtures

`fixtures/v90/manifest.json` covers:

- ready activation with product evidence,
- blocked brand boundary,
- blocked stale roadmap version,
- blocked command safety failure.

## Release Plan

V90 adds product-evidence activation to the release command corpus and makes
V87/V88/V89 evidence part of the next-workflow readiness decision.
