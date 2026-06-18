# DWM Command Reference

This file keeps the full CLI and artifact reference out of the README. The
README should explain the product; this page preserves operator detail.

## Product Shell

```bash
python scripts/dwm.py plan "<objective>" --out out/v21/<run_id>
python scripts/dwm.py run "<objective>" --out out/v21/<run_id>
python scripts/dwm.py resume --run out/v21/<run_id>
python scripts/dwm.py status --run out/v9/v32-semantic-dogfood
python scripts/dwm.py next --run out/v9/v32-semantic-dogfood
python scripts/dwm.py doctor
python scripts/dwm.py commands --kind product
python scripts/check_contract.py
python scripts/check_readme_quality.py README.md
python scripts/dwm.py commands --kind release
```

## Demo

```bash
python scripts/dwm_demo.py run --out out/demo/quickstart
python scripts/dwm_demo.py inspect --demo out/demo/quickstart
```

Demo artifacts include `demo.json`, `status.json`, `README.md`,
`demo-inspect.json`, `demo-summary.md`, and `out/demo/quickstart`.

## Benchmark and Live Evidence

```bash
python scripts/dwm_benchmark.py corpus
python scripts/dwm_benchmark.py claim --min-margin 8
python scripts/dwm_live_benchmark.py capture --out out/benchmarks-live/<capture_id>
python scripts/dwm_live_attempt_plan.py plan --adapter-command codex --task-id failing-test-fix --out out/live-attempt-plans/<plan_id>
python scripts/dwm_live_runner_preflight.py preflight --plan out/live-attempt-plans/<plan_id> --out out/live-runner-preflight/<preflight_id>
python scripts/dwm_live_receipt.py ingest --preflight out/live-runner-preflight/<preflight_id> --receipt receipt.json --out out/live-receipts/<receipt_id>
python scripts/dwm_live_report.py publish --review out/live-score-reviews/<review_id> --out out/live-reports/<report_id>
python scripts/dwm_readme_benchmark_graph.py generate --report out/live-reports/<report_id> --out out/readme-benchmark-graphs/<graph_id>
python scripts/dwm_benchmark_snapshot.py record --report out/live-reports/<report_id> --release-id <release_id> --out out/benchmark-snapshots/<snapshot_id>
python scripts/dwm_benchmark_series.py build --snapshot-root out/benchmark-snapshots --out out/benchmark-series/<series_id>
python scripts/dwm_benchmark_candidate.py make --series out/benchmark-series/<series_id> --out out/benchmark-candidates/<candidate_id>
python scripts/dwm_benchmark_candidate_review.py review --candidate out/benchmark-candidates/<candidate_id> --out out/benchmark-candidate-reviews/<review_id>
python scripts/dwm_readme_asset_promotion.py promote --review out/benchmark-candidate-reviews/<review_id> --out out/readme-asset-promotions/<promotion_id>
python scripts/dwm_benchmark_history.py build --report out/live-reports/<report_id> --out out/benchmark-history/<history_id>
python scripts/dwm_benchmark_promotion.py promote --history out/benchmark-history/<history_id> --out out/benchmark-promotions/<promotion_id>
```

Benchmark artifacts include `report.json.graph_metrics`,
`benchmark-graph.json`, `benchmark-graph.svg`, `readme-snippet.md`,
`history.json`, `trend.svg`, `promotion.json`, `promoted-trend.svg`,
`snapshot.json`, `series.json`, `candidate.json`, `candidate-review.json`,
`publish-checklist.md`, `asset-promotion.json`, and `asset-diff.md`.

## Dogfood and Process Progress

