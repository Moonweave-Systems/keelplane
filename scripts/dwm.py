#!/usr/bin/env python3
"""DWM product CLI for status, product shell, doctor, and command discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "out"
DEFAULT_RUN = OUT_ROOT / "v9" / "v32-semantic-dogfood"
SHELL_ROOT = OUT_ROOT / "v21"
SHELL_SENTINEL = ".dwm_shell-owned.json"
SHELL_VERSION = "21.0.0"

RELEASE_COMMANDS = [
    "python scripts/quick_validate_skill.py .",
    "python scripts/quick_validate_skill.py --self-test",
    "python scripts/check_contract.py",
    "python scripts/check_contract.py --self-test",
    "python scripts/check_contract.py --tier smoke",
    "python scripts/check_contract.py --tier changed",
    "python scripts/evaluate_plan.py --self-test",
    "python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5",
    "python scripts/compile_workflow.py --self-test",
    "python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final",
    "python scripts/execute_packet.py --self-test",
    "python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final",
    "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
    "python scripts/dwm_runner.py --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final",
    "python scripts/dwm_runner.py session --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v14/manifest.json --out out/v13/v14-final",
    "python scripts/dwm_runner.py review --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v15/manifest.json --out out/v13/v15-final",
    "python scripts/dwm_runner.py fanout --self-test",
    "python scripts/dwm_runner.py --manifest fixtures/v16/manifest.json --out out/v13/v16-final",
    "python scripts/dwm_hud.py --self-test",
    "python scripts/dwm_hud.py --manifest fixtures/v17/manifest.json --out out/hud/v17-final",
    "python scripts/dwm_install.py --self-test",
    "python scripts/dwm_install.py --manifest fixtures/v18/manifest.json --out out/install/v18-final",
    "python scripts/dwm_adapters.py --self-test",
    "python scripts/dwm_adapters.py --manifest fixtures/v19/manifest.json --out out/adapters/v19-final",
    "python scripts/dwm_adapters.py --manifest fixtures/v49/manifest.json --out out/adapters/v49-final",
    "python scripts/dwm_release.py --self-test",
    "python scripts/dwm_release.py --manifest fixtures/v20/manifest.json --out out/release/v20-final",
    "python scripts/dwm_review_gate.py --self-test",
    "python scripts/dwm_review_gate.py --manifest fixtures/v20.5/manifest.json --out out/release-review/v20.5-final",
    "python scripts/dwm_dogfood_replay.py --self-test",
    "python scripts/dwm_dogfood_replay.py --manifest fixtures/v20.6/manifest.json --out out/dogfood-replay/v20.6-final",
    "python scripts/dwm.py plan \"V21 shell smoke\" --out out/v21/release-plan-smoke --json",
    "python scripts/dwm.py run \"V21 shell smoke\" --out out/v21/release-run-smoke --json",
    "python scripts/dwm.py resume --run out/v21/release-run-smoke --json",
    "python scripts/dwm_roles.py --self-test",
    "python scripts/dwm_roles.py --manifest fixtures/v22/manifest.json --out out/roles/v22-final",
    "python scripts/dwm_benchmark.py --self-test",
    "python scripts/dwm_benchmark.py --manifest fixtures/v23/manifest.json --out out/benchmarks/v23-final",
    "python scripts/dwm_live_benchmark.py --self-test",
    "python scripts/dwm_live_benchmark.py --manifest fixtures/v24/manifest.json --out out/benchmarks-live/v24-final",
    "python scripts/dwm_benchmark_tasks.py --self-test",
    "python scripts/dwm_benchmark_tasks.py --manifest fixtures/v25/manifest.json --out out/benchmark-tasks/v25-final",
    "python scripts/dwm_benchmark_attempts.py --self-test",
    "python scripts/dwm_benchmark_attempts.py --manifest fixtures/v26/manifest.json --out out/benchmark-attempts/v26-final",
    "python scripts/dwm_adapter_smoke.py --self-test",
    "python scripts/dwm_adapter_smoke.py --manifest fixtures/v27/manifest.json --out out/adapter-smoke/v27-final",
    "python scripts/dwm_live_attempt_plan.py --self-test",
    "python scripts/dwm_live_attempt_plan.py --manifest fixtures/v28/manifest.json --out out/live-attempt-plans/v28-final",
    "python scripts/dwm_live_runner_preflight.py --self-test",
    "python scripts/dwm_live_runner_preflight.py --manifest fixtures/v29/manifest.json --out out/live-runner-preflight/v29-final",
    "python scripts/dwm_live_receipt.py --self-test",
    "python scripts/dwm_live_receipt.py --manifest fixtures/v30/manifest.json --out out/live-receipts/v30-final",
    "python scripts/dwm_live_receipt_judge.py --self-test",
    "python scripts/dwm_live_receipt_judge.py --manifest fixtures/v31/manifest.json --out out/live-receipt-judgments/v31-final",
    "python scripts/dwm_live_score.py --self-test",
    "python scripts/dwm_live_score.py --manifest fixtures/v32/manifest.json --out out/live-scores/v32-final",
    "python scripts/dwm_live_score_aggregate.py --self-test",
    "python scripts/dwm_live_score_aggregate.py --manifest fixtures/v33/manifest.json --out out/live-score-aggregates/v33-final",
    "python scripts/dwm_live_score_review.py --self-test",
    "python scripts/dwm_live_score_review.py --manifest fixtures/v34/manifest.json --out out/live-score-reviews/v34-final",
    "python scripts/dwm_live_report.py --self-test",
    "python scripts/dwm_live_report.py --manifest fixtures/v35/manifest.json --out out/live-reports/v35-final",
    "python scripts/dwm_readme_benchmark_graph.py --self-test",
    "python scripts/dwm_readme_benchmark_graph.py --manifest fixtures/v36/manifest.json --out out/readme-benchmark-graphs/v36-final",
    "python scripts/dwm_benchmark_history.py --self-test",
    "python scripts/dwm_benchmark_history.py --manifest fixtures/v38/manifest.json --out out/benchmark-history/v38-final",
    "python scripts/dwm_benchmark_promotion.py --self-test",
    "python scripts/dwm_benchmark_promotion.py --manifest fixtures/v39/manifest.json --out out/benchmark-promotions/v39-final",
    "python scripts/dwm_benchmark_snapshot.py --self-test",
    "python scripts/dwm_benchmark_snapshot.py --manifest fixtures/v40/manifest.json --out out/benchmark-snapshots/v40-final",
    "python scripts/dwm_benchmark_series.py --self-test",
    "python scripts/dwm_benchmark_series.py --manifest fixtures/v41/manifest.json --out out/benchmark-series/v41-final",
    "python scripts/dwm_benchmark_candidate.py --self-test",
    "python scripts/dwm_benchmark_candidate.py --manifest fixtures/v42/manifest.json --out out/benchmark-candidates/v42-final",
    "python scripts/dwm_benchmark_candidate_review.py --self-test",
    "python scripts/dwm_benchmark_candidate_review.py --manifest fixtures/v44/manifest.json --out out/benchmark-candidate-reviews/v44-final",
    "python scripts/dwm_readme_asset_promotion.py --self-test",
    "python scripts/dwm_readme_asset_promotion.py --manifest fixtures/v45/manifest.json --out out/readme-asset-promotions/v45-final",
    "python scripts/dwm_workflow_queue.py --self-test",
    "python scripts/dwm_workflow_queue.py --manifest fixtures/v46/manifest.json --out out/workflow-queues/v46-final",
    "python scripts/dwm_dogfood_corpus.py --self-test",
    "python scripts/dwm_dogfood_corpus.py --manifest fixtures/v47/manifest.json --out out/dogfood-corpus/v47-final",
    "python scripts/dwm_dogfood_attempts.py --self-test",
    "python scripts/dwm_dogfood_attempts.py --manifest fixtures/v54/manifest.json --out out/dogfood-attempts/v54-final",
    "python scripts/dwm_dogfood_measure.py --self-test",
    "python scripts/dwm_dogfood_measure.py --manifest fixtures/v56/manifest.json --out out/dogfood-measurements/v56-final",
    "python scripts/dwm_dogfood_pair.py --self-test",
    "python scripts/dwm_dogfood_pair.py --manifest fixtures/v57/manifest.json --out out/dogfood-pairs/v57-final",
    "python scripts/dwm_dogfood_pair_series.py --self-test",
    "python scripts/dwm_dogfood_pair_series.py --manifest fixtures/v58/manifest.json --out out/dogfood-pair-series/v58-final",
    "python scripts/dwm_dogfood_chart_candidate.py --self-test",
    "python scripts/dwm_dogfood_chart_candidate.py --manifest fixtures/v59/manifest.json --out out/dogfood-chart-candidates/v59-final",
    "python scripts/dwm_dogfood_chart_review.py --self-test",
    "python scripts/dwm_dogfood_chart_review.py --manifest fixtures/v60/manifest.json --out out/dogfood-chart-reviews/v60-final",
    "python scripts/dwm_dogfood_acquire.py --self-test",
    "python scripts/dwm_dogfood_acquire.py --manifest fixtures/v61/manifest.json --out out/dogfood-acquisitions/v61-final",
    "python scripts/dwm_dogfood_operator.py --self-test",
    "python scripts/dwm_dogfood_operator.py --manifest fixtures/v62/manifest.json --out out/dogfood-operator/v62-final",
    "python scripts/dwm_dogfood_operator.py --self-test",
    "python scripts/dwm_dogfood_operator.py --manifest fixtures/v63/manifest.json --out out/dogfood-operator/v63-final",
    "python scripts/dwm_dogfood_pair_select.py --self-test",
    "python scripts/dwm_dogfood_pair_select.py --manifest fixtures/v64/manifest.json --out out/dogfood-pair-selections/v64-final",
    "python scripts/dwm_dogfood_chart_render.py --self-test",
    "python scripts/dwm_dogfood_chart_render.py --manifest fixtures/v65/manifest.json --out out/dogfood-chart-renders/v65-final",
    "python scripts/dwm_dogfood_progress.py --self-test",
    "python scripts/dwm_dogfood_progress.py --manifest fixtures/v66/manifest.json --out out/dogfood-progress/v66-final",
    "python scripts/dwm_dogfood_progress_asset_promotion.py --self-test",
    "python scripts/dwm_dogfood_progress_asset_promotion.py --manifest fixtures/v67/manifest.json --out out/dogfood-progress-asset-promotions/v67-final",
    "python scripts/check_readme_quality.py --self-test",
    "python scripts/check_readme_quality.py README.md",
    "python scripts/dwm_release_timing.py --self-test",
    "python scripts/dwm_release_timing.py --manifest fixtures/v71/manifest.json --out out/release-timing/v71-final",
    "python scripts/dwm_release_timing_history.py --self-test",
    "python scripts/dwm_release_timing_history.py --manifest fixtures/v72/manifest.json --out out/release-timing-history/v72-final",
    "python scripts/dwm_large_workflow_control.py --self-test",
    "python scripts/dwm_large_workflow_control.py --manifest fixtures/v73/manifest.json --out out/large-workflow-control/v73-final",
    "python scripts/evaluate_plan.py --plan docs/v73-large-workflow-control.workflow.plan.json",
    "python scripts/dwm_large_workflow_dogfood.py --self-test",
    "python scripts/dwm_large_workflow_dogfood.py --manifest fixtures/v74/manifest.json --out out/large-workflow-dogfood/v74-final",
    "python scripts/dwm_large_workflow_dogfood.py record --run out/v9/v32-semantic-dogfood --out out/large-workflow-dogfood/v74-canonical",
    "python scripts/dwm_large_workflow_next.py --self-test",
    "python scripts/dwm_large_workflow_next.py --manifest fixtures/v75/manifest.json --out out/large-workflow-next/v75-final",
    "python scripts/dwm_large_workflow_next.py select --control out/large-workflow-dogfood/v74-canonical/dogfood-control.json --out out/large-workflow-next/v75-canonical",
    "python scripts/dwm_large_workflow_queue_bridge.py --self-test",
    "python scripts/dwm_large_workflow_queue_bridge.py --manifest fixtures/v76/manifest.json --out out/large-workflow-queue-bridge/v76-final",
    "python scripts/dwm_large_workflow_queue_bridge.py bridge --selection out/large-workflow-next/v75-canonical/large-workflow-next.json --out out/large-workflow-queue-bridge/v76-canonical --queue-out out/workflow-queues/v76-canonical",
    "python scripts/dwm_large_workflow_queue_preflight.py --self-test",
    "python scripts/dwm_large_workflow_queue_preflight.py --manifest fixtures/v77/manifest.json --out out/large-workflow-queue-preflight/v77-final",
    "python scripts/dwm_large_workflow_queue_preflight.py preflight --queue out/workflow-queues/v76-canonical/queue.json --out out/large-workflow-queue-preflight/v77-canonical",
    "python scripts/dwm_graph_timing_gate.py --self-test",
    "python scripts/dwm_graph_timing_gate.py --manifest fixtures/v78/manifest.json --out out/graph-timing/v78-final",
    "python scripts/dwm_graph_timing_gate.py check --progress out/dogfood-progress/local-v66-current/dogfood-progress.json --readiness out/dogfood-pair-series/local-v64-selected-series/graph-readiness.json --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --out out/graph-timing/v78-canonical",
    "python scripts/dwm_readme_graph_visibility.py --self-test",
    "python scripts/dwm_readme_graph_visibility.py --manifest fixtures/v79/manifest.json --out out/readme-graph-visibility/v79-final",
    "python scripts/dwm_readme_graph_visibility.py audit --readme README.md --timing out/graph-timing/v78-canonical/graph-timing.json --out out/readme-graph-visibility/v79-canonical",
    "python scripts/dwm_continuation_boundary.py --self-test",
    "python scripts/dwm_continuation_boundary.py --manifest fixtures/v80/manifest.json --out out/continuation-boundaries/v80-final",
    "python scripts/dwm_continuation_boundary.py assess --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --timing out/graph-timing/v78-canonical/graph-timing.json --visibility out/readme-graph-visibility/v79-canonical/readme-graph-visibility.json --out out/continuation-boundaries/v80-canonical",
    "python scripts/dwm_multi_slice_batch.py --self-test",
    "python scripts/dwm_multi_slice_batch.py --manifest fixtures/v81/manifest.json --out out/multi-slice-batches/v81-final",
    "python scripts/dwm_multi_slice_batch.py plan --boundary out/continuation-boundaries/v80-canonical/continuation-boundary.json --out out/multi-slice-batches/v81-canonical",
    "python scripts/dwm_execution_receipt_schema.py --self-test",
    "python scripts/dwm_execution_receipt_schema.py --manifest fixtures/v82/manifest.json --out out/execution-receipt-schemas/v82-final",
    "python scripts/dwm_execution_receipt_schema.py preflight --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/execution-receipt-schemas/v82-canonical",
    "python scripts/dwm_runner_receipt_dry_run.py --self-test",
    "python scripts/dwm_runner_receipt_dry_run.py --manifest fixtures/v83/manifest.json --out out/runner-receipt-dry-runs/v83-final",
    "python scripts/dwm_runner_receipt_dry_run.py dry-run --schema out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/runner-receipt-dry-runs/v83-canonical",
    "python scripts/dwm_installed_surface_audit.py --self-test",
    "python scripts/dwm_installed_surface_audit.py --manifest fixtures/v84/manifest.json --out out/installed-surface-audits/v84-final",
    "python scripts/dwm_installed_surface_audit.py audit --active-skill SKILL.md --out out/installed-surface-audits/v84-canonical",
    "python scripts/dwm_workflow_activation.py --self-test",
    "python scripts/dwm_workflow_activation.py --manifest fixtures/v85/manifest.json --out out/workflow-activations/v85-final",
    "python scripts/dwm_workflow_activation.py activate --audit out/installed-surface-audits/v84-canonical/installed-surface-audit.json --receipt out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json --status out/v9/v32-semantic-dogfood/status.json --out out/workflow-activations/v85-canonical",
    "python scripts/dwm_brand_boundary_audit.py --self-test",
    "python scripts/dwm_brand_boundary_audit.py --manifest fixtures/v87/manifest.json --out out/brand-boundary-audits/v87-final",
    "python scripts/dwm_brand_boundary_audit.py audit --out out/brand-boundary-audits/v87-canonical",
    "python scripts/dwm_roadmap_reconciliation.py --self-test",
    "python scripts/dwm_roadmap_reconciliation.py --manifest fixtures/v88/manifest.json --out out/roadmap-reconciliations/v88-final",
    "python scripts/dwm_roadmap_reconciliation.py audit --out out/roadmap-reconciliations/v88-canonical",
    "python scripts/dwm_command_safety.py --self-test",
    "python scripts/dwm_command_safety.py --manifest fixtures/v89/manifest.json --out out/command-safety/v89-final",
    "python scripts/dwm_workflow_activation.py --manifest fixtures/v90/manifest.json --out out/workflow-activations/v90-final",
    "python scripts/dwm_workflow_activation.py activate --audit out/installed-surface-audits/v84-canonical/installed-surface-audit.json --receipt out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json --status out/v9/v32-semantic-dogfood/status.json --brand-audit out/brand-boundary-audits/v87-canonical/brand-boundary-audit.json --roadmap-reconciliation out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --out out/workflow-activations/v90-canonical",
    "python scripts/dwm_evidence_oracle.py --self-test",
    "python scripts/dwm_evidence_oracle.py --manifest fixtures/v92/manifest.json --out out/evidence-oracles/v92-final",
    "python scripts/dwm_evidence_oracle.py verify --claims fixtures/v92/canonical-claims.json --out out/evidence-oracles/v92-canonical",
    "python scripts/dwm_workflow_narrative.py --self-test",
    "python scripts/dwm_workflow_narrative.py --manifest fixtures/v93/manifest.json --out out/workflow-narratives/v93-final",
    "python scripts/dwm_workflow_narrative.py render --roadmap out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --oracle out/evidence-oracles/v92-canonical/evidence-oracle.json --out out/workflow-narratives/v93-canonical",
    "python scripts/dwm_control_deck_score.py --self-test",
    "python scripts/dwm_control_deck_score.py --manifest fixtures/v94/manifest.json --out out/control-deck-scores/v94-final",
    "python scripts/dwm_control_deck_score.py score --narrative out/workflow-narratives/v93-canonical/workflow-narrative.json --roadmap out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --oracle out/evidence-oracles/v92-canonical/evidence-oracle.json --out out/control-deck-scores/v94-canonical",
    "python scripts/dwm_control_deck_score_history.py --self-test",
    "python scripts/dwm_control_deck_score_history.py --manifest fixtures/v95/manifest.json --out out/control-deck-score-history/v95-final",
    "python scripts/dwm_control_deck_score_history.py build --score out/control-deck-scores/v94-canonical --out out/control-deck-score-history/v95-canonical",
    "python scripts/dwm_metric_ladder.py --self-test",
    "python scripts/dwm_metric_ladder.py --manifest fixtures/v96/manifest.json --out out/metric-ladders/v96-final",
    "python scripts/dwm_metric_ladder.py assess --history out/control-deck-score-history/v95-canonical/control-deck-score-history.json --graph-timing out/graph-timing/v78-canonical/graph-timing.json --out out/metric-ladders/v96-canonical",
    "python scripts/dwm_benchmark_readiness.py --self-test",
    "python scripts/dwm_benchmark_readiness.py --manifest fixtures/v97/manifest.json --out out/benchmark-readiness/v97-final",
    "python scripts/dwm_benchmark_readiness.py assess --ladder out/metric-ladders/v96-canonical/metric-ladder.json --out out/benchmark-readiness/v97-canonical",
    "python scripts/dwm_wave_operator.py --self-test",
    "python scripts/dwm_wave_operator.py --manifest fixtures/v98/manifest.json --out out/wave-operators/v98-final",
    "python scripts/dwm_wave_operator.py select --readiness out/benchmark-readiness/v97-canonical/benchmark-readiness.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --out out/wave-operators/v98-canonical",
    "python scripts/dwm_wave_receipt.py --self-test",
    "python scripts/dwm_wave_receipt.py --manifest fixtures/v99/manifest.json --out out/wave-receipts/v99-final",
    "python scripts/dwm_wave_receipt.py record --wave out/wave-operators/v98-canonical/wave-operator.json --acquisition out/dogfood-acquisitions/v61-final/summary.json --out out/wave-receipts/v99-canonical",
    "python scripts/dwm_promotion_evidence.py --self-test",
    "python scripts/dwm_promotion_evidence.py --manifest fixtures/v100/manifest.json --out out/promotion-evidence/v100-final",
    "python scripts/dwm_promotion_evidence.py record --receipt out/wave-receipts/v99-canonical/wave-receipt.json --readiness out/benchmark-readiness/v97-canonical/benchmark-readiness.json --out out/promotion-evidence/v100-canonical",
    "python scripts/dwm_promotion_route.py --self-test",
    "python scripts/dwm_promotion_route.py --manifest fixtures/v101/manifest.json --out out/promotion-routes/v101-final",
    "python scripts/dwm_promotion_route.py route --evidence out/promotion-evidence/v100-canonical/promotion-evidence.json --out out/promotion-routes/v101-canonical",
    "python scripts/dwm_live_proof.py --self-test",
    "python scripts/dwm_live_proof.py --manifest fixtures/v102/manifest.json --out out/v102/final",
    "python scripts/dwm_live_proof.py --manifest fixtures/v103/manifest.json --out out/v103/final",
    "python scripts/v105_verify_wedge.py --self-test",
    "python scripts/v106_multi_wave.py --self-test",
    "python scripts/dwm_daily_operator.py --self-test",
    "python scripts/dwm_daily_operator.py --manifest fixtures/v48/manifest.json --out out/daily-operator/v48-final",
    "python scripts/dwm_release_candidate.py --self-test",
    "python scripts/dwm_release_candidate.py --manifest fixtures/v50/manifest.json --out out/release-candidates/v50-final",
    "python scripts/dwm_adapter_live_matrix.py --self-test",
    "python scripts/dwm_adapter_live_matrix.py --manifest fixtures/v55/manifest.json --out out/adapter-live-matrix/v55-final",
    "python scripts/dwm_demo.py --self-test",
    "python scripts/dwm_demo.py --manifest fixtures/v51/manifest.json --out out/demo/v51-final",
    "python scripts/dwm_demo.py --manifest fixtures/v53/manifest.json --out out/demo/v53-final",
    "python scripts/run_workflow.py --self-test",
    "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
    "python scripts/orchestrate_workflow.py --self-test",
    "python scripts/dispatch_worker.py --self-test",
    "python scripts/run_worker_result.py --self-test",
    "python scripts/review_worker_result.py --self-test",
    "python scripts/ingest_worker_review.py --self-test",
    "python scripts/dispatch_frontier.py --self-test",
    "python scripts/run_frontier_result.py --self-test",
    "python scripts/review_frontier_result.py --self-test",
    "python scripts/ingest_frontier_review.py --self-test",
    "python scripts/resolve_human_gate.py --self-test",
    "python scripts/dwm.py --self-test",
    "python scripts/check_whitespace.py .",
    "python scripts/check_release_text.py .",
    "python scripts/check_release_text.py --self-test",
]

DOGFOOD_COMMANDS = [
    "python scripts/review_frontier_result.py --result out/v7/v32-semantic-dogfood --out out/v7.5/v32-semantic-dogfood",
    "python scripts/review_frontier_result.py --resume out/v7.5/v32-semantic-dogfood",
    "python scripts/ingest_frontier_review.py --review out/v7.5/v32-semantic-dogfood --out out/v8/v32-semantic-dogfood",
    "python scripts/ingest_frontier_review.py --resume out/v8/v32-semantic-dogfood",
    "python scripts/resolve_human_gate.py --frontier out/v8/v32-semantic-dogfood --approval fixtures/v9/approvals/dogfood-human-approval.json --out out/v9/v32-semantic-dogfood",
    "python scripts/resolve_human_gate.py --resume out/v9/v32-semantic-dogfood",
]

PRODUCT_COMMANDS = [
    "python scripts/dwm.py plan \"<objective>\" --out out/v21/<run_id> --json",
    "python scripts/dwm.py run \"<objective>\" --out out/v21/<run_id> --json",
    "python scripts/dwm.py resume --run out/v21/<run_id> --json",
    "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json",
    "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json",
    "python scripts/dwm.py doctor --json",
    "python scripts/dwm.py commands --kind product --json",
]

BASE_REQUIRED_PATHS = [
    "SKILL.md",
    "README.md",
    "docs/automation-roadmap.md",
    "docs/v10-product-packaging-spec.md",
    "docs/v10-product-packaging.workflow.plan.json",
    "docs/v10-decision.md",
    "docs/v11-operator-guidance-spec.md",
    "docs/v11-operator-guidance.workflow.plan.json",
    "docs/v11-decision.md",
    "docs/v13-decision.md",
    "docs/v14-decision.md",
    "docs/v15-decision.md",
    "docs/v16-decision.md",
    "docs/v17-decision.md",
    "docs/v18-decision.md",
    "docs/v19-decision.md",
    "docs/v20-decision.md",
    "docs/v20-compatibility-matrix.md",
    "docs/v20-migration-rollback.md",
    "docs/v20.5-decision.md",
    "docs/v20.5-reviewer-gate-spec.md",
    "docs/v20.6-decision.md",
    "docs/v20.6-dogfood-replay-spec.md",
    "docs/v21-decision.md",
    "docs/v21-product-shell-spec.md",
    "docs/v22-decision.md",
    "docs/v22-role-pack-spec.md",
    "docs/v23-decision.md",
    "docs/v23-harness-benchmark-spec.md",
    "docs/v24-decision.md",
    "docs/v24-live-benchmark-evidence-spec.md",
    "docs/v25-decision.md",
    "docs/v25-benchmark-task-materializer-spec.md",
    "docs/v26-decision.md",
    "docs/v26-benchmark-attempt-harness-spec.md",
    "docs/v27-decision.md",
    "docs/v27-adapter-smoke-spec.md",
    "docs/v28-decision.md",
    "docs/v28-live-attempt-planner-spec.md",
    "docs/v29-decision.md",
    "docs/v29-live-runner-preflight-spec.md",
    "docs/v30-decision.md",
    "docs/v30-live-receipt-ingestion-spec.md",
    "docs/v31-decision.md",
    "docs/v31-live-receipt-judgment-spec.md",
    "docs/v32-decision.md",
    "docs/v32-live-score-verifier-spec.md",
    "docs/v32-to-v35-live-scoring-workflow.md",
    "docs/v32-to-v35-live-scoring-workflow.plan.json",
    "docs/v33-decision.md",
    "docs/v33-live-score-aggregate-spec.md",
    "docs/v34-decision.md",
    "docs/v34-live-score-review-spec.md",
    "docs/v35-decision.md",
    "docs/v35-live-report-spec.md",
    "docs/v36-decision.md",
    "docs/v36-readme-benchmark-graph-spec.md",
    "docs/v37-decision.md",
    "docs/v37-readme-public-page-spec.md",
    "docs/v38-decision.md",
    "docs/v38-benchmark-history-spec.md",
    "docs/v39-decision.md",
    "docs/v39-benchmark-promotion-spec.md",
    "docs/v40-decision.md",
    "docs/v40-benchmark-snapshot-spec.md",
    "docs/v41-decision.md",
    "docs/v41-benchmark-series-spec.md",
    "docs/v42-decision.md",
    "docs/v42-benchmark-candidate-spec.md",
    "docs/v43-direction-check-roadmap.md",
    "docs/v43-direction-check-roadmap.workflow.plan.json",
    "docs/v44-decision.md",
    "docs/v44-candidate-review-gate-spec.md",
    "docs/v45-decision.md",
    "docs/v45-readme-asset-promotion-spec.md",
    "docs/v46-decision.md",
    "docs/v46-long-run-workflow-queue-spec.md",
    "docs/v47-decision.md",
    "docs/v47-real-dogfood-corpus-spec.md",
    "docs/v48-decision.md",
    "docs/v48-daily-operator-loop-spec.md",
    "docs/v49-decision.md",
    "docs/v49-adapter-parity-matrix-spec.md",
    "docs/v50-decision.md",
    "docs/v50-release-candidate-cut-spec.md",
    "docs/v51-decision.md",
    "docs/v51-canonical-demo-spec.md",
    "docs/v52-decision.md",
    "docs/v52-readme-ux-spec.md",
    "docs/v53-decision.md",
    "docs/v53-demo-inspect-spec.md",
    "docs/v54-decision.md",
    "docs/v54-dogfood-attempts-spec.md",
    "docs/v55-decision.md",
    "docs/v55-adapter-live-matrix-spec.md",
    "docs/v56-decision.md",
    "docs/v56-dogfood-measure-spec.md",
    "docs/v57-decision.md",
    "docs/v57-dogfood-pair-spec.md",
    "docs/v58-decision.md",
    "docs/v58-dogfood-pair-series-spec.md",
    "docs/v59-decision.md",
    "docs/v59-dogfood-chart-candidate-spec.md",
    "docs/v60-decision.md",
    "docs/v60-dogfood-chart-review-spec.md",
    "docs/v61-decision.md",
    "docs/v61-dogfood-acquire-spec.md",
    "docs/v62-decision.md",
    "docs/v62-dogfood-operator-spec.md",
    "docs/v63-decision.md",
    "docs/v63-dogfood-operator-duplicate-root-spec.md",
    "docs/v64-decision.md",
    "docs/v64-dogfood-pair-select-spec.md",
    "docs/v65-decision.md",
    "docs/v65-dogfood-chart-render-spec.md",
    "docs/v66-decision.md",
    "docs/v66-dogfood-progress-spec.md",
    "docs/v67-decision.md",
    "docs/v67-dogfood-progress-asset-promotion-spec.md",
    "docs/v68-decision.md",
    "docs/v68-readme-product-page-spec.md",
    "docs/v69-decision.md",
    "docs/v69-readme-quality-gate-spec.md",
    "docs/v70-decision.md",
    "docs/v70-contract-timeout-spec.md",
    "docs/v71-decision.md",
    "docs/v71-release-timing-spec.md",
    "docs/v72-decision.md",
    "docs/v72-release-timing-history-spec.md",
    "docs/v73-decision.md",
    "docs/v73-large-workflow-control-spec.md",
    "docs/v73-large-workflow-control-blueprint.md",
    "docs/v73-large-workflow-control.workflow.plan.json",
    "docs/v74-decision.md",
    "docs/v74-large-workflow-dogfood-spec.md",
    "docs/v75-decision.md",
    "docs/v75-large-workflow-next-spec.md",
    "docs/v76-decision.md",
    "docs/v76-large-workflow-queue-bridge-spec.md",
    "docs/v77-decision.md",
    "docs/v77-large-workflow-queue-preflight-spec.md",
    "docs/v78-decision.md",
    "docs/v78-graph-timing-gate-spec.md",
    "docs/v79-decision.md",
    "docs/v79-readme-graph-visibility-spec.md",
    "docs/v80-decision.md",
    "docs/v80-continuation-boundary-spec.md",
    "docs/v81-decision.md",
    "docs/v81-multi-slice-batch-spec.md",
    "docs/v82-decision.md",
    "docs/v82-execution-receipt-schema-spec.md",
    "docs/v83-decision.md",
    "docs/v83-runner-receipt-dry-run-spec.md",
    "docs/v84-decision.md",
    "docs/v84-installed-surface-audit-spec.md",
    "docs/v85-decision.md",
    "docs/v85-workflow-activation-spec.md",
    "docs/v86-decision.md",
    "docs/v86-keelplane-brand-spec.md",
    "docs/v87-decision.md",
    "docs/v87-brand-boundary-audit-spec.md",
    "docs/v88-decision.md",
    "docs/v88-roadmap-reconciliation-spec.md",
    "docs/v89-decision.md",
    "docs/v89-command-safety-spec.md",
    "docs/v90-decision.md",
    "docs/v90-workflow-activation-v2-spec.md",
    "docs/v91-decision.md",
    "docs/v91-contract-tiering-spec.md",
    "docs/v92-decision.md",
    "docs/v92-evidence-oracle-spec.md",
    "docs/v93-decision.md",
    "docs/v93-workflow-narrative-spec.md",
    "docs/v94-decision.md",
    "docs/v94-control-deck-score-spec.md",
    "docs/command-reference.md",
    "docs/release-history.md",
    "packaging/dwm-benchmark-attempts.json",
    "packaging/dwm-adapters.json",
    "packaging/dwm-benchmarks.json",
    "packaging/dwm-benchmark-tasks.json",
    "packaging/dwm-package.json",
    "packaging/dwm-roles.json",
    "scripts/dwm.py",
    "scripts/dwm_runner.py",
    "scripts/dwm_hud.py",
    "scripts/dwm_install.py",
    "scripts/dwm_adapters.py",
    "scripts/dwm_release.py",
    "scripts/dwm_review_gate.py",
    "scripts/dwm_dogfood_replay.py",
    "scripts/dwm_roles.py",
    "scripts/dwm_benchmark.py",
    "scripts/dwm_live_benchmark.py",
    "scripts/dwm_benchmark_tasks.py",
    "scripts/dwm_benchmark_attempts.py",
    "scripts/dwm_adapter_smoke.py",
    "scripts/dwm_live_attempt_plan.py",
    "scripts/dwm_live_runner_preflight.py",
    "scripts/dwm_live_receipt.py",
    "scripts/dwm_live_receipt_judge.py",
    "scripts/dwm_live_score.py",
    "scripts/dwm_live_score_aggregate.py",
    "scripts/dwm_live_score_review.py",
    "scripts/dwm_live_report.py",
    "scripts/dwm_readme_benchmark_graph.py",
    "scripts/dwm_benchmark_history.py",
    "scripts/dwm_benchmark_promotion.py",
    "scripts/dwm_benchmark_snapshot.py",
    "scripts/dwm_benchmark_series.py",
    "scripts/dwm_benchmark_candidate.py",
    "scripts/dwm_benchmark_candidate_review.py",
    "scripts/dwm_readme_asset_promotion.py",
    "scripts/dwm_workflow_queue.py",
    "scripts/dwm_dogfood_corpus.py",
    "scripts/dwm_dogfood_attempts.py",
    "scripts/dwm_dogfood_measure.py",
    "scripts/dwm_dogfood_pair.py",
    "scripts/dwm_dogfood_pair_series.py",
    "scripts/dwm_dogfood_chart_candidate.py",
    "scripts/dwm_dogfood_chart_review.py",
    "scripts/dwm_dogfood_acquire.py",
    "scripts/dwm_dogfood_operator.py",
    "scripts/dwm_dogfood_pair_select.py",
    "scripts/dwm_dogfood_chart_render.py",
    "scripts/dwm_dogfood_progress.py",
    "scripts/dwm_dogfood_progress_asset_promotion.py",
    "scripts/check_readme_quality.py",
    "scripts/dwm_release_timing.py",
    "scripts/dwm_release_timing_history.py",
    "scripts/dwm_large_workflow_control.py",
    "scripts/dwm_large_workflow_dogfood.py",
    "scripts/dwm_command_safety.py",
    "scripts/dwm_large_workflow_next.py",
    "scripts/dwm_large_workflow_queue_bridge.py",
    "scripts/dwm_large_workflow_queue_preflight.py",
    "scripts/dwm_graph_timing_gate.py",
    "scripts/dwm_readme_graph_visibility.py",
    "scripts/dwm_continuation_boundary.py",
    "scripts/dwm_multi_slice_batch.py",
    "scripts/dwm_execution_receipt_schema.py",
    "scripts/dwm_runner_receipt_dry_run.py",
    "scripts/dwm_installed_surface_audit.py",
    "scripts/dwm_workflow_activation.py",
    "scripts/dwm_brand_boundary_audit.py",
    "scripts/dwm_roadmap_reconciliation.py",
    "scripts/dwm_evidence_oracle.py",
    "scripts/dwm_workflow_narrative.py",
    "scripts/dwm_control_deck_score.py",
    "scripts/dwm_control_deck_score_history.py",
    "scripts/dwm_metric_ladder.py",
    "scripts/dwm_daily_operator.py",
    "scripts/dwm_adapter_live_matrix.py",
    "fixtures/v49/manifest.json",
    "fixtures/v50/manifest.json",
    "scripts/dwm_release_candidate.py",
    "fixtures/v51/manifest.json",
    "fixtures/v53/manifest.json",
    "scripts/dwm_demo.py",
    "fixtures/v54/manifest.json",
    "docs/v52-decision.md",
    "docs/v52-readme-ux-spec.md",
    "docs/v53-decision.md",
    "docs/v53-demo-inspect-spec.md",
    "docs/v54-decision.md",
    "docs/v54-dogfood-attempts-spec.md",
    "fixtures/v55/manifest.json",
    "docs/v55-decision.md",
    "docs/v55-adapter-live-matrix-spec.md",
    "fixtures/v56/manifest.json",
    "docs/v56-decision.md",
    "docs/v56-dogfood-measure-spec.md",
    "fixtures/v57/manifest.json",
    "docs/v57-decision.md",
    "docs/v57-dogfood-pair-spec.md",
    "fixtures/v58/manifest.json",
    "docs/v58-decision.md",
    "docs/v58-dogfood-pair-series-spec.md",
    "fixtures/v59/manifest.json",
    "docs/v59-decision.md",
    "docs/v59-dogfood-chart-candidate-spec.md",
    "fixtures/v60/manifest.json",
    "docs/v60-decision.md",
    "docs/v60-dogfood-chart-review-spec.md",
    "fixtures/v61/manifest.json",
    "docs/v61-decision.md",
    "docs/v61-dogfood-acquire-spec.md",
    "fixtures/v62/manifest.json",
    "docs/v62-decision.md",
    "docs/v62-dogfood-operator-spec.md",
    "fixtures/v63/manifest.json",
    "docs/v63-decision.md",
    "docs/v63-dogfood-operator-duplicate-root-spec.md",
    "fixtures/v64/manifest.json",
    "docs/v64-decision.md",
    "docs/v64-dogfood-pair-select-spec.md",
    "fixtures/v65/manifest.json",
    "docs/v65-decision.md",
    "docs/v65-dogfood-chart-render-spec.md",
    "fixtures/v66/manifest.json",
    "docs/v66-decision.md",
    "docs/v66-dogfood-progress-spec.md",
    "fixtures/v67/manifest.json",
    "docs/v67-decision.md",
    "docs/v67-dogfood-progress-asset-promotion-spec.md",
    "docs/v68-decision.md",
    "docs/v68-readme-product-page-spec.md",
    "docs/v69-decision.md",
    "docs/v69-readme-quality-gate-spec.md",
    "docs/v70-decision.md",
    "docs/v70-contract-timeout-spec.md",
    "fixtures/v71/manifest.json",
    "docs/v71-decision.md",
    "docs/v71-release-timing-spec.md",
    "fixtures/v72/manifest.json",
    "docs/v72-decision.md",
    "docs/v72-release-timing-history-spec.md",
    "fixtures/v73/manifest.json",
    "docs/v73-decision.md",
    "docs/v73-large-workflow-control-spec.md",
    "docs/v73-large-workflow-control-blueprint.md",
    "docs/v73-large-workflow-control.workflow.plan.json",
    "fixtures/v74/manifest.json",
    "docs/v74-decision.md",
    "docs/v74-large-workflow-dogfood-spec.md",
    "fixtures/v75/manifest.json",
    "docs/v75-decision.md",
    "docs/v75-large-workflow-next-spec.md",
    "fixtures/v76/manifest.json",
    "docs/v76-decision.md",
    "docs/v76-large-workflow-queue-bridge-spec.md",
    "fixtures/v77/manifest.json",
    "docs/v77-decision.md",
    "docs/v77-large-workflow-queue-preflight-spec.md",
    "fixtures/v78/manifest.json",
    "docs/v78-decision.md",
    "docs/v78-graph-timing-gate-spec.md",
    "fixtures/v79/manifest.json",
    "docs/v79-decision.md",
    "docs/v79-readme-graph-visibility-spec.md",
    "fixtures/v80/manifest.json",
    "docs/v80-decision.md",
    "docs/v80-continuation-boundary-spec.md",
    "fixtures/v81/manifest.json",
    "docs/v81-decision.md",
    "docs/v81-multi-slice-batch-spec.md",
    "fixtures/v82/manifest.json",
    "docs/v82-decision.md",
    "docs/v82-execution-receipt-schema-spec.md",
    "fixtures/v83/manifest.json",
    "docs/v83-decision.md",
    "docs/v83-runner-receipt-dry-run-spec.md",
    "fixtures/v84/manifest.json",
    "docs/v84-decision.md",
    "docs/v84-installed-surface-audit-spec.md",
    "fixtures/v85/manifest.json",
    "docs/v85-decision.md",
    "docs/v85-workflow-activation-spec.md",
    "docs/v86-decision.md",
    "docs/v86-keelplane-brand-spec.md",
    "fixtures/v87/manifest.json",
    "docs/v87-decision.md",
    "docs/v87-brand-boundary-audit-spec.md",
    "fixtures/v88/manifest.json",
    "docs/v88-decision.md",
    "docs/v88-roadmap-reconciliation-spec.md",
    "fixtures/v89/manifest.json",
    "docs/v89-decision.md",
    "docs/v89-command-safety-spec.md",
    "fixtures/v90/manifest.json",
    "docs/v90-decision.md",
    "docs/v90-workflow-activation-v2-spec.md",
    "docs/v91-decision.md",
    "docs/v91-contract-tiering-spec.md",
    "fixtures/v92/manifest.json",
    "fixtures/v92/canonical-claims.json",
    "docs/v92-decision.md",
    "docs/v92-evidence-oracle-spec.md",
    "fixtures/v93/manifest.json",
    "docs/v93-decision.md",
    "docs/v93-workflow-narrative-spec.md",
    "fixtures/v94/manifest.json",
    "docs/v94-decision.md",
    "docs/v94-control-deck-score-spec.md",
    "fixtures/v95/manifest.json",
    "docs/v95-decision.md",
    "docs/v95-control-deck-score-history-spec.md",
    "fixtures/v96/manifest.json",
    "docs/v96-decision.md",
    "docs/v96-metric-ladder-spec.md",
    "scripts/dwm_benchmark_readiness.py",
    "fixtures/v97/manifest.json",
    "docs/v97-decision.md",
    "docs/v97-benchmark-readiness-spec.md",
    "scripts/dwm_wave_operator.py",
    "fixtures/v98/manifest.json",
    "docs/v98-decision.md",
    "docs/v98-wave-operator-spec.md",
    "scripts/dwm_wave_receipt.py",
    "fixtures/v99/manifest.json",
    "docs/v99-decision.md",
    "docs/v99-wave-receipt-spec.md",
    "scripts/dwm_promotion_evidence.py",
    "fixtures/v100/manifest.json",
    "docs/v100-decision.md",
    "docs/v100-promotion-evidence-spec.md",
    "scripts/dwm_promotion_route.py",
    "fixtures/v101/manifest.json",
    "docs/v101-decision.md",
    "docs/v101-promotion-route-spec.md",
    "scripts/dwm_live_proof.py",
    "fixtures/v102/manifest.json",
    "fixtures/live-proof/live-proof-1.workflow.plan.json",
    "fixtures/live-proof/seed/live_math.py",
    "fixtures/live-proof/seed/test_live_math.py",
    "docs/v102-decision.md",
    "docs/v102-live-proof-1-spec.md",
    "fixtures/v103/manifest.json",
    "docs/v103-decision.md",
    "docs/v103-live-proof-2-spec.md",
    "scripts/v105_verify_wedge.py",
    "fixtures/v105-verify-wedge/cases.json",
    "fixtures/v105-verify-wedge/plan.json",
    "docs/v105-decision.md",
    "docs/v105-verify-wedge-spec.md",
    "scripts/v106_multi_wave.py",
    "fixtures/v106-multi-wave/manifest.json",
    "docs/v106-decision.md",
    "docs/v106-multi-wave-spec.md",
]


class DwmError(ValueError):
    """Structured product CLI error."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
        return record


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise DwmError(code, message, path=path)


