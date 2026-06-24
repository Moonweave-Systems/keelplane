# V108 Agent Fabric Reference Adapter Fixture Spec

V108 adds the first deterministic Agent Fabric adapter fixture while keeping
Depone Core out of live agent execution.

## Boundary

The reference adapter is fixture-only:

- it does not call live models;
- it does not execute shell commands;
- it does not prove productivity, quality, or direct-agent superiority;
- it does not let an agent write observer-owned evidence, approvals, seals, or
  final decisions.

The fixture records an invocation packet plus non-authoritative captured fields:

- `self_report`;
- `diff_summary`;
- `touched_files`;
- `test_output`;
- `command_receipts`.

The capture trust label is always `A0-claims-only`. Later observed capture work
may lift evidence to `A1-local-observed`, but V108 intentionally does not.

## Reference harness

The first reference fixture targets the local `shell` harness because V107 can
compile exact shell tool mappings and because a fixture-only shell adapter can be
validated without introducing live model or provider behavior.

## Contract

A valid V108 fixture has kind
`agent-fabric-reference-adapter-fixture` and must satisfy these rules:

1. `adapter.mode` is `fixture-only`.
2. `adapter.executes_commands` is `false`.
3. `adapter.harness` is `shell` and matches `invocation.target_harness`.
4. `capture.trust_level` is `A0-claims-only`.
5. `capture.self_report` is a valid Agent Fabric result self-report.
6. `capture.diff_summary.changed_files` and `capture.touched_files` are lists of
   strings.
7. `capture.test_output.status` is one of `not-run`, `passed`, `failed`, or
   `error`.
8. `capture.command_receipts` is a list of objects.
9. Agent result outputs under observer-owned evidence paths are rejected.

## Verification

The intended verification surface is:

```bash
python3 tests/test_agent_fabric_reference_adapter.py
python3 -c 'from depone.agent_fabric.reference_adapter import _self_test; _self_test()'
python3 -m depone validate-contracts --file depone/fixtures/agent_fabric/reference_adapter_shell.json
python3 -m depone validate-contracts --all
```
