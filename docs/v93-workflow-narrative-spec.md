# V93 Workflow Narrative Spec

Status: implemented workflow narrative and Depone Control Deck rendering in
`scripts/dwm_workflow_narrative.py`.

## Research and Prior Art

V88-V92 made Depone safer and more evidence-bound, but the operator still
had to inspect several JSON artifacts to understand whether the workflow was
actually ready. V93 adds a narrative rendering layer that turns existing
artifact decisions into a compact Control Deck without inventing new authority.

## Product Position and Non-Goals

V93 is a status renderer. It makes the workflow feel legible and operational
while preserving the deterministic control-plane boundary.

Non-goals:

- do not claim autonomous execution,
- do not create fictional agents or unverified role activity,
- do not execute commands,
- do not create worktrees or sessions,
- do not fetch network evidence,
- do not treat narrative labels as source truth.

## Workflow Architecture

`scripts/dwm_workflow_narrative.py` reads:

- V88 roadmap reconciliation,
- V89 command safety,
- V90 workflow activation,
- V92 evidence oracle.

It emits:

- `workflow-narrative.json`,
- `workflow-narrative.md`,
- `status.json`.

The rendered Control Deck uses these labels:

- `Chart`: roadmap reconciliation state,
- `Gate`: command safety state,
- `Activation`: next-workflow readiness,
- `Oracle`: evidence-claim verification,
- `Next move`: the safe next action from activation or blocker policy.

These labels are status rendering only. Artifact assertions and source hashes
remain the source of truth.

## Execution Model

Run fixture coverage:

```bash
python scripts/dwm_workflow_narrative.py --self-test
python scripts/dwm_workflow_narrative.py --manifest fixtures/v93/manifest.json --out out/workflow-narratives/v93-final
```

Run canonical Control Deck rendering:

```bash
python scripts/dwm_workflow_narrative.py render --roadmap out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --oracle out/evidence-oracles/v92-canonical/evidence-oracle.json --out out/workflow-narratives/v93-canonical
```

## Safety and Verification Gates

V93 blocks when roadmap reconciliation is stale, command safety failed,
activation is not ready, activation source hashes drift from current artifacts,
or the evidence oracle did not verify claims.

## Evaluation Fixtures

`fixtures/v93/manifest.json` covers:

- ready Control Deck,
- stale roadmap,
- command-safety source-hash drift,
- blocked oracle evidence.

## Release Plan

V93 adds Control Deck rendering to the changed-surface contract tier and keeps
the voice policy explicit: evocative labels may improve operator clarity, but
they cannot replace artifact-backed evidence.
