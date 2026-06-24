# V119 Decision: Agent Fabric Claim Gate

Decision: add a source-only claim gate before any public Agent Fabric benefit or
superiority claim.

Rationale:

- V118 proves only that an adapter fixture binds to a source harness snapshot.
- Public claims need paired dogfood or explicitly approved live adapter-smoke
  evidence, not just source readiness.
- A deterministic gate prevents source-only artifacts from being misread as live
  proof.

Boundary:

- no command execution;
- no live model calls;
- no installed harness detection;
- no MCP runtime introspection;
- no public-claim approval;
- no trust upgrade.
