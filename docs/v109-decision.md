# V109 Decision

Decision: add a passive Agent Fabric capture bridge that can produce a
Depone-facing manifest with explicit assurance labels.

V109 preserves the V108 boundary: adapter self-report is still a claim. The new
bridge can emit either:

- `A0-claims-only`, when there is no observer capture; or
- `A1-local-observed`, when a Depone observer supplies hash-bound local
  observations for diff summary, touched files, test output, and command
  receipts.

Implemented in this slice:

- `depone.agent_fabric.capture_bridge.build_capture_manifest(...)`;
- `depone.agent_fabric.capture_bridge.validate_capture_manifest(...)`;
- `agent-fabric-capture-manifest` dispatch support in `validate-contracts`;
- a shipped shell manifest fixture at
  `depone/fixtures/agent_fabric/capture_manifest_shell.json`;
- regression tests for A1, A0, tamper, stale-source, and unexpected touched-file
  cases.

This decision intentionally does not claim:

- live model execution;
- command execution by the bridge;
- external attestation;
- isolated sandbox observation;
- public productivity, quality, cost, speed, or superiority benefits.

The next implementation slice should connect this manifest to the existing
verification report surface so Depone can render decision and assurance
separately without weakening V105/V106 evidence-contract behavior.
