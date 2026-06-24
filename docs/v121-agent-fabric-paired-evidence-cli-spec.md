# V121 Agent Fabric Paired Evidence CLI Spec

V121 adds `depone agent-fabric-paired-evidence`, a source-only command that
builds the paired evidence report consumed by the V120 claim gate. It binds a
ready adapter smoke report to source-only dogfood evidence with canonical
hashes, while preserving the public-claim approval boundary.

## Command

```bash
python3 -m depone agent-fabric-paired-evidence \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --dogfood-evidence dogfood-evidence.json \
  --out paired-evidence.json
```

The output can then be passed to the V120 claim gate:

```bash
python3 -m depone agent-fabric-claim-gate \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --paired-evidence paired-evidence.json \
  --out agent-fabric-claim-gate.json
```

## Input Contract

The command reads two JSON objects:

- an adapter smoke report with `decision: ready-source-only`;
- dogfood evidence with `decision: dogfood-evidence-ready-source-only` and a
  boundary that sets `executes_commands`, `calls_live_models`, and
  `approves_public_claim` to `false`.

## Output Contract

The paired evidence report includes:

- `decision`: `paired-evidence-ready-source-only` when both inputs are ready;
- `evidence_type`: `paired-dogfood`;
- `claim_scope`: `public-benefit` by default;
- `source_hashes.adapter_smoke_report`: canonical hash of the adapter smoke
  input;
- `source_hashes.dogfood_evidence`: canonical hash of the dogfood evidence
  input;
- `boundary.approves_public_claim`: `false`.

## Decisions

- `paired-evidence-ready-source-only`: adapter smoke and dogfood evidence are
  ready, source-only, and non-approving.
- `blocked-adapter-smoke-not-ready`: the adapter smoke report is not
  `ready-source-only`.
- `blocked-dogfood-evidence-not-ready`: dogfood evidence is not source-ready or
  overclaims execution, live model calls, or public-claim approval.

## Boundary

The command does not execute commands, call live models, detect installed
harnesses, inspect MCP runtime state, approve public claims, or upgrade trust.
It only creates the hash-bound JSON input that lets the claim gate move to human
review readiness.

## Verification

```bash
python3 tests/test_agent_fabric_paired_evidence.py
python3 -m depone agent-fabric-paired-evidence --self-test
python3 tests/test_agent_fabric_claim_gate_paired_evidence.py
python3 -m depone agent-fabric-claim-gate --self-test
python3 scripts/check_contract.py --tier changed
```
