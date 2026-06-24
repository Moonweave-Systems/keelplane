# V116 Agent Fabric Smoke CLI Spec

V116 promotes the V112 source-only Agent Fabric lifecycle smoke helper into an
operator-facing Depone CLI export surface.

## Command

```bash
python3 -m depone agent-fabric-smoke \
  --profile profile.json \
  --roles role.json \
  --plan plan.json \
  --harness shell \
  --out agent-fabric-smoke.json \
  --operator-view-out operator-view.md
```

Inputs:

- `--profile`: Agent Fabric profile JSON.
- `--roles`: role contract JSON path, repeated as needed, or a role-set JSON
  with a top-level `roles[]` list.
- `--plan`: Depone plan JSON used by the existing verifier.
- `--harness`: target harness name, default `shell`.
- `--out`: summary JSON output path, default `agent-fabric-smoke.json`.
- `--operator-view-out`: optional Markdown export of the embedded operator
  view.
- `--observer-capture`: optional Depone observer capture JSON.
- `--allow-touched-file`: optional repeated touched-file allowlist entries for
  observer-capture validation.

## Boundary

The command is an export surface over existing deterministic pieces. It does
not execute commands, launch workers, call live models, install dependencies,
create worktrees, or upgrade Agent Fabric self-reports into authoritative
Depone evidence.

Unsupported critical compile controls still produce `blocked-compile` even when
the downstream verification report can render a passing evidence contract.
Approximations remain visible in the summary.

## Outputs

The JSON summary is exactly the V112 smoke summary shape:

- `kind: agent-fabric-compile-to-report-smoke`;
- `compile_decision`;
- `invocation_count`;
- `first_invocation_instructions`;
- `capture_assurance`;
- `report_decision`;
- `report_assurance`;
- `overall_decision`;
- `operator_view`.

When `--operator-view-out` is provided, the command writes the embedded operator
Markdown view to that path as a convenience export.

## Verification

Focused verification:

```bash
python3 tests/test_agent_fabric_smoke_cli.py
python3 -m depone agent-fabric-smoke --self-test
python3 tests/test_agent_fabric_lifecycle_smoke.py
python3 -m depone compile --self-test
python3 -m depone validate-contracts --self-test
```
