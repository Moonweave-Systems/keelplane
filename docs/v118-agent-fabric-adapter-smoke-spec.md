# V118 Agent Fabric Adapter Smoke Spec

V118 adds a source-only adapter smoke report. It binds a V108 reference adapter
fixture to a V117 harness snapshot and records whether the adapter fixture is
ready for source-only review before any live adapter work.

## Command

```bash
python3 -m depone agent-fabric-adapter-smoke \
  --adapter-fixture depone/fixtures/agent_fabric/reference_adapter_shell.json \
  --harness-snapshot agent-fabric-harness-snapshot.json \
  --out agent-fabric-adapter-smoke.json
```

Inputs:

- `--adapter-fixture`: reference adapter fixture JSON.
- `--harness-snapshot`: optional harness snapshot JSON. When omitted, Depone
  builds a source-only snapshot for the adapter fixture harness.
- `--out`: report JSON output path, default `agent-fabric-adapter-smoke.json`.

## Boundary

The command does not execute commands, call live models, detect installed
harnesses, inspect MCP runtime state, create worktrees, or upgrade trust. It is
a deterministic binding of shipped/source JSON surfaces only.

## Decisions

- `ready-source-only`: adapter fixture validates and its harness is present in
  the snapshot without unsupported-critical status.
- `blocked-invalid-adapter-fixture`: fixture validation fails.
- `blocked-harness-not-in-snapshot`: fixture harness is absent from the snapshot.
- `blocked-unsupported-critical`: fixture harness is present but its snapshot is
  unsupported-critical.

## Outputs

The report contains `kind`, `decision`, adapter harness/mode/trust fields,
validation errors, blockers, source hashes for the fixture and snapshot, and an
explicit boundary object recording no execution, no model calls, no live harness
detection, no MCP runtime introspection, and no trust upgrade.

## Verification

```bash
python3 tests/test_agent_fabric_adapter_smoke.py
python3 -m depone agent-fabric-adapter-smoke --self-test
python3 -m depone agent-fabric-harness-snapshot --self-test
```
