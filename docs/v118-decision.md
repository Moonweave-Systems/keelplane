# V118 Decision

Decision: keep adapter smoke source-only.

Evidence:

- `python3 tests/test_agent_fabric_adapter_smoke.py` covers ready shell fixture
  binding, absent harness blocking, invalid fixture blocking, and CLI export.
- `python3 -m depone agent-fabric-adapter-smoke --self-test` exports a
  deterministic source-only report for the shipped shell reference fixture.
- `python3 -m depone agent-fabric-harness-snapshot --self-test` preserves the
  upstream snapshot input.

Boundary:

- no command execution;
- no live model calls;
- no installed harness detection;
- no MCP runtime introspection;
- no trust upgrade;
- no public direct-agent superiority claim.
