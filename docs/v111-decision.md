# V111 Decision

Decision: keep the V111 Agent Fabric operator-view/exporter as a
presentation-only layer over verification reports.

V111 should make the V110 report fields easier for an operator to read without
changing the trust model. The view/exporter is a presentation layer over Depone
verification reports: it can summarize `verdict`, `decision`, `assurance`, and
Agent Fabric capture entries, but it cannot create new evidence or upgrade an
assurance label.

Accepted implementation:

- consume existing verification report JSON as the source of truth;
- preserve `A0-claims-only` and `A1-local-observed` exactly as V109/V110 define
  them;
- keep invalid capture manifests visible and fail-closed through the underlying
  report;
- expose evidence paths in any exported summary for traceability;
- keep the implementation stdlib-only and deterministic;
- expose the Markdown exporter through
  `python3 -m depone verify --operator-view-out <path>`.

Resolved integration choices:

- the exporter command is `--operator-view-out` on `depone verify`;
- tests exercise the CLI write path, empty capture reports, invalid capture
  rendering, and evidence-contract dominance over Agent Fabric capture state;
- the view layer renders report fields without revalidating capture manifests;
- missing V110 fields render as `unknown`, not as a stronger pass state;
- public docs stay on the Depone brand and do not reintroduce old product
  naming.

This decision intentionally does not claim:

- live model or command execution;
- external attestation;
- new assurance levels beyond V109/V110;
- improved productivity, speed, cost, quality, or direct-agent superiority;
- release readiness beyond the focused V111 operator-view slice.
