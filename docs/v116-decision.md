# V116 Decision

Decision: keep the Agent Fabric lifecycle smoke as a source-only CLI/export
surface.

Evidence:

- `python3 tests/test_agent_fabric_smoke_cli.py` covers the new
  `depone agent-fabric-smoke` command writing JSON and optional operator view.
- `python3 -m depone agent-fabric-smoke --self-test` exports a deterministic
  source-only smoke summary.
- Missing role contracts still compile to `blocked-unsupported-critical` and
  the CLI preserves `overall_decision: blocked-compile`.

Boundary:

- no live model execution;
- no command execution;
- no worktree creation;
- no public direct-agent superiority claim;
- no trust upgrade beyond the existing V107-V112 compiler, capture, report, and
  operator-view contracts.
