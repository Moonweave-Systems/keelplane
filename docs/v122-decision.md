# V122 Decision: Agent Fabric Dogfood Evidence CLI

Decision: add a source-only CLI that produces dogfood evidence from validated
A1 local observed Agent Fabric capture manifests.

Rationale:

- V121 created the paired evidence producer, but its dogfood input still needed
  a deterministic source-only producer.
- Reusing capture manifest validation keeps dogfood evidence tied to existing
  observer hashes instead of trusting agent self-report.
- Passing dogfood evidence can feed public-claim review readiness, but it still
  cannot approve public claims.

Boundary:

- no command execution;
- no live model calls;
- no installed harness detection;
- no MCP runtime introspection;
- no automatic public-claim approval;
- no trust upgrade.
