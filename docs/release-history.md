# DWM Release History

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

## Current Public Boundaries

- Direct-agent superiority is not claimed.
- Process progress is not an upward benchmark claim.
- Generated `out/` directories are verification evidence, not source of truth.
- Benchmark promotion remains gated by history, review, and claim policy.
- Graph timing keeps process progress visible without forcing a public upward
  benchmark graph.
- README graph visibility must stay aligned with graph timing and overclaim
  blockers.
- Multi-slice continuation is allowed only for source-only or fixture-only
  work before actual queued command execution.
- Receipt work is allowed through dry-run evidence only; actual execution stays
  behind the V84 human gate.
