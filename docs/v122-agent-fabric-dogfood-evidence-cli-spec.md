# V122 Agent Fabric Dogfood Evidence CLI Spec

V122 adds `depone agent-fabric-dogfood-evidence`, a source-only command that
turns an observed Agent Fabric capture manifest into the `dogfood-evidence.json`
input consumed by V121 paired evidence reports. It validates existing capture
evidence; it does not run dogfood tasks itself.

## Command

```bash
python3 -m depone agent-fabric-dogfood-evidence \
  --capture-manifest depone/fixtures/agent_fabric/capture_manifest_shell.json \
  --out dogfood-evidence.json
```

The output can feed the V121/V120 chain:

```bash
python3 -m depone agent-fabric-paired-evidence \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --dogfood-evidence dogfood-evidence.json \
  --out paired-evidence.json
python3 -m depone agent-fabric-claim-gate \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --paired-evidence paired-evidence.json \
  --out agent-fabric-claim-gate.json
```

## Input Contract

The input is an Agent Fabric capture manifest. Ready dogfood evidence requires:

- `assurance`: `A1-local-observed`;
- `decision`: `observed-local-capture`;
- a valid `observer_capture_hash`;
- observer `test_output.status`: `passed`.

## Output Contract

The dogfood evidence report includes:

- `kind`: `agent-fabric-dogfood-evidence`;
- `decision`: `dogfood-evidence-ready-source-only` when the observed capture is
  valid and tests passed;
- `evidence_type`: `paired-dogfood`;
- `capture_assurance`, `capture_decision`, and `test_status`;
- `source_hashes.capture_manifest`: canonical hash of the capture manifest;
- a boundary that keeps command execution, live model calls, public-claim
  approval, and trust upgrade false.

## Decisions

- `dogfood-evidence-ready-source-only`: capture manifest is valid A1 observed
  evidence and its observer test output passed.
- `blocked-invalid-capture-manifest`: capture manifest validation fails.
- `blocked-capture-not-observed`: capture is only A0/self-report or otherwise
  not A1 observed.
- `blocked-dogfood-tests-not-passed`: observed capture exists but tests did not
  pass.

## Boundary

The command reads already-recorded evidence only. It does not execute commands,
call live models, detect installed harnesses, inspect MCP runtime state, approve
public claims, or upgrade trust.

## Verification

```bash
python3 tests/test_agent_fabric_dogfood_evidence.py
python3 -m depone agent-fabric-dogfood-evidence --self-test
python3 tests/test_agent_fabric_paired_evidence.py
python3 -m depone agent-fabric-paired-evidence --self-test
python3 tests/test_agent_fabric_claim_gate_paired_evidence.py
python3 scripts/check_contract.py --tier changed
```