def check_components_not_symlink(path: Path) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DwmError("ERR_DWM_PATH_SYMLINK", "run path contains a symlink", path=current)


def resolve_out_run(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_DWM_OUTSIDE_OUT", "run path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_resolved = OUT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(out_resolved)
    except ValueError as exc:
        raise DwmError("ERR_DWM_OUTSIDE_OUT", "run path must resolve under repo-local out/", path=value) from exc
    if resolved == out_resolved:
        raise DwmError("ERR_DWM_OUTSIDE_OUT", "run path must name a versioned run directory", path=value)
    check_components_not_symlink(candidate)
    return resolved


def read_json_obj(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DwmError("ERR_DWM_ARTIFACT_MISSING", f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", f"{label} root must be an object", path=path)
    return data


def read_text_file(path: Path, *, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise DwmError("ERR_DWM_ARTIFACT_MISSING", f"{label} is missing or symlinked", path=path)
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", f"{label} is not UTF-8 text", path=path) from exc


def write_text_atomic(path: Path, text: str, *, root: Path) -> None:
    target = path if path.is_absolute() else root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(text)
    tmp.replace(target)


def write_json_atomic(path: Path, data: Any, *, root: Path) -> None:
    write_text_atomic(path, canonical_json(data) + "\n", root=root)


def detect_version(run_dir: Path) -> str:
    parent = run_dir.parent.name
    if re.fullmatch(r"v[0-9]+(?:\.[0-9]+)?", parent):
        return parent
    raise DwmError("ERR_DWM_UNKNOWN_RUN_LAYOUT", "run path must be under out/v<number>/", path=run_dir)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "objective"


def resolve_shell_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_DWM_SHELL_OUTSIDE_ROOT", "shell output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = SHELL_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DwmError("ERR_DWM_SHELL_OUTSIDE_ROOT", "shell output must resolve under repo-local out/v21/", path=value) from exc
    if resolved == root_resolved:
        raise DwmError("ERR_DWM_SHELL_OUTSIDE_ROOT", "shell output must name a run directory", path=value)
    check_components_not_symlink(candidate)
    return resolved


def default_shell_out(objective: str, mode: str) -> Path:
    return SHELL_ROOT / f"{mode}-{slugify(objective)}-{now_utc().replace(':', '').replace('-', '')}"


def read_shell_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SHELL_SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_shell_out(path: Path, shell_id: str, *, mode: str) -> None:
    if path.exists():
        if path.is_symlink():
            raise DwmError("ERR_DWM_PATH_SYMLINK", "shell output is a symlink", path=path)
        if not path.is_dir():
            raise DwmError("ERR_DWM_SHELL_OUTSIDE_ROOT", "shell output is not a directory", path=path)
        sentinel = read_shell_sentinel(path)
        if sentinel is None or sentinel.get("shell_id") != shell_id:
            raise DwmError("ERR_DWM_SHELL_OUTSIDE_ROOT", "existing shell output is not shell-owned", path=path)
        for child in path.iterdir():
            if child.is_dir():
                import shutil

                shutil.rmtree(child)
            else:
                child.unlink()
    SHELL_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        path / SHELL_SENTINEL,
        {
            "tool": "dwm.py",
            "schema_version": "1.0",
            "shell_version": SHELL_VERSION,
            "shell_id": shell_id,
            "mode": mode,
            "created_at": now_utc(),
        },
        root=path,
    )


def render_shell_request(request: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# DWM Product Shell Request",
            "",
            f"Mode: `{request['mode']}`",
            f"Decision: `{request['decision']}`",
            f"Objective: {request['objective']}",
            "",
            f"Safe default: {request['safe_default']}",
            "",
            "This artifact records product-shell intent only. It does not claim live adapter execution.",
            "",
        ]
    )


def create_shell_request(objective: str, out_dir: Path, *, mode: str) -> dict[str, Any]:
    objective = objective.strip()
    if not objective:
        raise DwmError("ERR_DWM_ARGUMENTS", "objective must not be empty")
    out_dir = resolve_shell_out(out_dir)
    shell_id = out_dir.name
    prepare_shell_out(out_dir, shell_id, mode=mode)
    live_blocked = mode == "run"
    request = {
        "tool": "dwm.py",
        "schema_version": "1.0",
        "shell_version": SHELL_VERSION,
        "shell_id": shell_id,
        "created_at": now_utc(),
        "mode": mode,
        "objective": objective,
        "decision": "blocked-before-live-execution" if live_blocked else "plan-only",
        "execution_path": "plan-only",
        "safe_default": "inspect this artifact, then invoke $depone or an approved adapter command",
        "blocked_by": ["ERR_DWM_SHELL_LIVE_EXECUTION_BLOCKED"] if live_blocked else [],
        "recommended_commands": [
            f"Use $depone to design a workflow for: {objective}",
            f"python scripts/dwm.py resume --run {rel(out_dir)} --json",
        ],
    }
    status = {
        "tool": "dwm.py",
        "schema_version": "1.0",
        "shell_version": SHELL_VERSION,
        "run_id": shell_id,
        "run_path": rel(out_dir),
        "version": "v21",
        "mode": mode,
        "status": "blocked" if live_blocked else "planned",
        "decision": request["decision"],
        "resume_state": "resumable",
        "blocked_by": request["blocked_by"],
        "request_hash": canonical_hash(request),
        "source_paths": {
            "request": rel(out_dir / "workflow-request.json"),
            "status": rel(out_dir / "status.json"),
            "resume": rel(out_dir / "resume.md"),
        },
    }
    write_json_atomic(out_dir / "workflow-request.json", request, root=out_dir)
    write_text_atomic(out_dir / "workflow-request.md", render_shell_request(request), root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    write_text_atomic(out_dir / "resume.md", render_shell_resume(status), root=out_dir)
    return shell_resume_summary(out_dir)


def status_summary(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_out_run(run_dir)
    status = read_json_obj(run_dir / "status.json", label="status.json")
    run = read_json_obj(run_dir / "run.json", label="run.json") if (run_dir / "run.json").exists() else {}
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "run_path": rel(run_dir),
        "version": detect_version(run_dir),
        "run_id": status.get("run_id", run_dir.name),
        "status": status.get("status"),
        "resume_state": status.get("resume_state"),
        "state_path": status.get("state_path"),
        "completed_phase_ids": status.get("completed_phase_ids", []),
        "reviewed_phase_ids": status.get("reviewed_phase_ids", []),
        "human_approved_phase_ids": status.get("human_approved_phase_ids", []),
        "ready_phase_ids": status.get("ready_phase_ids", []),
        "selected_phase_ids": status.get("selected_phase_ids", []),
        "invalidators": status.get("invalidators", []),
        "snapshots": status.get("snapshots", {}),
        "source_paths": {
            "run": rel(run_dir / "run.json") if (run_dir / "run.json").exists() else None,
            "status": rel(run_dir / "status.json"),
            "state": rel(run_dir / str(status.get("state_path"))) if isinstance(status.get("state_path"), str) else None,
            "resume": rel(run_dir / "resume.md") if (run_dir / "resume.md").exists() else None,
        },
        "run_created_at": run.get("created_at"),
    }


def render_shell_resume(status: dict[str, Any]) -> str:
    blocked = status.get("blocked_by") or []
    lines = [
        "# DWM Product Shell Resume",
        "",
        f"Run: `{status['run_path']}`",
        f"Status: `{status['status']}`",
        f"Decision: `{status['decision']}`",
        "",
    ]
    if blocked:
        lines.extend(["Blocked by:", *[f"- `{item}`" for item in blocked], ""])
    lines.extend(
        [
            "Safe next action: inspect the request artifact and invoke `$depone` for a real workflow design.",
            "",
        ]
    )
    return "\n".join(lines)


def shell_resume_summary(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_shell_out(run_dir)
    sentinel = read_shell_sentinel(run_dir)
    if sentinel is None:
        raise DwmError("ERR_DWM_ARTIFACT_MISSING", "v21 shell run is missing ownership sentinel", path=run_dir / SHELL_SENTINEL)
    status = read_json_obj(run_dir / "status.json", label="v21 status.json")
    request = read_json_obj(run_dir / "workflow-request.json", label="workflow-request.json")
    expected_hash = status.get("request_hash")
    if expected_hash != canonical_hash(request):
        raise DwmError("ERR_DWM_SHELL_STALE", "workflow request hash does not match status", path=run_dir / "status.json")
    blocked_by = status.get("blocked_by", [])
    if not isinstance(blocked_by, list):
        raise DwmError("ERR_DWM_ARTIFACT_MALFORMED", "v21 status blocked_by must be a list", path=run_dir / "status.json")
    action = "blocked" if status.get("status") == "blocked" else "manual-design-required"
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "shell_version": SHELL_VERSION,
        "run_path": rel(run_dir),
        "version": "v21",
        "run_id": status.get("run_id", run_dir.name),
        "mode": status.get("mode"),
        "status": status.get("status"),
        "decision": status.get("decision"),
        "resume_state": status.get("resume_state"),
        "trusted": True,
        "verified_artifact_hashes": 1,
        "blocked_by": blocked_by,
        "recommendation": {
            "action": action,
            "requires_user_approval": False,
            "blocked_by": blocked_by,
            "safe_default": request.get("safe_default"),
            "commands": request.get("recommended_commands", []),
            "summary": "V21 product shell records intent only; live planning or execution remains gated.",
        },
        "source_paths": status.get("source_paths", {}),
    }


def require_hash_match(hashes: dict[str, Any], key: str, actual: str, path: Path) -> None:
    expected = hashes.get(key)
    if not isinstance(expected, str):
        raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", f"hashes.json is missing {key}", path=path)
    if expected != actual:
        raise DwmError("ERR_DWM_HASH_LEDGER_STALE", f"hashes.json {key} does not match current artifact", path=path)


def validate_packet_hash_maps(run_dir: Path, hashes: dict[str, Any]) -> int:
    verified = 0
    packet_hashes = hashes.get("packet_hashes")
    prompt_hashes = hashes.get("prompt_hashes")
    if packet_hashes is None and prompt_hashes is None:
        return verified
    if not isinstance(packet_hashes, dict) or not isinstance(prompt_hashes, dict):
        raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", "packet or prompt hash map is malformed", path=run_dir / "hashes.json")

    packet_dir = run_dir / "packets"
    packet_files = sorted(packet_dir.glob("*.packet.json"))
    packets_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for packet_path in packet_files:
        packet = read_json_obj(packet_path, label=rel(packet_path))
        packet_id = packet.get("packet_id")
        if isinstance(packet_id, str):
            packets_by_id[packet_id] = (packet_path, packet)

    for packet_id, expected_hash in packet_hashes.items():
        if not isinstance(packet_id, str) or not isinstance(expected_hash, str):
            raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", "packet hash map contains a malformed entry", path=run_dir / "hashes.json")
        packet_path, packet = packets_by_id.get(packet_id, (None, None))  # type: ignore[assignment]
        if packet_path is None or packet is None:
            raise DwmError("ERR_DWM_ARTIFACT_MISSING", f"packet {packet_id} is missing", path=packet_dir)
        if canonical_hash(packet) != expected_hash:
            raise DwmError("ERR_DWM_HASH_LEDGER_STALE", f"packet hash for {packet_id} does not match current artifact", path=packet_path)
        verified += 1
        prompt_path = packet_path.with_name(packet_path.name.replace(".packet.json", ".prompt.md"))
        expected_prompt_hash = prompt_hashes.get(packet_id)
        if not isinstance(expected_prompt_hash, str):
            raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", f"prompt hash for {packet_id} is missing", path=run_dir / "hashes.json")
        if sha256_text(read_text_file(prompt_path, label=rel(prompt_path))) != expected_prompt_hash:
            raise DwmError("ERR_DWM_HASH_LEDGER_STALE", f"prompt hash for {packet_id} does not match current artifact", path=prompt_path)
        verified += 1
    return verified


def validate_hash_ledger(run_dir: Path, status: dict[str, Any], hashes: dict[str, Any]) -> int:
    snapshots = status.get("snapshots")
    if snapshots != hashes:
        raise DwmError("ERR_DWM_HASH_LEDGER_STALE", "status snapshots do not match hashes.json", path=run_dir / "status.json")

    verified = 0
    json_hash_files = {
        "result_hash": "result.json",
        "review_hash": "review.json",
        "run_hash": "run.json",
        "state_hash": "state.json",
        "journal_hash": "journal/0000.json",
    }
    text_hash_files = {
        "stdout_hash": "stdout.txt",
        "stderr_hash": "stderr.txt",
        "review_markdown_hash": "review.md",
        "approval_markdown_hash": "human-approval.md",
    }

    for key, relative in json_hash_files.items():
        if key in hashes:
            path = run_dir / relative
            require_hash_match(hashes, key, canonical_hash(read_json_obj(path, label=relative)), path)
            verified += 1
    for key, relative in text_hash_files.items():
        if key in hashes:
            path = run_dir / relative
            require_hash_match(hashes, key, sha256_text(read_text_file(path, label=relative)), path)
            verified += 1
    for key in sorted(hashes):
        if key.startswith("output:"):
            output_name = key.removeprefix("output:")
            if "/" in output_name or output_name in {"", ".", ".."}:
                raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", f"output hash key is malformed: {key}", path=run_dir / "hashes.json")
            path = run_dir / "work" / output_name
            require_hash_match(hashes, key, sha256_text(read_text_file(path, label=rel(path))), path)
            verified += 1

    verified += validate_packet_hash_maps(run_dir, hashes)
    if verified == 0:
        raise DwmError("ERR_DWM_HASH_LEDGER_MALFORMED", "hashes.json has no locally verifiable entries", path=run_dir / "hashes.json")
    return verified


def check_path(path_text: str) -> dict[str, Any]:
    path = ROOT / path_text
    if path_text.startswith("out/"):
        if not path.exists() or path.is_symlink() or not path.is_dir():
            return {
                "id": f"path:{path_text}",
                "ok": False,
                "path": path_text,
                "message": "missing, symlinked, or not a directory",
            }
        try:
            status = read_json_obj(path / "status.json", label=f"{path_text}/status.json")
            hashes = read_json_obj(path / "hashes.json", label=f"{path_text}/hashes.json")
            verified = validate_hash_ledger(path, status, hashes)
        except DwmError as exc:
            return {
                "id": f"path:{path_text}",
                "ok": False,
                "path": path_text,
                "message": exc.message,
            }
        return {
            "id": f"path:{path_text}",
            "ok": True,
            "path": path_text,
            "message": f"status.json and hashes.json verified ({verified} artifact hashes)",
        }
    ok = path.exists() and not path.is_symlink()
    return {
        "id": f"path:{path_text}",
        "ok": ok,
        "path": path_text,
        "message": "present" if ok else "missing or symlinked",
    }


def run_trust_summary(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_out_run(run_dir)
    checks: list[dict[str, Any]] = []
    try:
        status = read_json_obj(run_dir / "status.json", label="status.json")
        checks.append({"id": "status-json", "ok": True, "path": rel(run_dir / "status.json"), "message": "present"})
    except DwmError as exc:
        checks.append({"id": "status-json", "ok": False, "path": rel(run_dir / "status.json"), "message": exc.message})
        return {"trusted": False, "checks": checks, "verified_artifact_hashes": 0}

    hashes_path = run_dir / "hashes.json"
    if hashes_path.exists():
        try:
            hashes = read_json_obj(hashes_path, label="hashes.json")
            verified = validate_hash_ledger(run_dir, status, hashes)
            checks.append(
                {
                    "id": "hash-ledger",
                    "ok": True,
                    "path": rel(hashes_path),
                    "message": f"verified {verified} artifact hashes",
                }
            )
            return {"trusted": True, "checks": checks, "verified_artifact_hashes": verified}
        except DwmError as exc:
            checks.append({"id": "hash-ledger", "ok": False, "path": rel(hashes_path), "message": exc.message})
            return {"trusted": False, "checks": checks, "verified_artifact_hashes": 0}

    checks.append({"id": "hash-ledger", "ok": False, "path": rel(hashes_path), "message": "missing hashes.json"})
    return {"trusted": False, "checks": checks, "verified_artifact_hashes": 0}


def recommended_action(summary: dict[str, Any], trust: dict[str, Any]) -> dict[str, Any]:
    invalidators = summary.get("invalidators", [])
    selected = summary.get("selected_phase_ids", [])
    status = summary.get("status")
    resume_state = summary.get("resume_state")
    run_path = str(summary.get("run_path", ""))
    if not trust.get("trusted"):
        return {
            "action": "repair-required",
            "summary": "Run artifacts are not trusted; inspect invalidators and regenerate from the prior trusted stage.",
            "requires_user_approval": True,
            "safe_default": "stop before executing or ingesting this run",
            "commands": [],
            "blocked_by": ["untrusted-artifacts"],
        }
    if invalidators or status == "invalid" or resume_state == "invalidated":
        return {
            "action": "repair-required",
            "summary": "The run is invalidated; do not advance it until the stale or malformed artifact is repaired.",
            "requires_user_approval": True,
            "safe_default": "stop and inspect status invalidators",
            "commands": [],
            "blocked_by": [str(item.get("code", "invalidator")) for item in invalidators if isinstance(item, dict)] or ["invalid-run"],
        }
    if status == "workflow-complete":
        return {
            "action": "complete",
            "summary": "The workflow is complete; no next workflow action is required for this run.",
            "requires_user_approval": False,
            "safe_default": "archive evidence or start a new workflow",
            "commands": [f"python scripts/dwm.py doctor --run {run_path} --json"],
            "blocked_by": [],
        }
    if isinstance(selected, list) and "human_gate" in selected:
        return {
            "action": "human-approval-required",
            "summary": "The next selected phase is a human gate; collect a tracked approval artifact before advancing.",
            "requires_user_approval": True,
            "safe_default": "stop before approval or execution",
            "commands": [],
            "blocked_by": ["human_gate"],
        }
    if isinstance(selected, list) and selected:
        return {
            "action": "next-phase-ready",
            "summary": "The run has selected phases ready for the next controlled dispatch step.",
            "requires_user_approval": False,
            "safe_default": "dispatch only through the matching deterministic adapter",
            "commands": [f"python scripts/dwm.py status --run {run_path} --json"],
            "blocked_by": ["adapter-selection-required"],
        }
    return {
        "action": "inspect",
        "summary": "No selected next phase is recorded; inspect status and resume artifacts before deciding.",
        "requires_user_approval": False,
        "safe_default": "inspect before advancing",
        "commands": [f"python scripts/dwm.py status --run {run_path} --json"],
        "blocked_by": [],
    }


def next_summary(run_dir: Path) -> dict[str, Any]:
    summary = status_summary(run_dir)
    trust = run_trust_summary(run_dir)
    action = recommended_action(summary, trust)
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "run_path": summary["run_path"],
        "version": summary["version"],
        "run_id": summary["run_id"],
        "status": summary["status"],
        "resume_state": summary["resume_state"],
        "trusted": trust["trusted"],
        "trust_checks": trust["checks"],
        "verified_artifact_hashes": trust["verified_artifact_hashes"],
        "selected_phase_ids": summary["selected_phase_ids"],
        "human_approved_phase_ids": summary["human_approved_phase_ids"],
        "invalidators": summary["invalidators"],
        "recommendation": action,
    }


def advertised_command_paths() -> list[str]:
    paths: set[str] = set(BASE_REQUIRED_PATHS)
    for command in [*RELEASE_COMMANDS, *DOGFOOD_COMMANDS, *PRODUCT_COMMANDS]:
        for token in shlex.split(command):
            if token.startswith("scripts/") and token.endswith(".py"):
                paths.add(token)
            elif token.startswith("fixtures/") and token.endswith(".json"):
                paths.add(token)
    for command in DOGFOOD_COMMANDS:
        for token in shlex.split(command):
            if token.startswith("out/"):
                paths.add(token)
    return sorted(paths)


def doctor_summary(run_dir: Path = DEFAULT_RUN) -> dict[str, Any]:
    checks = [check_path(path) for path in advertised_command_paths()]
    final_status: dict[str, Any] | None = None
    try:
        final_status = status_summary(run_dir)
        checks.append(
            {
                "id": "dogfood:workflow-complete",
                "ok": final_status.get("status") == "workflow-complete",
                "path": rel(resolve_out_run(run_dir) / "status.json"),
                "message": str(final_status.get("status")),
            }
        )
        checks.append(
            {
                "id": "dogfood:human-gate-approved",
                "ok": final_status.get("human_approved_phase_ids") == ["human_gate"],
                "path": rel(resolve_out_run(run_dir) / "status.json"),
                "message": ",".join(str(item) for item in final_status.get("human_approved_phase_ids", [])),
            }
        )
    except DwmError as exc:
        checks.append({"id": "dogfood:status-readable", "ok": False, "path": rel(resolve_out_run(run_dir)), "message": exc.message})
    ok = all(bool(check.get("ok")) for check in checks)
    return {
        "schema_version": "1.0",
        "tool": "dwm.py",
        "ok": ok,
        "checks": checks,
        "final_status": final_status,
        "release_commands": RELEASE_COMMANDS,
        "dogfood_commands": DOGFOOD_COMMANDS,
        "product_commands": PRODUCT_COMMANDS,
    }


def command_summary(kind: str) -> dict[str, Any]:
    commands: dict[str, list[str]] = {}
    if kind in {"all", "release"}:
        commands["release"] = RELEASE_COMMANDS
    if kind in {"all", "dogfood"}:
        commands["dogfood"] = DOGFOOD_COMMANDS
    if kind in {"all", "product"}:
        commands["product"] = PRODUCT_COMMANDS
    return {"schema_version": "1.0", "tool": "dwm.py", "commands": commands}


def print_text_status(summary: dict[str, Any]) -> None:
    print(f"DWM run: {summary['run_path']}")
    print(f"Version: {summary['version']}")
    print(f"Status: {summary['status']}")
    print(f"Resume: {summary['resume_state']}")
    print(f"Completed: {', '.join(str(item) for item in summary['completed_phase_ids']) or 'none'}")
    print(f"Selected: {', '.join(str(item) for item in summary['selected_phase_ids']) or 'none'}")
    print(f"Human approved: {', '.join(str(item) for item in summary['human_approved_phase_ids']) or 'none'}")
    if summary["invalidators"]:
        print("Invalidators:")
        for item in summary["invalidators"]:
            print(f"- {item.get('code')}: {item.get('message')}")


def print_text_doctor(summary: dict[str, Any]) -> None:
    print(f"DWM doctor: {'ok' if summary['ok'] else 'failed'}")
    for check in summary["checks"]:
        marker = "ok" if check["ok"] else "fail"
        print(f"- {marker}: {check['id']} ({check['message']})")


def print_text_commands(summary: dict[str, Any]) -> None:
    for group, commands in summary["commands"].items():
        print(f"{group}:")
        for command in commands:
            print(f"  {command}")


def print_text_next(summary: dict[str, Any]) -> None:
    recommendation = summary["recommendation"]
    print(f"DWM next: {recommendation['action']}")
    print(f"Run: {summary['run_path']}")
    print(f"Trusted: {'yes' if summary['trusted'] else 'no'}")
    print(f"Status: {summary['status']}")
    print(f"Summary: {recommendation['summary']}")
    if recommendation["commands"]:
        print("Commands:")
        for command in recommendation["commands"]:
            print(f"  {command}")
    if recommendation["blocked_by"]:
        print(f"Blocked by: {', '.join(str(item) for item in recommendation['blocked_by'])}")


def print_text_shell(summary: dict[str, Any]) -> None:
    print(f"DWM shell: {summary['recommendation']['action']}")
    print(f"Run: {summary['run_path']}")
    print(f"Status: {summary['status']}")
    print(f"Decision: {summary['decision']}")
    if summary["blocked_by"]:
        print(f"Blocked by: {', '.join(str(item) for item in summary['blocked_by'])}")
    print(f"Summary: {summary['recommendation']['summary']}")
    commands = summary["recommendation"].get("commands", [])
    if commands:
        print("Commands:")
        for command in commands:
            print(f"  {command}")


def self_test() -> None:
    summary = status_summary(DEFAULT_RUN)
    if summary["status"] != "workflow-complete":
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "canonical dogfood run should be workflow-complete", path=DEFAULT_RUN)
    if summary["human_approved_phase_ids"] != ["human_gate"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "canonical dogfood run should record human_gate approval", path=DEFAULT_RUN)
    doctor = doctor_summary(DEFAULT_RUN)
    if not doctor["ok"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "doctor should pass for the canonical repo state", path=DEFAULT_RUN)
    if "python scripts/dwm.py --self-test" not in doctor["release_commands"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "release commands should include DWM self-test")
    checked_paths = {str(check["path"]) for check in doctor["checks"] if str(check.get("id", "")).startswith("path:")}
    missing_advertised = [path for path in advertised_command_paths() if path not in checked_paths]
    if missing_advertised:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "doctor should check every advertised command path", path=missing_advertised[0])
    out_checks = [check for check in doctor["checks"] if str(check.get("id", "")).startswith("path:out/")]
    if not out_checks or not all("verified" in str(check.get("message", "")) for check in out_checks):
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "doctor should verify dogfood hash ledgers", path=DEFAULT_RUN)
    next_step = next_summary(DEFAULT_RUN)
    if next_step["recommendation"]["action"] != "complete" or not next_step["trusted"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "canonical dogfood next action should be trusted complete", path=DEFAULT_RUN)
    product_commands = command_summary("product")["commands"].get("product", [])
    if "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json" not in product_commands:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "product commands should include DWM next")
    inspect_action = recommended_action(
        {"run_path": "out/v5/example", "status": "executed", "resume_state": "resumable", "selected_phase_ids": [], "invalidators": []},
        {"trusted": True},
    )
    if inspect_action["commands"] != ["python scripts/dwm.py status --run out/v5/example --json"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "inspect recommendation should stay bound to the inspected run")
    ready_action = recommended_action(
        {"run_path": "out/v6/example", "status": "frontier-ready", "resume_state": "resumable", "selected_phase_ids": ["release_decision"], "invalidators": []},
        {"trusted": True},
    )
    if ready_action["commands"] != ["python scripts/dwm.py status --run out/v6/example --json"] or "adapter-selection-required" not in ready_action["blocked_by"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "ready recommendation should avoid canonical dogfood commands")
    canonical_status = read_json_obj(DEFAULT_RUN / "status.json", label="canonical status.json")
    canonical_hashes = read_json_obj(DEFAULT_RUN / "hashes.json", label="canonical hashes.json")
    tampered_hashes = dict(canonical_hashes)
    tampered_hashes["state_hash"] = "0" * 64
    try:
        validate_hash_ledger(DEFAULT_RUN, canonical_status, tampered_hashes)
    except DwmError as exc:
        if exc.code != "ERR_DWM_HASH_LEDGER_STALE":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "tampered hash ledger should be rejected", path=DEFAULT_RUN / "hashes.json")
    try:
        status_summary(ROOT / "README.md")
    except DwmError as exc:
        if exc.code != "ERR_DWM_OUTSIDE_OUT":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "outside-out status path should be rejected")
    try:
        detect_version(OUT_ROOT / "tmp" / "run")
    except DwmError as exc:
        if exc.code != "ERR_DWM_UNKNOWN_RUN_LAYOUT":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "unknown run layout should be rejected")
    try:
        read_json_obj(ROOT / "README.md", label="malformed json fixture")
    except DwmError as exc:
        if exc.code != "ERR_DWM_ARTIFACT_MALFORMED":
            raise
    else:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "malformed JSON should be rejected", path=ROOT / "README.md")
    plan_summary = create_shell_request("V21 shell self-test", SHELL_ROOT / "self-test-plan", mode="plan")
    if plan_summary["status"] != "planned" or plan_summary["recommendation"]["action"] != "manual-design-required":
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "V21 plan should create a resumable plan-only artifact")
    run_summary = create_shell_request("V21 shell self-test", SHELL_ROOT / "self-test-run", mode="run")
    if run_summary["status"] != "blocked" or "ERR_DWM_SHELL_LIVE_EXECUTION_BLOCKED" not in run_summary["blocked_by"]:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "V21 run should block before live execution")
    resumed = shell_resume_summary(SHELL_ROOT / "self-test-run")
    if resumed["trusted"] is not True or resumed["verified_artifact_hashes"] != 1:
        raise DwmError("ERR_DWM_SELF_TEST_FAILED", "V21 resume should verify the request hash")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run CLI self-tests")
    subparsers = parser.add_subparsers(dest="command")

    status = subparsers.add_parser("status", help="summarize one DWM run directory")
    status.add_argument("--run", default=str(DEFAULT_RUN), help="run directory under out/")
    status.add_argument("--json", action="store_true", help="emit stable JSON")

    doctor = subparsers.add_parser("doctor", help="check the repo-local DWM product surface")
    doctor.add_argument("--run", default=str(DEFAULT_RUN), help="canonical final run directory under out/")
    doctor.add_argument("--json", action="store_true", help="emit stable JSON")

    next_parser = subparsers.add_parser("next", help="recommend the next safe operator action for one run")
    next_parser.add_argument("--run", default=str(DEFAULT_RUN), help="run directory under out/")
    next_parser.add_argument("--json", action="store_true", help="emit stable JSON")

    plan = subparsers.add_parser("plan", help="record a plan-only product shell request")
    plan.add_argument("objective", help="large objective to design")
    plan.add_argument("--out", help="output directory under out/v21/")
    plan.add_argument("--json", action="store_true", help="emit stable JSON")

    run = subparsers.add_parser("run", help="record a run request and block before live execution")
    run.add_argument("objective", help="large objective to run through DWM")
    run.add_argument("--out", help="output directory under out/v21/")
    run.add_argument("--json", action="store_true", help="emit stable JSON")

    resume = subparsers.add_parser("resume", help="resume a V21 shell request or inspect an existing run")
    resume.add_argument("--run", required=True, help="run directory under out/")
    resume.add_argument("--json", action="store_true", help="emit stable JSON")

    commands = subparsers.add_parser("commands", help="print release or dogfood commands")
    commands.add_argument("--kind", choices=["all", "release", "dogfood", "product"], default="all")
    commands.add_argument("--json", action="store_true", help="emit stable JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            print("dwm self-test: pass")
            return 0
        if args.command == "status":
            summary = status_summary(Path(args.run))
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_status(summary)
            return 0 if summary.get("status") not in {None, "invalid"} else 1
        if args.command == "doctor":
            summary = doctor_summary(Path(args.run))
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_doctor(summary)
            return 0 if summary["ok"] else 1
        if args.command == "next":
            summary = next_summary(Path(args.run))
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_next(summary)
            return 0 if summary["trusted"] and summary["recommendation"]["action"] != "repair-required" else 1
        if args.command == "plan":
            out_dir = Path(args.out) if args.out else default_shell_out(args.objective, "plan")
            summary = create_shell_request(args.objective, out_dir, mode="plan")
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_shell(summary)
            return 0
        if args.command == "run":
            out_dir = Path(args.out) if args.out else default_shell_out(args.objective, "run")
            summary = create_shell_request(args.objective, out_dir, mode="run")
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_shell(summary)
            return 0
        if args.command == "resume":
            run_path = Path(args.run)
            summary = shell_resume_summary(run_path) if run_path.parts[:2] == ("out", "v21") or "out/v21" in run_path.as_posix() else next_summary(run_path)
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_shell(summary) if summary.get("version") == "v21" else print_text_next(summary)
            return 0 if summary.get("trusted") else 1
        if args.command == "commands":
            summary = command_summary(args.kind)
            if args.json:
                print(canonical_json(summary))
            else:
                print_text_commands(summary)
            return 0
        raise DwmError("ERR_DWM_ARGUMENTS", "expected --self-test, plan, run, resume, status, doctor, next, or commands")
    except DwmError as exc:
        print(canonical_json(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
