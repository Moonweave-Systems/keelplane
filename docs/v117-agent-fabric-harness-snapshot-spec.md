# V117 Agent Fabric Harness Snapshot Spec

V117 exports static Agent Fabric harness capability snapshots as operator-facing
JSON. It combines the shipped V107 capability fixtures with deterministic tool
mapping coverage so operators can see which harnesses are exact, approximated,
or blocked before any live adapter work.

## Command

```bash
python3 -m depone agent-fabric-harness-snapshot \
  --harness shell \
  --harness codex \
  --out agent-fabric-harness-snapshot.json
```

Inputs:

- `--harness`: optional harness name, repeated as needed. When omitted, Depone
  exports every harness in the deterministic mapping table.
- `--out`: summary JSON output path, default
  `agent-fabric-harness-snapshot.json`.

## Boundary

The command is source-only. It reads shipped fixtures and mapping tables only.
It does not detect installed tools, execute commands, call live models, inspect
MCP runtime state, create worktrees, or claim runtime enforcement.

Unknown harness names are not silently dropped. They produce
`blocked-unsupported-critical` in the exported snapshot.

## Outputs

The JSON summary contains:

- `kind: agent-fabric-harness-capability-snapshot`;
- `requested_harnesses`;
- `decision`: `snapshot-exact`, `snapshot-with-approximations`, or
  `blocked-unsupported-critical`;
- valid shipped `capability` records for known harnesses;
- per-harness `tool_mapping_status_counts`;
- `exact_tools`, `approximated_tools`, and `unsupported_critical_tools`;
- `unknown_harnesses` and `unsupported_critical` blockers.

## Verification

Focused verification:

```bash
python3 tests/test_agent_fabric_harness_snapshot.py
python3 -m depone agent-fabric-harness-snapshot --self-test
python3 -m depone validate-contracts --self-test
```
