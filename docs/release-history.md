# Depone Release History

This is an implementation history, not the README product pitch.

## Live Scoring and README Benchmark Path

The live benchmark path is intentionally staged:

```text
V28 command plan
  -> V29 runner preflight
  -> V30 receipt ingestion
  -> V31 receipt judgment
  -> V32 score verification
  -> V33 score aggregation
  -> V34 adversarial review
  -> V35 benchmark report
  -> V36 README graph artifacts
```

The README graph pipeline is source-bound. Benchmark visuals read
`report.json.graph_metrics`, not terminal output, generated prose, or manually
copied numbers. Trend graphs require a history ledger and public trend
promotion requires real release history.

## Versioned Slices

- V36: `docs/v36-readme-benchmark-graph-spec.md` implemented
  `benchmark-graph.json`, `benchmark-graph.svg`, and `README-snippet.md`.
- V37: `docs/v37-readme-public-page-spec.md` promoted the first tracked README
  benchmark asset pair.
- V38: `docs/v38-benchmark-history-spec.md` added `history.json` and
  `trend.svg`.
- V39: `docs/v39-benchmark-promotion-spec.md` added `promotion.json` and
  `promoted-trend.svg` behind public-claim policy.
- V40: `docs/v40-benchmark-snapshot-spec.md` added release-bound
  `snapshot.json` records.
- V41: `docs/v41-benchmark-series-spec.md` added sorted `series.json`
  generation from release snapshots.
- V42: `docs/v42-benchmark-candidate-spec.md` added `candidate.json`, the
  pre-publish artifact before tracked README asset changes.
- V43: `docs/v43-direction-check-roadmap.md` recorded the direction checkpoint.
- V44: `docs/v44-candidate-review-gate-spec.md` added
  `candidate-review.json` and `publish-checklist.md`.
- V45: `docs/v45-readme-asset-promotion-spec.md` added the reviewable
  `asset-promotion.json` and `asset-diff.md` bundle.
- V46: `docs/v46-long-run-workflow-queue-spec.md` added `queue.json` and
  `next-action.md`.
- V47: `docs/v47-real-dogfood-corpus-spec.md` added `dogfood-corpus.json` and
  `queue-packets.json`.
- V48: `docs/v48-daily-operator-loop-spec.md` added `operator-loop.json` and
  `today.md`.
- V49: `docs/v49-adapter-parity-matrix-spec.md` added `adapter-parity.json`
  and `adapter-parity.md`.
- V50: `docs/v50-release-candidate-cut-spec.md` added
  `release-candidate.json`, `release-notes.md`, and `release-checklist.md`.
- V51: `docs/v51-canonical-demo-spec.md` added canonical demo output:
  `demo.json`, `status.json`, and `README.md`.
- V52: `docs/v52-readme-ux-spec.md` made the README product-facing.
- V53: `docs/v53-demo-inspect-spec.md` added `demo-inspect.json` and
  `demo-summary.md`.
- V54: `docs/v54-dogfood-attempts-spec.md` added `dogfood-attempts.json` and
  `comparison-ledger.json`.
- V55: `docs/v55-adapter-live-matrix-spec.md` added
  `adapter-live-matrix.json` and `adapter-live-matrix.md`.
- V56: `docs/v56-dogfood-measure-spec.md` added `measurement.json`,
  `attempts.json`, and linked dogfood ledgers.
- V57: `docs/v57-dogfood-pair-spec.md` added `comparison-pair.json`,
  `comparison-pair.md`, and `pair-status.json`.
- V58: `docs/v58-dogfood-pair-series-spec.md` added `pair-series.json`,
  `pair-series.md`, and `graph-readiness.json`.
- V59: `docs/v59-dogfood-chart-candidate-spec.md` added
  `chart-candidate.json`, `chart-candidate.md`, and `chart-data.csv`.
- V60: `docs/v60-dogfood-chart-review-spec.md` added `chart-review.json` and
  `chart-review.md`.
- V61: `docs/v61-dogfood-acquire-spec.md` added `acquisition.json`,
  `acquisition.md`, and `direct-receipt-template.json`.
- V62: `docs/v62-dogfood-operator-spec.md` added `dogfood-operator.json`,
  `dogfood-operator.md`, and `status.json`.
- V63: `docs/v63-dogfood-operator-duplicate-root-spec.md` added duplicate
  task blocking for graph readiness.
- V64: `docs/v64-dogfood-pair-select-spec.md` added `pair-selection.json` and
  `pair-selection.md`.
- V65: `docs/v65-dogfood-chart-render-spec.md` added `chart-render.json`,
  `chart-render.svg`, and `chart-render.md`.
- V66: `docs/v66-dogfood-progress-spec.md` added `dogfood-progress.json`,
  `dogfood-progress.svg`, and `dogfood-progress.md`.
- V67: `docs/v67-dogfood-progress-asset-promotion-spec.md` added
  `dwm-dogfood-progress.svg` and `dwm-dogfood-progress.json` promotion bundles.
- V69: `docs/v69-readme-quality-gate-spec.md` added the README product-page
  quality gate.