```bash
python scripts/dwm_workflow_queue.py create --packets packets.json --out out/workflow-queues/<queue_id>
python scripts/dwm_workflow_queue.py resume --queue out/workflow-queues/<queue_id>
python scripts/dwm_dogfood_corpus.py record --out out/dogfood-corpus/<corpus_id>
python scripts/dwm_dogfood_attempts.py record --corpus out/dogfood-corpus/<corpus_id> --attempts attempts.json --out out/dogfood-attempts/<attempt_id>
python scripts/dwm_dogfood_measure.py sample --out out/dogfood-measurements/<measurement_id>
python scripts/dwm_dogfood_pair.py pair --dwm-measure out/dogfood-measurements/<measurement_id> --direct-receipt direct-receipt.json --out out/dogfood-pairs/<pair_id>
python scripts/dwm_dogfood_pair_series.py build --pair-root out/dogfood-pairs --out out/dogfood-pair-series/<series_id>
python scripts/dwm_dogfood_chart_candidate.py candidate --series out/dogfood-pair-series/<series_id> --out out/dogfood-chart-candidates/<chart_id>
python scripts/dwm_dogfood_chart_review.py review --candidate out/dogfood-chart-candidates/<chart_id> --receipt review-receipt.json --out out/dogfood-chart-reviews/<review_id>
python scripts/dwm_dogfood_acquire.py acquire --task-id <task_id> --out out/dogfood-acquisitions/<acquisition_id>
python scripts/dwm_dogfood_operator.py recommend --out out/dogfood-operator/<operator_id>
python scripts/dwm_dogfood_pair_select.py select --pair-root out/dogfood-pairs --out out/dogfood-pair-selections/<selection_id>
python scripts/dwm_dogfood_chart_render.py render --review out/dogfood-chart-reviews/<review_id> --out out/dogfood-chart-renders/<render_id>
python scripts/dwm_dogfood_progress.py build --out out/dogfood-progress/<progress_id>
python scripts/dwm_dogfood_progress_asset_promotion.py promote --progress out/dogfood-progress/<progress_id> --out out/dogfood-progress-asset-promotions/<promotion_id>
python scripts/dwm_daily_operator.py today --corpus out/dogfood-corpus/<corpus_id> --out out/daily-operator/<operator_id>
```

Dogfood artifacts include `queue.json`, `next-action.md`,
`dogfood-corpus.json`, `queue-packets.json`, `dogfood-attempts.json`,
`comparison-ledger.json`, `measurement.json`, `attempts.json`,
`comparison-pair.json`, `comparison-pair.md`, `pair-status.json`,
`pair-series.json`, `pair-series.md`, `graph-readiness.json`,
`chart-candidate.json`, `chart-candidate.md`, `chart-data.csv`,
`chart-review.json`, `chart-review.md`, `acquisition.json`, `acquisition.md`,
`direct-receipt-template.json`, `dogfood-operator.json`,
`dogfood-operator.md`, `pair-selection.json`, `pair-selection.md`,
`chart-render.json`, `chart-render.svg`, `chart-render.md`,
`dogfood-progress.json`, `dogfood-progress.svg`, `dogfood-progress.md`,
`dwm-dogfood-progress.svg`, and `dwm-dogfood-progress.json`.

## Role, HUD, Install, Adapter, and Release

