# V120 Decision: Agent Fabric Paired Evidence Gate

Decision: let the Agent Fabric claim gate consume optional source-only paired
evidence and move to human review readiness, not automatic public approval.

Rationale:

- V119 correctly blocks source-only adapter smoke from becoming a public claim.
- The next safe step is to bind paired evidence by source hash before human
  review.
- Hash mismatch or any evidence that claims public approval must block.

Boundary:

- no command execution;
- no live model calls;
- no installed harness detection;
- no MCP runtime introspection;
- no automatic public-claim approval;
- no trust upgrade.
