# V119 Agent Fabric Claim Gate Spec

V119 adds a source-only public-claim gate for Agent Fabric evidence. It consumes a
V118 adapter smoke report and records whether a public benefit claim is allowed.
Source-ready adapter smoke is necessary but not sufficient: public claims remain
blocked until paired dogfood or explicitly approved live adapter-smoke evidence
exists.

## Command

```bash
python3 -m depone agent-fabric-claim-gate \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --out agent-fabric-claim-gate.json
```

Inputs:

- `--adapter-smoke`: V118 adapter smoke report JSON.
- `--claim-scope`: claim scope label, default `public-benefit`.
- `--out`: report JSON output path, default `agent-fabric-claim-gate.json`.

## Boundary

The command does not execute commands, call live models, detect installed
harnesses, inspect MCP runtime state, approve public claims, or upgrade trust. It
is a deterministic source-evidence gate.

## Decisions

- `blocked-adapter-smoke-not-ready`: the adapter smoke report is absent from the
  source-ready state.
- `blocked-missing-paired-evidence`: the adapter smoke report is source-ready,
  but paired dogfood or explicitly approved live adapter-smoke evidence is still
  missing.

## Outputs

The report contains `kind`, `decision`, `claim_scope`, adapter-smoke decision and
harness fields, adapter-smoke blockers, source hashes, blockers, and an explicit
boundary object recording no execution, no model calls, no installed harness
detection, no MCP runtime introspection, no public-claim approval, and no trust
upgrade.

## Verification

```bash
python3 tests/test_agent_fabric_claim_gate.py
python3 -m depone agent-fabric-claim-gate --self-test
python3 scripts/check_contract.py --tier changed
```
