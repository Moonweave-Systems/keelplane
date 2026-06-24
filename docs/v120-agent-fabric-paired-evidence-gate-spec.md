# V120 Agent Fabric Paired Evidence Gate Spec

V120 extends `depone agent-fabric-claim-gate` with optional source-only paired
evidence. The gate can move from `blocked-missing-paired-evidence` to
`ready-for-public-claim-review` only when the paired evidence is source-ready and
hash-bound to the adapter smoke report. It still does not approve public claims.

## Command

```bash
python3 -m depone agent-fabric-claim-gate \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --paired-evidence paired-evidence.json \
  --out agent-fabric-claim-gate.json
```

## Paired Evidence Contract

The paired evidence input is a JSON object with:

- `decision`: `paired-evidence-ready-source-only`.
- `source_hashes.adapter_smoke_report`: canonical hash of the adapter smoke
  report consumed by the gate.
- `boundary.approves_public_claim`: `false`.

A mismatched adapter-smoke hash, a non-ready decision, or evidence that claims to
approve public claims blocks the gate.

## Decisions

- `ready-for-public-claim-review`: adapter smoke is source-ready and paired
  evidence is source-ready, hash-bound, and non-approving.
- `blocked-paired-evidence-not-ready`: paired evidence is invalid, mismatched,
  or overclaims public approval.
- Existing V119 decisions remain unchanged when paired evidence is absent or
  adapter smoke is not source-ready.

## Boundary

The command remains source-only. It does not execute commands, call live models,
detect installed harnesses, inspect MCP runtime state, approve public claims, or
upgrade trust.

## Verification

```bash
python3 tests/test_agent_fabric_claim_gate_paired_evidence.py
python3 tests/test_agent_fabric_claim_gate.py
python3 -m depone agent-fabric-claim-gate --self-test
python3 scripts/check_contract.py --tier changed
```