```bash
python scripts/dwm_roles.py registry
python scripts/dwm_hud.py approve --hud out/hud/<hud_id> --out out/hud/<approval_id> --approver <name>
python scripts/dwm_install.py validate
python scripts/dwm_adapters.py registry
python scripts/dwm_adapters.py parity --out out/adapters/<parity_id>
python scripts/dwm_adapter_live_matrix.py matrix --out out/adapter-live-matrix/<matrix_id>
python scripts/dwm_release_candidate.py cut --parity out/adapters/<parity_id> --operator out/daily-operator/<operator_id> --out out/release-candidates/<candidate_id>
python scripts/dwm_release.py status --out out/release/<release_id>
python scripts/dwm_release_timing.py plan --out out/release-timing/<timing_id>
python scripts/dwm_release_timing.py measure --limit 3 --out out/release-timing/<timing_id>
python scripts/dwm_release_timing_history.py build --timing-root out/release-timing --out out/release-timing-history/<history_id>
python scripts/dwm_large_workflow_control.py assess --workflow workflow.json --out out/large-workflow-control/<control_id>
python scripts/dwm_large_workflow_dogfood.py record --run out/v9/v32-semantic-dogfood --out out/large-workflow-dogfood/<dogfood_id>
python scripts/dwm_large_workflow_next.py select --control out/large-workflow-dogfood/v74-canonical/dogfood-control.json --out out/large-workflow-next/<next_id>
python scripts/dwm_large_workflow_queue_bridge.py bridge --selection out/large-workflow-next/v75-canonical/large-workflow-next.json --out out/large-workflow-queue-bridge/<bridge_id> --queue-out out/workflow-queues/<queue_id>
python scripts/dwm_large_workflow_queue_preflight.py preflight --queue out/workflow-queues/v76-canonical/queue.json --out out/large-workflow-queue-preflight/<preflight_id>
python scripts/dwm_graph_timing_gate.py check --progress out/dogfood-progress/local-v66-current/dogfood-progress.json --readiness out/dogfood-pair-series/local-v64-selected-series/graph-readiness.json --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --out out/graph-timing/<timing_id>
python scripts/dwm_readme_graph_visibility.py audit --readme README.md --timing out/graph-timing/v78-canonical/graph-timing.json --out out/readme-graph-visibility/<visibility_id>
python scripts/dwm_continuation_boundary.py assess --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --timing out/graph-timing/v78-canonical/graph-timing.json --visibility out/readme-graph-visibility/v79-canonical/readme-graph-visibility.json --out out/continuation-boundaries/<boundary_id>
python scripts/dwm_multi_slice_batch.py plan --boundary out/continuation-boundaries/v80-canonical/continuation-boundary.json --out out/multi-slice-batches/<batch_id>
python scripts/dwm_execution_receipt_schema.py preflight --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/execution-receipt-schemas/<schema_id>
python scripts/dwm_runner_receipt_dry_run.py dry-run --schema out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/runner-receipt-dry-runs/<dry_run_id>
```

Release artifacts include `operator-loop.json`, `today.md`,
`adapter-parity.json`, `adapter-parity.md`, `adapter-live-matrix.json`,
`adapter-live-matrix.md`, `release-candidate.json`, `release-notes.md`, and
`release-checklist.md`, `release-timing.json`, `release-timing.md`,
`timing-history.json`, `timing-history.md`, `large-workflow-control.json`,
`large-workflow-control.md`, `dogfood-control.json`, `dogfood-control.md`,
`large-workflow-next.json`, `large-workflow-next.md`, `queue-bridge.json`,
`queue-packets.json`, `queue-bridge.md`, `queue-preflight.json`,
`queue-preflight.md`, `graph-timing.json`, `graph-timing.md`, and
`readme-graph-visibility.json`, `readme-graph-visibility.md`, and
`continuation-boundary.json`, `continuation-boundary.md`,
`multi-slice-batch.json`, `multi-slice-batch.md`,
`execution-receipt-schema.json`, `execution-receipt-schema.md`,
`sample-receipt.json`, `runner-receipt.json`, `runner-receipt.md`, and
`status.json`.

