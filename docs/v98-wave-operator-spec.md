# V98 Wave Operator Spec

Status: implemented next wave operator.

V98 adds `scripts/dwm_wave_operator.py`, a source-only operator that consumes
V97 benchmark readiness and V90 workflow activation evidence to select the next
large product wave. It turns the current question from "what should we do next"
into an artifact-backed wave decision.

The tool writes `wave-operator.json`, `wave-operator.md`, and `status.json`
under `out/wave-operators/<wave_id>`.

## Command

```bash
python scripts/dwm_wave_operator.py --manifest fixtures/v98/manifest.json --out out/wave-operators/v98-final
python scripts/dwm_wave_operator.py select --readiness out/benchmark-readiness/v97-canonical/benchmark-readiness.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --out out/wave-operators/v98-canonical
```

## Decision Model

V98 selects `dogfood-evidence-wave` when:

- V97 benchmark readiness is recorded;
- V90 activation is ready for next workflow design;
- public benchmark publication is still blocked by promotion policy.

V98 stops at `human_gate_required` when public benchmark publication becomes
possible, because README benchmark publication still requires human review. It
blocks when readiness or activation is blocked.

## Safety

The wave operator does not execute commands, create worktrees, use the network,
or publish benchmark claims. It may emit a command string for a safe source-only
wave, but command execution remains a later explicit action.

Public benchmark graph publication still requires promotion evidence and human
review. The safe default is to continue evidence acquisition, not to publish a
graph.

Public benchmark graph publication still requires promotion evidence and human review.

## Fixtures

`fixtures/v98/manifest.json` covers:

- ready readiness selecting dogfood evidence acquisition;
- public benchmark readiness stopping at a human gate;
- blocked readiness blocking wave selection;
- blocked activation blocking wave selection.

## Contract

V98 adds wave selection to the changed-surface contract tier and product doctor
command corpus. It depends on V97 readiness and V90 activation evidence, but it
does not make generated `out/` artifacts the source of truth.