- V70: `docs/v70-contract-timeout-spec.md` added timeout failure reporting for
  release-contract child commands.
- V71: `docs/v71-release-timing-spec.md` added `release-timing.json`,
  `release-timing.md`, and `status.json` for release command cost evidence.
- V72: `docs/v72-release-timing-history-spec.md` added
  `timing-history.json`, `timing-history.md`, and `status.json` for release
  timing history evidence.
- V73: `docs/v73-large-workflow-control-spec.md` added the six-axis
  large-workflow control evaluator for direction fidelity, decomposition,
  execution quality, efficiency, recovery, and evidence.
- V74: `docs/v74-large-workflow-dogfood-spec.md` applied the V73 six-axis
  control evaluator to canonical dogfood workflow status.
- V75: `docs/v75-large-workflow-next-spec.md` added control-bound
  next-action selection with command-ready, human-gate-required, and blocked
  decisions.
- V76: `docs/v76-large-workflow-queue-bridge-spec.md` added V75-to-V46 queue
  bridging so command-ready selections become queue packets without executing
  the selected command.
- V77: `docs/v77-large-workflow-queue-preflight-spec.md` added a preflight
  gate for queued large-workflow packets before any runner or operator consumes
  the selected command.
- V78: `docs/v78-graph-timing-gate-spec.md` added `graph-timing.json` and
  `graph-timing.md` to distinguish process progress visibility from public
  benchmark trend promotion.
- V79: `docs/v79-readme-graph-visibility-spec.md` added
  `readme-graph-visibility.json` and `readme-graph-visibility.md` to audit
  README graph visibility against V78 graph timing.
- V80: `docs/v80-continuation-boundary-spec.md` added
  `continuation-boundary.json` and `continuation-boundary.md` to define where
  continuous source-only work must stop.
- V81: `docs/v81-multi-slice-batch-spec.md` added `multi-slice-batch.json`
  and `multi-slice-batch.md` to plan several safe slices before the V84 human
  gate.
- V82: `docs/v82-execution-receipt-schema-spec.md` added
  `execution-receipt-schema.json`, `execution-receipt-schema.md`, and
  `sample-receipt.json`.
- V83: `docs/v83-runner-receipt-dry-run-spec.md` added
  `runner-receipt.json` and `runner-receipt.md` with `executed: false`.
- V84: `docs/v84-installed-surface-audit-spec.md` added
  `installed-surface-audit.json` and `installed-surface-audit.md` to verify
  the active local skill path before execution.
- V85: `docs/v85-workflow-activation-spec.md` added
  `workflow-activation.json` and `workflow-activation.md` to decide whether the
  next safe action is workflow design.
- V86: `docs/v86-keelplane-brand-spec.md` set **Depone** as the public
  product brand while preserving DWM Core and preparing the later `depone`
  skill-name migration.
- V87: `docs/v87-brand-boundary-audit-spec.md` added
  `brand-boundary-audit.json` and `brand-boundary-audit.md` to keep public
  Depone naming, DWM Core internals, and the skill-name boundary from
  drifting.
- V88: `docs/v88-roadmap-reconciliation-spec.md` added
  `roadmap-reconciliation.json` and `roadmap-reconciliation.md` to keep
  `docs/spec.md`, `docs/automation-roadmap.md`, and this release history
  aligned with implementation truth.
- V89: `docs/v89-command-safety-spec.md` added shared command-safety inference
  so V75/V76/V77 no longer rely on candidate-declared `risk_codes` alone.
- V90: `docs/v90-workflow-activation-v2-spec.md` added product-evidence
  activation so V87/V88/V89 gates feed the next-workflow readiness decision.
- V91: `docs/v91-contract-tiering-spec.md` added smoke, changed-surface, and
  full contract tiers while keeping full release verification as the publish
  boundary.
- V92: `docs/v92-evidence-oracle-spec.md` added read-only artifact assertions
  for JSON fields, text evidence, missing artifacts, and source-hash drift.
- V93: `docs/v93-workflow-narrative-spec.md` added the Depone Control Deck
  renderer for artifact-backed chart, gate, activation, oracle, and next-move
  status.
- V94: `docs/v94-control-deck-score-spec.md` added operator-readiness scoring
  for Control Deck signals without claiming benchmark or upward trend progress.
- V95: `docs/v95-control-deck-score-history-spec.md` added internal readiness
  history and SVG rendering for Control Deck scores without creating a public
  benchmark graph.
- V96: `docs/v96-metric-ladder-spec.md` added graph claim-level assessment for
  process, operator-readiness, and public-benchmark metric levels.
- V97: `docs/v97-benchmark-readiness-spec.md` added an internal benchmark
  readiness report while keeping README benchmark publication behind promotion
  evidence and human review.
- V98: `docs/v98-wave-operator-spec.md` added source-only next-wave selection
  from benchmark readiness and activation evidence.
- V99: `docs/v99-wave-receipt-spec.md` added source-only receipt validation
  for the selected dogfood evidence wave.
