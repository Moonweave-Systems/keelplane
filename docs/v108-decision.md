# V108 Decision

Decision: add a deterministic shell reference adapter fixture, not a live agent
adapter.

V108 advances Agent Fabric by making the adapter-output shape explicit:
invocation packet in, fixture capture out. The fixture can carry self-report,
diff summary, touched files, test output, and command receipts, but all of that
remains non-authoritative `A0-claims-only` material until a separate observer
captures and verifies real evidence.

Implemented in this slice:

- `depone.agent_fabric.reference_adapter.build_reference_adapter_fixture(...)`;
- `depone.agent_fabric.reference_adapter.validate_reference_adapter_fixture(...)`;
- a shipped shell fixture at
  `depone/fixtures/agent_fabric/reference_adapter_shell.json`;
- `validate-contracts` dispatch support for
  `agent-fabric-reference-adapter-fixture`;
- stdlib tests for valid fixture shape, live-execution rejection,
  observer-owned output rejection, invalid invocation rejection, and CLI dispatch.

This decision intentionally does not claim:

- live model execution;
- shell command execution;
- adapter evidence above `A0-claims-only`;
- hard tool hiding in native Codex, Claude Code, OpenCode, or OMO;
- productivity, quality, cost, speed, or superiority benefits.

The next implementation slice should connect fixture output to the Depone
evidence manifest as observed local capture only when an observer, not the
agent, records the diff, touched files, test output, and command receipts.
