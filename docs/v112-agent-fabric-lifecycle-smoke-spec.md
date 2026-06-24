# V112 Agent Fabric Lifecycle Smoke Spec

V112 adds a source-only smoke helper for the Agent Fabric path from compile
output to operator-readable verification output.

## Boundary

The smoke helper does not execute commands, call live models, launch workers, or
create new assurance levels. It only composes existing deterministic pieces:

1. V107 `compile_agent_fabric(...)` invocation packets and compile report;
2. V108 reference adapter fixture shape;
3. V109 capture manifest;
4. V110 verification report decision and assurance fields;
5. V111 operator view rendering.

The helper is a planning and regression surface. It does not make a direct
agent-performance claim and cannot mark unsupported-critical compiles as ready
just because the downstream report renderer can display a passing evidence
contract.

## Implemented behavior

`build_compile_to_report_smoke(...)` returns a deterministic summary with:

- `kind: "agent-fabric-compile-to-report-smoke"`;
- `compile_decision`;
- `invocation_count`;
- first invocation instructions for operator traceability;
- capture assurance;
- verification report decision and assurance;
- `overall_decision`;
- V111 Markdown operator view text.

Decision rules:

- `blocked-unsupported-critical` compile reports become `blocked-compile`;
- non-passing verification reports become `blocked-report`;
- approximated compiles with passing reports become `ready-with-approximations`;
- exact compiles with passing reports become `ready-for-operator-review`.

## Verification

Focused verification:

```bash
python3 tests/test_agent_fabric_lifecycle_smoke.py
python3 tests/test_agent_fabric_report_assurance.py
python3 -m depone compile --self-test
python3 -m depone validate-contracts --self-test
```