- V100: `docs/v100-promotion-evidence-spec.md` added source-only promotion
  evidence recording before any README graph publication review.
- V101: `docs/v101-promotion-route-spec.md` added source-only routing from
  promotion evidence to dogfood acquisition planning or a human gate.
- V102: `docs/v102-live-proof-1-spec.md` added a deterministic live-proof
  recorder and fixture gate for one bounded Codex-backed attempt. The first
  live n=1 Codex execution is recorded in
  `docs/releases/v102-live-proof-1.md` with `decision: live-proof-pass`,
  red-green verification, and approved independent review.
- V103: `docs/v103-live-proof-2-spec.md` added a deterministic two-arm
  comparison schema for direct-codex versus dwm-controlled evidence richness.
  The live comparison remains opt-in and makes no pass-rate, speed, cost, or
  direct-agent superiority claim.
- V104: `docs/v104-product-direction-spec.md` repositioned Depone as a
  workflow designer plus cross-platform evidence verifier above existing agent
  execution engines.
- V105: `docs/v105-verify-wedge-spec.md` added deterministic evidence-contract
  wedge fixtures for missing logs, forbidden touches, test weakening, missing
  root contracts, nested control-file shadows, and a clean verified case.
- V106: `docs/v106-multi-wave-spec.md` added optional `first_wave` and `waves`
  validation while preserving legacy `first_slice` compatibility.
- V107: `docs/v107-agent-fabric-control-plane-spec.md` added the Agent Fabric
  contract direction and the deterministic contract/compiler slice:
  role/toolbelt/profile/harness/compile-report/invocation/result validators,
  `compile_agent_fabric(...)`, and self-tests for exact, approximated, and
  unsupported-critical tool mappings without live model execution.
- V108: `docs/v108-agent-fabric-reference-adapter-spec.md` added the first
  fixture-only shell reference adapter shape for self-report, diff/touched-file
  summary, test output, and command receipts while keeping all adapter material
  at `A0-claims-only`.
- V109: `docs/v109-agent-fabric-capture-bridge-spec.md` added a passive capture
  manifest bridge with explicit `A0-claims-only` and `A1-local-observed`
  assurance labels plus fail-closed tamper, stale-source, and unexpected-file
  checks.
- V110: `docs/v110-agent-fabric-report-assurance-spec.md` surfaced capture
  manifest checks in verification reports with separate `verdict`, `decision`,
  and `assurance` fields.
- V111: `docs/v111-agent-fabric-operator-view-spec.md` documents the
  presentation-only operator-view/exporter for V110 report fields, including
  the `depone verify --operator-view-out` Markdown export path.

## Current Public Boundaries

- Direct-agent superiority is not claimed.
- Process progress is not an upward benchmark claim.
- Generated `out/` directories are verification evidence, not source of truth.
- Benchmark promotion remains gated by history, review, and claim policy.
- Graph timing keeps process progress visible without forcing a public upward
  benchmark graph.
- Benchmark readiness is an internal indicator, not public benchmark
  publication approval.
- Wave selection is source-only and does not execute commands or publish
  benchmark claims.
- Wave receipts are source-only evidence links and do not publish benchmark
  claims.
- README graph visibility must stay aligned with graph timing and overclaim
  blockers.
- Control Deck score history is internal operator readiness history, not public
  benchmark evidence.
- The Metric Ladder treats readiness history as a real operator metric, not a
  public benchmark graph.
- Multi-slice continuation is allowed only for source-only or fixture-only
  work before actual queued command execution.
- Receipt work is allowed through dry-run evidence only; actual execution stays
  behind the V84 human gate.
- Brand boundary audits preserve Depone as the public brand without claiming
  autonomous execution or renaming compatibility surfaces.
- Roadmap reconciliation audits keep spec, roadmap, and release history aligned
  before the next product wave is selected.
- Evidence oracle checks must pass before future scoring or graph promotion can
  treat generated artifacts as support for a claim.
- Workflow narrative labels are status rendering only; artifacts and source
  hashes remain the source of truth.
- Control Deck readiness scores are operator status, not public benchmark
  evidence.
- The V94-V101 meta layer is frozen; V102 records one bounded live proof
  without adding new score, route, or benchmark layers.
- V105 evidence contracts are root-controlled harness evidence, not model claims.
- V106 multi-wave execution paths remain plan contracts only; they do not execute
  agents or relax existing human gates.
- V107 Agent Fabric contracts compile invocation packets and reports only; they
  do not execute live agents or prove productivity, quality, or superiority.
- V108 Agent Fabric reference adapter fixtures do not execute commands or live
  models; their captures remain non-authoritative `A0-claims-only` material.
- V109 Agent Fabric capture manifests can reach `A1-local-observed` only from
  hash-bound Depone observer capture; self-report-only manifests remain A0.
- V110 verification reports may display Agent Fabric assurance, but invalid
  capture manifests fail closed and evidence-contract failures still dominate
  the final verdict.
- V111 operator views may summarize report fields, but they do not create new
  evidence, upgrade assurance, or hide invalid captures and integration risks.
