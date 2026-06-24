# V117 Decision

Decision: keep harness capability export source-only.

Evidence:

- `python3 tests/test_agent_fabric_harness_snapshot.py` covers the new snapshot
  API, CLI JSON export, approximation reporting, and unknown-harness blocking.
- `python3 -m depone agent-fabric-harness-snapshot --self-test` exports a
  deterministic shell+codex snapshot.
- Existing capability fixtures remain validated through
  `python3 -m depone validate-contracts --self-test`.

Boundary:

- no live harness detection;
- no command execution;
- no model calls;
- no MCP runtime introspection;
- no public superiority claim;
- no trust upgrade beyond shipped V107 capability fixtures and deterministic
  tool mapping tables.
