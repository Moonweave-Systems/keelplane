# V110 Decision

Decision: surface Agent Fabric capture assurance in verification reports.

V110 keeps the existing verification verdict intact while adding a clearer
operator-facing decision and an assurance label. This lets Depone show whether a
report passed, failed, or remains inconclusive separately from whether the
Agent Fabric material is only self-reported (`A0-claims-only`) or locally
observed (`A1-local-observed`).

Implemented in this slice:

- `VerificationReport.decision` derived from the existing verdict;
- `VerificationReport.assurance` derived from valid Agent Fabric captures;
- `VerificationReport.agent_fabric_captures` entries with path, manifest
  decision, assurance, validity, and validation errors;
- fail-closed handling where invalid capture manifests refute the report;
- CLI summary output for decision and assurance;
- regression tests for valid A1 capture, self-report-only A0 capture, and
  tampered capture manifests.

This decision intentionally does not claim:

- live model execution;
- command execution by the verifier;
- external attestation;
- sandbox observation beyond the V109 local observer manifest;
- productivity, quality, cost, speed, or superiority benefits.

The next implementation slice should add a small fixture/report exporter or
operator view that consumes the new report fields without adding new trust
levels or bypassing evidence-contract failures.
