# V106 Multi-Wave Spec

Status: implemented deterministic multi-wave validation
Date: 2026-06-23

## Purpose

V106 adds an optional multi-wave execution-path contract for consumers that need
more structure than the legacy first slice. The legacy `first_slice` remains
required, so existing plan consumers keep working.

## Contract

`execution_path.first_wave` describes the object-shaped first wave, including a
concurrency cap, slice objects, entry and exit gates, and fan-in semantics. The
canonical V106 fixture uses `wave-1` for selected V105 verify-wedge cases:
`missing-test-log`, `forbidden-file-touch`, `test-weakened`, and `good`.

`execution_path.waves` describes follow-on wave records. Wave ids must be
unique, dependencies must point to known wave ids, dependency cycles are blocked,
and dependent waves must name an `entry_gate` that references prior receipt,
verified, or exit-gate semantics. The canonical `wave-2` unlocks only after the
`wave-1` receipt proves the selected V105 verified/refuted verdicts and
evidence-contract codes match expected outcomes.

Both `scripts/evaluate_plan.py` and
`keelplane/core/embedded_plan_contract.py` validate the same pass/fail contract.

## Command Contract

```bash
python scripts/v106_multi_wave.py --self-test
```

The deterministic fixture suite lives under `fixtures/v106-multi-wave/` and
covers a valid multi-wave plan, dependency cycles, empty slices, missing entry
gates, ungated follow-on waves, V105-backed wave-1 receipts, and legacy
first-slice-only compatibility.

## Boundaries

V106 validates plan and fixture contracts only. It does not execute waves, run
agents, install dependencies, use the network, publish, deploy, or relax existing
risk gates.