## Repository Map

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Codex skill entrypoint and workflow design contract. |
| `scripts/dwm.py` | Product CLI for status, next actions, doctor, and command discovery. |
| `scripts/dwm_demo.py` | Canonical local demo and inspect summary without live adapters. |
| `scripts/check_contract.py` | Release contract smoke and documentation consistency check. |
| `scripts/compile_workflow.py` | First-slice packet compiler. |
| `scripts/dwm_runner.py` | Runner, session/worktree, review/repair, and fanout surfaces. |
| `scripts/dwm_live_*.py` | Live evidence, receipt, score, review, report, and graph gates. |
| `scripts/dwm_benchmark_snapshot.py` | Release benchmark snapshot recorder. |
| `scripts/dwm_benchmark_series.py` | Release snapshot series builder. |
| `scripts/dwm_benchmark_candidate.py` | Promotion-ready benchmark publish candidate workflow. |
| `scripts/dwm_benchmark_candidate_review.py` | Benchmark candidate review gate before README asset promotion. |
| `scripts/dwm_readme_asset_promotion.py` | README benchmark asset promotion bundle and diff summary. |
| `scripts/dwm_workflow_queue.py` | Long-run workflow queue and next safe action selector. |
| `scripts/dwm_dogfood_corpus.py` | Local dogfood task corpus recorder with comparison placeholders. |
| `scripts/dwm_dogfood_attempts.py` | Measured local dogfood comparison ledger. |
| `scripts/dwm_dogfood_measure.py` | Measured local dogfood sample runner. |
| `scripts/dwm_dogfood_pair.py` | Human-gated direct Codex versus DWM comparison pair. |
| `scripts/dwm_dogfood_pair_series.py` | Dogfood pair series and graph-readiness gate. |
| `scripts/dwm_dogfood_chart_candidate.py` | Local dogfood chart candidate gate. |
| `scripts/dwm_dogfood_chart_review.py` | Human-reviewed local dogfood chart gate. |
| `scripts/dwm_dogfood_acquire.py` | One-command dogfood evidence acquisition loop. |
| `scripts/dwm_dogfood_operator.py` | Next dogfood acquisition recommendation loop. |
| `scripts/dwm_dogfood_pair_select.py` | Clean pair-root selector for duplicate task pairs. |
| `scripts/dwm_dogfood_chart_render.py` | Reviewed local dogfood chart renderer. |
| `scripts/dwm_dogfood_progress.py` | Dogfood evidence process progress graph. |
| `scripts/dwm_dogfood_progress_asset_promotion.py` | Reviewable README asset bundle for the dogfood process graph. |
| `scripts/dwm_graph_timing_gate.py` | Graph timing gate that separates process progress visibility from public benchmark trends. |
| `scripts/dwm_readme_graph_visibility.py` | README graph visibility audit aligned with V78 graph timing. |
| `scripts/dwm_continuation_boundary.py` | Continuation boundary gate for source-only multi-slice work. |
| `scripts/dwm_multi_slice_batch.py` | Plan-only multi-slice batch planner before the V84 human gate. |
| `scripts/dwm_execution_receipt_schema.py` | Execution receipt schema preflight before actual queued execution. |
| `scripts/dwm_runner_receipt_dry_run.py` | Fixture-only runner receipt dry-run gate with `executed: false`. |
| `scripts/dwm_daily_operator.py` | Daily operator loop for ready, blocked, and freshness state. |
| `scripts/dwm_adapters.py` | Adapter registry, normalized evidence, and parity matrix checks. |
| `scripts/dwm_adapter_live_matrix.py` | Local adapter command availability and auth-assumption matrix. |
| `scripts/dwm_release_candidate.py` | Release candidate cut from parity and operator evidence. |
| `scripts/dwm_benchmark_history.py` | Benchmark history ledger and trend graph builder. |
| `scripts/dwm_benchmark_promotion.py` | Benchmark trend promotion gate for public graph claims. |
| `docs/spec.md` | Product spec and release criteria. |
| `docs/automation-roadmap.md` | Implementation roadmap and completed slices. |
| `docs/github-research.md` | Prior-art survey. |
| `docs/v12-to-v20-final-roadmap.md` | Final-product roadmap. |
| `docs/command-reference.md` | Full command and artifact reference. |
| `docs/release-history.md` | Versioned implementation history. |
| `fixtures/` | Deterministic manifests used by release gates. |
| `assets/` | Tracked README visuals and published benchmark graph snapshots. |

Tracked assets include `assets/dwm-hero.svg`,
`assets/dwm-live-benchmark.svg`, `assets/dwm-live-benchmark.json`,
`assets/dwm-dogfood-progress.svg`, and `assets/dwm-dogfood-progress.json`.
