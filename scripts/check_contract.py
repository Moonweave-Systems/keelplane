#!/usr/bin/env python3
"""Check release-contract terms for the dynamic workflow designer skill."""

from pathlib import Path
import argparse
import json
import re
import shutil
import subprocess
import sys

import compile_workflow
import evaluate_plan


ROOT = Path(__file__).resolve().parents[1]
FIELD_LABELS = [
    "objective",
    "surface",
    "assumptions",
    "phases",
    "workers",
    "handoffs",
    "parallelism",
    "verification",
    "risk gates",
    "budget",
    "resume",
    "execution path",
    "falsifiable verification",
    "safe default",
]
FIXTURE_RECORD_LABELS = [
    "fixture type",
    "local context inspected",
]
V05_REQUIRED_TERMS = [
    "router-first rule",
    "exclusive condition",
    "workflow.plan.json",
    "tool_permissions",
    "artifact_schema",
    "first_slice",
    "raw_kind",
    "fixture_id",
    "producer",
    "packet hashes",
    "source-hashed normalization-failure",
    "downstream consumer protocol",
    "borderline downgrade fixtures",
    "valid downgrade artifact",
    "source-backed evidence excerpts",
    "blinded sample-review provenance",
    "repo-local",
]


def require_terms(path: str, terms: list[str]) -> None:
    text = (ROOT / path).read_text().lower()
    missing = [term for term in terms if term not in text]
    if missing:
        raise SystemExit(f"{path} missing required terms: {missing}")


def require_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    decision_text = decision_text.lower()
    normalized_decision_text = " ".join(decision_text.split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"{summary['fixture_count']} fixtures",
        f"candidate keep/kill average: {summary['candidate_keep_kill_average']}",
        "aggregate keep/kill average",
    ]
    for name, value in summary["baseline_keep_kill_averages"].items():
        required_snippets.append(f"`{name}` baseline average: {value}")
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v0.5-decision.md does not match out/v0.5/summary.json: {missing}")
    forbidden_claims = [
        "per-metric margin",
        "across activation discipline, handoff clarity, verification strength, safety gating, and downstream consumer success.",
    ]
    for claim in forbidden_claims:
        if claim in normalized_decision_text and "does not claim a per-metric margin" not in normalized_decision_text:
            raise SystemExit(f"docs/v0.5-decision.md contains unsupported claim: {claim}")


def run_contract_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "release command failed: "
            + " ".join(args)
            + f"\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        ) from exc


def require_decision_summary_consistency() -> None:
    completed = run_contract_command([sys.executable, "scripts/evaluate_plan.py", "--manifest", "fixtures/v0.5/manifest.json", "--out", "out/v0.5"])
    match = re.search(r"manifest evaluated: (\d+) fixtures, decision=(\w+)", completed.stdout)
    if not match:
        raise SystemExit(f"V0.5 manifest command output was not recognized: {completed.stdout}")
    out_root = ROOT / "out" / "v0.5-contract-check"
    try:
        summary = evaluate_plan.evaluate_manifest(ROOT / "fixtures" / "v0.5" / "manifest.json", out_root)
        require_decision_summary_text(summary, (ROOT / "docs" / "v0.5-decision.md").read_text())
    finally:
        shutil.rmtree(out_root, ignore_errors=True)


def require_v1_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final",
        "does not claim runtime execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v1-decision.md does not match V1 summary: {missing}")


def require_v1_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/compile_workflow.py",
                "--manifest",
                "fixtures/v1/manifest.json",
                "--out",
                "out/v1/final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v1_decision_summary_text(summary, (ROOT / "docs" / "v1-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V1 decision consistency failed: {exc}") from exc


def require_v2_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final",
        "does not claim multi-slice workflow runtime behavior",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v2-decision.md does not match V2 summary: {missing}")


def require_v2_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/execute_packet.py",
                "--manifest",
                "fixtures/v2/manifest.json",
                "--out",
                "out/v2/final",
            ],
        )
        summary = json.loads(completed.stdout)
        full_summary = json.loads((ROOT / "out" / "v2" / "final" / "summary.json").read_text())
        records = {
            item.get("id"): item
            for item in full_summary.get("fixtures", [])
            if isinstance(item, dict)
        }
        default_required = records.get("required-default-omitted")
        if not default_required or default_required.get("required") is not True or default_required.get("status") != "pass":
            raise SystemExit("V2 manifest did not prove omitted required defaults to true")
        optional_failure = records.get("optional-failing-fixture")
        if not optional_failure or optional_failure.get("required") is not False or optional_failure.get("status") != "fail":
            raise SystemExit("V2 manifest did not prove optional fixture failure policy")
        if "expected status blocked, got prepared" not in str(optional_failure.get("error", "")):
            raise SystemExit("V2 optional fixture failed for an unexpected reason")
        if full_summary.get("decision") != "keep" or full_summary.get("failed", 0) < 1:
            raise SystemExit("V2 manifest optional failure did not preserve keep decision with a recorded failure")
        require_v2_decision_summary_text(summary, (ROOT / "docs" / "v2-decision.md").read_text())
        shutil.rmtree(ROOT / "out" / "v2" / "contract-v2-ready-smoke", ignore_errors=True)
        shutil.rmtree(ROOT / "out" / "v2" / "contract-v2-blocked-smoke", ignore_errors=True)
        ready_completed = run_contract_command(
            [
                sys.executable,
                "scripts/execute_packet.py",
                "--run",
                "out/v1/v2-final-dry-run-ready-readonly",
                "--out",
                "out/v2/contract-v2-ready-smoke",
            ],
        )
        ready_status = json.loads(ready_completed.stdout)
        if ready_status.get("status") != "prepared":
            raise SystemExit(f"V2 ready smoke did not prepare evidence: {ready_completed.stdout}")
        attempts = ready_status.get("attempts")
        latest = attempts[-1] if isinstance(attempts, list) and attempts else {}
        if latest.get("repo_tracked_diff_unchanged") is not True:
            raise SystemExit("V2 ready smoke did not prove tracked diff was unchanged")
        blocked_completed = subprocess.run(
            [
                sys.executable,
                "scripts/execute_packet.py",
                "--run",
                "out/v1/v2-final-dry-run-blocked-risk",
                "--out",
                "out/v2/contract-v2-blocked-smoke",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if blocked_completed.returncode == 0:
            raise SystemExit("V2 blocked smoke unexpectedly exited zero")
        blocked_status = json.loads(blocked_completed.stdout)
        blocked_codes = [item.get("code") for item in blocked_status.get("invalidators", [])]
        if blocked_status.get("status") != "blocked" or "ERR_EXEC_BLOCKED_RISK" not in blocked_codes or blocked_status.get("attempt_count") != 0:
            raise SystemExit(f"V2 blocked smoke did not prove blocked-risk refusal: {blocked_completed.stdout}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V2 decision consistency failed: {exc}") from exc


def require_v25_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
        "does not claim backend repair execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v2.5-decision.md does not match V2.5 summary: {missing}")


def require_v25_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/execute_packet.py",
                "--manifest",
                "fixtures/v2.5/manifest.json",
                "--out",
                "out/v2.5/final",
            ],
        )
        summary = json.loads(completed.stdout)
        full_summary = json.loads((ROOT / "out" / "v2.5" / "final" / "summary.json").read_text())
        records = {
            item.get("id"): item
            for item in full_summary.get("fixtures", [])
            if isinstance(item, dict)
        }
        stale_review = records.get("review-stale-after-new-attempt")
        if not stale_review or stale_review.get("status") != "pass":
            raise SystemExit("V2.5 manifest did not prove stale review invalidation")
        replacement_review = records.get("review-replacement-after-new-attempt")
        if not replacement_review or replacement_review.get("status") != "pass":
            raise SystemExit("V2.5 manifest did not prove replacement review append")
        stale_repair = records.get("repair-stale-after-new-review")
        if not stale_repair or stale_repair.get("status") != "pass":
            raise SystemExit("V2.5 manifest did not prove stale repair invalidation")
        if full_summary.get("decision") != "keep" or full_summary.get("failed") != 0:
            raise SystemExit("V2.5 manifest did not preserve a clean keep decision")
        require_v25_decision_summary_text(summary, (ROOT / "docs" / "v2.5-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V2.5 decision consistency failed: {exc}") from exc


def require_v3_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
        "does not claim execution of later packets",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v3-decision.md does not match V3 summary: {missing}")


def require_v3_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/run_workflow.py",
                "--manifest",
                "fixtures/v3/manifest.json",
                "--out",
                "out/v3/final",
            ],
        )
        summary = json.loads(completed.stdout)
        full_summary = json.loads((ROOT / "out" / "v3" / "final" / "summary.json").read_text())
        records = {
            item.get("id"): item
            for item in full_summary.get("fixtures", [])
            if isinstance(item, dict)
        }
        expected = {
            "approved-advance": ("advanced", None),
            "reject-review-approved-manual": ("entry-rejected", "ERR_RUNTIME_ENTRY_REJECTED"),
            "reject-changes-requested": ("entry-rejected", "ERR_RUNTIME_ENTRY_REJECTED"),
            "reject-repair-prepared": ("entry-rejected", "ERR_RUNTIME_ENTRY_REJECTED"),
            "needs-human-requires-approval": ("entry-rejected", "ERR_RUNTIME_ENTRY_REJECTED"),
            "needs-human-approved": ("entry-rejected", "ERR_RUNTIME_ENTRY_REJECTED"),
            "resume-clean": ("advanced", None),
            "resume-stale-v25-status": ("invalid", "ERR_RUNTIME_STALE_V25"),
            "resume-tampered-next-packet": ("invalid", "ERR_RUNTIME_ARTIFACT_MALFORMED"),
            "resume-tampered-journal": ("invalid", "ERR_RUNTIME_ARTIFACT_MALFORMED"),
            "resume-non-owned-dir": ("invalid", "ERR_RUNTIME_ARTIFACT_MALFORMED"),
            "resume-human-approved-string": ("invalid", "ERR_RUNTIME_ARTIFACT_MALFORMED"),
            "reject-unmatched-first-slice": ("entry-rejected", "ERR_RUNTIME_ENTRY_REJECTED"),
        }
        for fixture_id, (expected_status, expected_code) in expected.items():
            record = records.get(fixture_id)
            if not record or record.get("status") != "pass" or record.get("actual_status") != expected_status:
                raise SystemExit(f"V3 manifest did not prove {fixture_id}")
            codes = record.get("invalidator_codes", [])
            if expected_code and expected_code not in codes:
                raise SystemExit(f"V3 manifest did not prove {fixture_id} with {expected_code}")
        for fixture_id in ["approved-advance", "resume-clean"]:
            record = records.get(fixture_id)
            if not record or record.get("actual_phase_id") != "verify":
                raise SystemExit(f"V3 manifest did not prove post-first-slice phase advancement for {fixture_id}")
        approved_status = json.loads((ROOT / "out" / "v3" / "final" / "needs-human-approved" / "status.json").read_text())
        if approved_status.get("human_approved") is not True or approved_status.get("accepted_v25_state") != "needs-human":
            raise SystemExit("V3 manifest did not exercise needs-human-approved with human_approved=true over needs-human state")
        manual_status = json.loads((ROOT / "out" / "v3" / "final" / "reject-review-approved-manual" / "status.json").read_text())
        if manual_status.get("accepted_v25_state") != "review-approved":
            raise SystemExit("V3 manifest did not exercise manual-only review-approved rejection")
        if full_summary.get("decision") != "keep" or full_summary.get("failed") != 0:
            raise SystemExit("V3 manifest did not preserve a clean keep decision")
        require_v3_decision_summary_text(summary, (ROOT / "docs" / "v3-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V3 decision consistency failed: {exc}") from exc


def require_v75_decision_summary_text(status: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict):
        raise SystemExit("V7.5 status is missing snapshots")
    approved_outputs = status.get("approved_outputs")
    if not isinstance(approved_outputs, list):
        raise SystemExit("V7.5 status is missing approved_outputs")
    required_snippets = [
        "decision: keep",
        "python scripts/review_frontier_result.py --self-test",
        "python scripts/review_frontier_result.py --result out/v7/v32-semantic-dogfood --out out/v7.5/v32-semantic-dogfood",
        "python scripts/review_frontier_result.py --resume out/v7.5/v32-semantic-dogfood",
        f"`run_id`: `{status['run_id']}`",
        f"`status`: `{status['status']}`",
        f"`resume_state`: `{status['resume_state']}`",
        f"`packet_id`: `{status['packet_id']}`",
        f"`phase_id`: `{status['phase_id']}`",
        f"`approved_outputs`: `{', '.join(str(output) for output in approved_outputs)}`",
        f"`source_result_hash`: `{snapshots['source_result_hash']}`",
        f"`source_packet_hash`: `{snapshots['source_packet_hash']}`",
        "does not claim runtime ingestion",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v7.5-decision.md does not match V7.5 status: {missing}")


def require_v75_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command([sys.executable, "scripts/review_frontier_result.py", "--resume", "out/v7.5/v32-semantic-dogfood"])
        status = json.loads(completed.stdout)
        require_v75_decision_summary_text(status, (ROOT / "docs" / "v7.5-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V7.5 decision consistency failed: {exc}") from exc


def require_v8_decision_summary_text(status: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict):
        raise SystemExit("V8 status is missing snapshots")
    required_snippets = [
        "decision: keep",
        "python scripts/ingest_frontier_review.py --self-test",
        "python scripts/ingest_frontier_review.py --review out/v7.5/v32-semantic-dogfood --out out/v8/v32-semantic-dogfood",
        "python scripts/ingest_frontier_review.py --resume out/v8/v32-semantic-dogfood",
        f"`run_id`: `{status['run_id']}`",
        f"`status`: `{status['status']}`",
        f"`resume_state`: `{status['resume_state']}`",
        f"`completed_phase_ids`: `{', '.join(str(phase) for phase in status['completed_phase_ids'])}`",
        f"`reviewed_phase_ids`: `{', '.join(str(phase) for phase in status['reviewed_phase_ids'])}`",
        f"`ready_phase_ids`: `{', '.join(str(phase) for phase in status['ready_phase_ids'])}`",
        f"`selected_phase_ids`: `{', '.join(str(phase) for phase in status['selected_phase_ids'])}`",
        f"`state_hash`: `{snapshots['state_hash']}`",
        "does not claim workflow completion",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v8-decision.md does not match V8 status: {missing}")


def require_v8_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command([sys.executable, "scripts/ingest_frontier_review.py", "--resume", "out/v8/v32-semantic-dogfood"])
        status = json.loads(completed.stdout)
        require_v8_decision_summary_text(status, (ROOT / "docs" / "v8-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V8 decision consistency failed: {exc}") from exc


def require_v9_decision_summary_text(status: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict):
        raise SystemExit("V9 status is missing snapshots")
    required_snippets = [
        "decision: keep",
        "python scripts/resolve_human_gate.py --self-test",
        "python scripts/resolve_human_gate.py --frontier out/v8/v32-semantic-dogfood --approval fixtures/v9/approvals/dogfood-human-approval.json --out out/v9/v32-semantic-dogfood",
        "python scripts/resolve_human_gate.py --resume out/v9/v32-semantic-dogfood",
        f"`run_id`: `{status['run_id']}`",
        f"`status`: `{status['status']}`",
        f"`resume_state`: `{status['resume_state']}`",
        f"`completed_phase_ids`: `{', '.join(str(phase) for phase in status['completed_phase_ids'])}`",
        f"`reviewed_phase_ids`: `{', '.join(str(phase) for phase in status['reviewed_phase_ids'])}`",
        f"`human_approved_phase_ids`: `{', '.join(str(phase) for phase in status['human_approved_phase_ids'])}`",
        f"`ready_phase_ids`: `{', '.join(str(phase) for phase in status['ready_phase_ids'])}`",
        f"`selected_phase_ids`: `{', '.join(str(phase) for phase in status['selected_phase_ids'])}`",
        f"`state_hash`: `{snapshots['state_hash']}`",
        "does not claim worker execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v9-decision.md does not match V9 status: {missing}")


def require_v9_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command([sys.executable, "scripts/resolve_human_gate.py", "--resume", "out/v9/v32-semantic-dogfood"])
        status = json.loads(completed.stdout)
        require_v9_decision_summary_text(status, (ROOT / "docs" / "v9-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V9 decision consistency failed: {exc}") from exc


def require_v10_decision_summary_text(doctor: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    final_status = doctor.get("final_status")
    release_commands = doctor.get("release_commands")
    if not isinstance(final_status, dict):
        raise SystemExit("V10 doctor output is missing final_status")
    if not isinstance(release_commands, list):
        raise SystemExit("V10 doctor output is missing release_commands")
    required_snippets = [
        "decision: keep",
        "python scripts/dwm.py --self-test",
        "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json",
        "python scripts/dwm.py doctor --json",
        "python scripts/dwm.py commands --kind release --json",
        f"`run_id`: `{final_status['run_id']}`",
        f"`version`: `{final_status['version']}`",
        f"`status`: `{final_status['status']}`",
        f"`resume_state`: `{final_status['resume_state']}`",
        f"`completed_phase_ids`: `{', '.join(str(phase) for phase in final_status['completed_phase_ids'])}`",
        f"`human_approved_phase_ids`: `{', '.join(str(phase) for phase in final_status['human_approved_phase_ids'])}`",
        f"`selected_phase_ids`: `{', '.join(str(phase) for phase in final_status['selected_phase_ids'])}`",
        f"`doctor_ok`: `{str(doctor['ok']).lower()}`",
        f"`release_command_count`: `{len(release_commands)}`",
        "does not claim workflow execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v10-decision.md does not match DWM doctor output: {missing}")


def require_v10_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command([sys.executable, "scripts/dwm.py", "doctor", "--json"])
        doctor = json.loads(completed.stdout)
        require_v10_decision_summary_text(doctor, (ROOT / "docs" / "v10-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V10 decision consistency failed: {exc}") from exc


def require_v11_decision_summary_text(next_status: dict[str, object], product_commands: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    recommendation = next_status.get("recommendation")
    command_groups = product_commands.get("commands")
    if not isinstance(recommendation, dict):
        raise SystemExit("V11 next output is missing recommendation")
    if not isinstance(command_groups, dict) or not isinstance(command_groups.get("product"), list):
        raise SystemExit("V11 product command output is missing commands.product")
    product = command_groups["product"]
    required_snippets = [
        "decision: keep",
        "python scripts/dwm.py --self-test",
        "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json",
        "python scripts/dwm.py commands --kind product --json",
        f"`run_id`: `{next_status['run_id']}`",
        f"`version`: `{next_status['version']}`",
        f"`status`: `{next_status['status']}`",
        f"`resume_state`: `{next_status['resume_state']}`",
        f"`trusted`: `{str(next_status['trusted']).lower()}`",
        f"`verified_artifact_hashes`: `{next_status['verified_artifact_hashes']}`",
        f"`recommendation.action`: `{recommendation['action']}`",
        f"`recommendation.requires_user_approval`: `{str(recommendation['requires_user_approval']).lower()}`",
        f"`product_command_count`: `{len(product)}`",
        "does not claim workflow execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v11-decision.md does not match DWM next output: {missing}")


def require_v11_decision_summary_consistency() -> None:
    try:
        next_completed = run_contract_command([sys.executable, "scripts/dwm.py", "next", "--run", "out/v9/v32-semantic-dogfood", "--json"])
        commands_completed = run_contract_command([sys.executable, "scripts/dwm.py", "commands", "--kind", "product", "--json"])
        next_status = json.loads(next_completed.stdout)
        product_commands = json.loads(commands_completed.stdout)
        require_v11_decision_summary_text(next_status, product_commands, (ROOT / "docs" / "v11-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V11 decision consistency failed: {exc}") from exc


def require_v13_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final",
        "does not claim live codex execution",
        "worktree creation",
        "durable session attach",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v13-decision.md does not match V13 summary: {missing}")


def require_v13_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_runner.py",
                "--manifest",
                "fixtures/v13/manifest.json",
                "--out",
                "out/v13/final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v13_decision_summary_text(summary, (ROOT / "docs" / "v13-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V13 decision consistency failed: {exc}") from exc


def require_v14_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_runner.py --manifest fixtures/v14/manifest.json --out out/v13/v14-final",
        "does not claim multi-worker scheduling",
        "automatic worktree cleanup",
        "force push",
        "secret access",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v14-decision.md does not match V14 summary: {missing}")


def require_v14_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_runner.py",
                "--manifest",
                "fixtures/v14/manifest.json",
                "--out",
                "out/v13/v14-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v14_decision_summary_text(summary, (ROOT / "docs" / "v14-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V14 decision consistency failed: {exc}") from exc


def require_v15_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_runner.py --manifest fixtures/v15/manifest.json --out out/v13/v15-final",
        "does not claim unlimited repair loops",
        "mutation of prior evidence",
        "self-review approval",
        "multi-worker fanout",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v15-decision.md does not match V15 summary: {missing}")


def require_v15_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_runner.py",
                "--manifest",
                "fixtures/v15/manifest.json",
                "--out",
                "out/v13/v15-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v15_decision_summary_text(summary, (ROOT / "docs" / "v15-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V15 decision consistency failed: {exc}") from exc


def require_v16_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_runner.py --manifest fixtures/v16/manifest.json --out out/v13/v16-final",
        "does not claim live multi-codex execution",
        "automatic output merging",
        "hidden failure suppression",
        "unbounded worker scheduling",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v16-decision.md does not match V16 summary: {missing}")


def require_v16_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_runner.py",
                "--manifest",
                "fixtures/v16/manifest.json",
                "--out",
                "out/v13/v16-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v16_decision_summary_text(summary, (ROOT / "docs" / "v16-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V16 decision consistency failed: {exc}") from exc


def require_v17_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_hud.py --manifest fixtures/v17/manifest.json --out out/hud/v17-final",
        "does not claim browser ui rendering",
        "approval of worker execution",
        "hosted dashboard service",
        "runtime execution authority",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v17-decision.md does not match V17 summary: {missing}")


def require_v17_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_hud.py",
                "--manifest",
                "fixtures/v17/manifest.json",
                "--out",
                "out/hud/v17-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v17_decision_summary_text(summary, (ROOT / "docs" / "v17-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V17 decision consistency failed: {exc}") from exc


def require_v18_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_install.py --manifest fixtures/v18/manifest.json --out out/install/v18-final",
        "does not claim hosted distribution",
        "global config mutation without approval",
        "package registry publication",
        "claude/codex adapter execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v18-decision.md does not match V18 summary: {missing}")


def require_v18_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_install.py",
                "--manifest",
                "fixtures/v18/manifest.json",
                "--out",
                "out/install/v18-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v18_decision_summary_text(summary, (ROOT / "docs" / "v18-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V18 decision consistency failed: {exc}") from exc


def require_v19_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_adapters.py --manifest fixtures/v19/manifest.json --out out/adapters/v19-final",
        "does not claim live codex execution",
        "live claude execution",
        "omx support",
        "trusted opaque transcripts",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v19-decision.md does not match V19 summary: {missing}")


def require_v19_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_adapters.py",
                "--manifest",
                "fixtures/v19/manifest.json",
                "--out",
                "out/adapters/v19-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v19_decision_summary_text(summary, (ROOT / "docs" / "v19-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V19 decision consistency failed: {exc}") from exc


def require_v20_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_release.py --manifest fixtures/v20/manifest.json --out out/release/v20-final",
        "does not claim hosted distribution",
        "live codex execution",
        "live claude execution",
        "production deployment",
        "autonomous execution without gates",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v20-decision.md does not match V20 summary: {missing}")


def require_v20_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_release.py",
                "--manifest",
                "fixtures/v20/manifest.json",
                "--out",
                "out/release/v20-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v20_decision_summary_text(summary, (ROOT / "docs" / "v20-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V20 decision consistency failed: {exc}") from exc


def require_v205_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_review_gate.py --manifest fixtures/v20.5/manifest.json --out out/release-review/v20.5-final",
        "does not claim package publication",
        "live codex execution",
        "live claude execution",
        "hosted distribution",
        "production deployment",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v20.5-decision.md does not match V20.5 summary: {missing}")


def require_v205_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_review_gate.py",
                "--manifest",
                "fixtures/v20.5/manifest.json",
                "--out",
                "out/release-review/v20.5-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v205_decision_summary_text(summary, (ROOT / "docs" / "v20.5-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V20.5 decision consistency failed: {exc}") from exc


def require_v206_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
    normalized_decision_text = " ".join(decision_text.lower().split())
    required_snippets = [
        f"decision: {summary['decision']}",
        f"`suite_id`: `{summary['suite_id']}`",
        f"`fixture_count`: {summary['fixture_count']}",
        f"`required_fixture_count`: {summary['required_fixture_count']}",
        f"`required_passed`: {summary['required_passed']}",
        f"`passed`: {summary['passed']}",
        f"`failed`: {summary['failed']}",
        f"`skipped`: {summary['skipped']}",
        f"`decision`: `{summary['decision']}`",
        "python scripts/dwm_dogfood_replay.py --manifest fixtures/v20.6/manifest.json --out out/dogfood-replay/v20.6-final",
        "repo status unchanged",
        "workflow-complete",
        "recommendation.action",
        "does not claim live adapter execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v20.6-decision.md does not match V20.6 summary: {missing}")


def require_v206_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_dogfood_replay.py",
                "--manifest",
                "fixtures/v20.6/manifest.json",
                "--out",
                "out/dogfood-replay/v20.6-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v206_decision_summary_text(summary, (ROOT / "docs" / "v20.6-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V20.6 decision consistency failed: {exc}") from exc


def require_release_commands_pass() -> None:
    commands = [
        [sys.executable, "scripts/quick_validate_skill.py", "."],
        [sys.executable, "scripts/quick_validate_skill.py", "--self-test"],
        [sys.executable, "scripts/evaluate_plan.py", "--self-test"],
        [sys.executable, "scripts/compile_workflow.py", "--self-test"],
        [sys.executable, "scripts/execute_packet.py", "--self-test"],
        [sys.executable, "scripts/execute_packet.py", "--manifest", "fixtures/v2.5/manifest.json", "--out", "out/v2.5/final"],
        [sys.executable, "scripts/dwm_runner.py", "--self-test"],
        [sys.executable, "scripts/dwm_runner.py", "session", "--self-test"],
        [sys.executable, "scripts/dwm_runner.py", "review", "--self-test"],
        [sys.executable, "scripts/dwm_runner.py", "fanout", "--self-test"],
        [sys.executable, "scripts/dwm_hud.py", "--self-test"],
        [sys.executable, "scripts/dwm_install.py", "--self-test"],
        [sys.executable, "scripts/dwm_adapters.py", "--self-test"],
        [sys.executable, "scripts/dwm_release.py", "--self-test"],
        [sys.executable, "scripts/dwm_review_gate.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_replay.py", "--self-test"],
        [sys.executable, "scripts/dwm.py", "plan", "V21 shell smoke", "--out", "out/v21/release-plan-smoke", "--json"],
        [sys.executable, "scripts/dwm.py", "run", "V21 shell smoke", "--out", "out/v21/release-run-smoke", "--json"],
        [sys.executable, "scripts/dwm.py", "resume", "--run", "out/v21/release-run-smoke", "--json"],
        [sys.executable, "scripts/run_workflow.py", "--self-test"],
        [sys.executable, "scripts/run_workflow.py", "--manifest", "fixtures/v3/manifest.json", "--out", "out/v3/final"],
        [sys.executable, "scripts/orchestrate_workflow.py", "--self-test"],
        [sys.executable, "scripts/dispatch_worker.py", "--self-test"],
        [sys.executable, "scripts/run_worker_result.py", "--self-test"],
        [sys.executable, "scripts/review_worker_result.py", "--self-test"],
        [sys.executable, "scripts/ingest_worker_review.py", "--self-test"],
        [sys.executable, "scripts/dispatch_frontier.py", "--self-test"],
        [sys.executable, "scripts/run_frontier_result.py", "--self-test"],
        [sys.executable, "scripts/review_frontier_result.py", "--self-test"],
        [sys.executable, "scripts/ingest_frontier_review.py", "--self-test"],
        [sys.executable, "scripts/resolve_human_gate.py", "--self-test"],
        [sys.executable, "scripts/dwm.py", "--self-test"],
        [sys.executable, "scripts/dwm.py", "status", "--run", "out/v9/v32-semantic-dogfood", "--json"],
        [sys.executable, "scripts/dwm.py", "next", "--run", "out/v9/v32-semantic-dogfood", "--json"],
        [sys.executable, "scripts/dwm.py", "doctor", "--json"],
        [sys.executable, "scripts/dwm.py", "commands", "--kind", "release", "--json"],
        [sys.executable, "scripts/dwm.py", "commands", "--kind", "product", "--json"],
        [sys.executable, "scripts/check_whitespace.py", "."],
        [sys.executable, "scripts/check_release_text.py", "."],
        [sys.executable, "scripts/check_release_text.py", "--self-test"],
    ]
    for command in commands:
        run_contract_command(command)
    completed = run_contract_command(
        [
            sys.executable,
            "scripts/review_frontier_result.py",
            "--result",
            "out/v7/v32-semantic-dogfood",
            "--out",
            "out/v7.5/v32-semantic-dogfood",
        ]
    )
    try:
        v75_review = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V7.5 dogfood review CLI output was not JSON: {completed.stdout}") from exc
    if v75_review.get("status") != "review-approved":
        raise SystemExit(f"V7.5 dogfood review did not approve: {completed.stdout}")
    completed = run_contract_command([sys.executable, "scripts/review_frontier_result.py", "--resume", "out/v7.5/v32-semantic-dogfood"])
    try:
        v75_resumed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V7.5 dogfood resume CLI output was not JSON: {completed.stdout}") from exc
    if v75_resumed.get("status") != "review-approved" or v75_resumed.get("resume_state") != "resumable":
        raise SystemExit(f"V7.5 dogfood resume did not produce clean resumable state: {completed.stdout}")
    completed = run_contract_command(
        [
            sys.executable,
            "scripts/ingest_frontier_review.py",
            "--review",
            "out/v7.5/v32-semantic-dogfood",
            "--out",
            "out/v8/v32-semantic-dogfood",
        ]
    )
    try:
        v8_ingested = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V8 dogfood ingestion CLI output was not JSON: {completed.stdout}") from exc
    if v8_ingested.get("status") != "frontier-ready" or v8_ingested.get("selected_phase_ids") != ["human_gate"]:
        raise SystemExit(f"V8 dogfood ingestion did not select human_gate: {completed.stdout}")
    completed = run_contract_command([sys.executable, "scripts/ingest_frontier_review.py", "--resume", "out/v8/v32-semantic-dogfood"])
    try:
        v8_resumed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V8 dogfood resume CLI output was not JSON: {completed.stdout}") from exc
    if v8_resumed.get("status") != "frontier-ready" or v8_resumed.get("resume_state") != "resumable":
        raise SystemExit(f"V8 dogfood resume did not produce clean resumable state: {completed.stdout}")
    completed = run_contract_command(
        [
            sys.executable,
            "scripts/resolve_human_gate.py",
            "--frontier",
            "out/v8/v32-semantic-dogfood",
            "--approval",
            "fixtures/v9/approvals/dogfood-human-approval.json",
            "--out",
            "out/v9/v32-semantic-dogfood",
        ]
    )
    try:
        v9_resolved = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V9 dogfood resolution CLI output was not JSON: {completed.stdout}") from exc
    if v9_resolved.get("status") != "workflow-complete" or v9_resolved.get("human_approved_phase_ids") != ["human_gate"]:
        raise SystemExit(f"V9 dogfood resolution did not complete human_gate: {completed.stdout}")
    completed = run_contract_command([sys.executable, "scripts/resolve_human_gate.py", "--resume", "out/v9/v32-semantic-dogfood"])
    try:
        v9_resumed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V9 dogfood resume CLI output was not JSON: {completed.stdout}") from exc
    if v9_resumed.get("status") != "workflow-complete" or v9_resumed.get("resume_state") != "resumable":
        raise SystemExit(f"V9 dogfood resume did not produce clean resumable state: {completed.stdout}")
    cli_out = ROOT / "out" / "v1" / "contract-cli"
    completed = run_contract_command(
        [
            sys.executable,
            "scripts/compile_workflow.py",
            "--plan",
            "fixtures/v1/plans/ready-readonly.workflow.plan.json",
            "--out",
            "out/v1/contract-cli",
        ]
    )
    try:
        compiled = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V1 compile CLI output was not JSON: {completed.stdout}") from exc
    if compiled.get("status") != "ready":
        raise SystemExit(f"V1 compile CLI did not produce a ready packet: {completed.stdout}")
    completed = run_contract_command([sys.executable, "scripts/compile_workflow.py", "--resume", "out/v1/contract-cli"])
    try:
        resumed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V1 resume CLI output was not JSON: {completed.stdout}") from exc
    if resumed.get("resume_state") != "resumable" or resumed.get("invalidators") != []:
        raise SystemExit(f"V1 resume CLI did not produce a clean resumable state: {completed.stdout}")
    if not (cli_out / "status.json").is_file() or not (cli_out / "resume.md").is_file():
        raise SystemExit("V1 compile/resume CLI did not write status.json and resume.md")


def canonical_patterns() -> set[str]:
    text = (ROOT / "references" / "workflow-patterns.md").read_text()
    return {
        match.group(1).strip().lower()
        for match in re.finditer(r"(?m)^## ([^\n]+)$", text)
    }


def collect_fixture_blocks() -> list[tuple[str, str]]:
    smoke_dir = ROOT / "docs" / "fixture-smoke"
    blocks: list[tuple[str, str]] = []
    for path in sorted(smoke_dir.glob("*.md")):
        text = path.read_text()
        parts = re.split(r"(?m)^## Fixture \d+\s*$", text)
        for index, part in enumerate(parts[1:], start=1):
            blocks.append((f"{path.relative_to(ROOT)} fixture {index}", part.lower()))
    return blocks


def section_between(block: str, start: str, end: str) -> str:
    pattern = re.compile(
        rf"{re.escape(start)}\s*\n(?P<body>.*?)(?=\n{re.escape(end)}\s*\n|\Z)",
        re.DOTALL,
    )
    match = pattern.search(block)
    return match.group("body").strip() if match else ""


def parse_selected_patterns(block: str) -> list[str]:
    body = section_between(block, "selected patterns:", "generated workflow output:")
    return [
        line.removeprefix("-").strip()
        for line in body.splitlines()
        if line.strip().startswith("-")
    ]


def parse_fixture_record_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        match = re.match(r"^([a-z ]+):\s*(.*)$", line)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def parse_output_fields(block: str) -> dict[str, str]:
    body = section_between(block, "generated workflow output:", "failed criteria:")
    fields: dict[str, list[str]] = {}
    current_label = ""
    for line in body.splitlines():
        match = re.match(r"^- ([a-z ]+):\s*(.*)$", line)
        if match:
            current_label = match.group(1).strip()
            fields.setdefault(current_label, []).append(match.group(2).strip())
        elif current_label and line.startswith("  "):
            fields[current_label].append(line.strip())
    return {label: " ".join(parts).strip() for label, parts in fields.items()}


def require_fixture_smoke(blocks: list[tuple[str, str]] | None = None) -> None:
    blocks = collect_fixture_blocks() if blocks is None else blocks
    if len(blocks) < 2:
        raise SystemExit("fixture smoke requires at least two fixture records")

    valid_patterns = canonical_patterns()
    type_counts = {
        "codebase-facing": 0,
        "non-code/meta": 0,
    }
    required_terms = [
        "fixture type:",
        "prompt:",
        "selected patterns:",
        "generated workflow output:",
        "objective:",
        "surface:",
        "assumptions:",
        "phases:",
        "workers:",
        "handoffs:",
        "parallelism:",
        "verification:",
        "risk gates:",
        "budget:",
        "resume:",
        "execution path:",
        "falsifiable verification:",
        "safe default:",
        "failed criteria: none",
        "resulting change:",
        "overclaims execution: no",
    ]

    for index, (name, raw_block) in enumerate(blocks, start=1):
        block = raw_block.lower()
        missing = [term for term in required_terms if term not in block]
        if missing:
            raise SystemExit(f"{name} missing required terms: {missing}")

        record_fields = parse_fixture_record_fields(block)
        empty_record_fields = [
            label for label in FIXTURE_RECORD_LABELS
            if not record_fields.get(label, "").strip()
        ]
        if empty_record_fields:
            raise SystemExit(
                f"{name} has empty fixture record fields: {empty_record_fields}"
            )

        local_context = record_fields["local context inspected"]
        if local_context not in {"yes", "no", "not-needed"}:
            raise SystemExit(
                f"{name} has invalid local context inspected value: {local_context}"
            )

        patterns = parse_selected_patterns(block)
        if not patterns:
            raise SystemExit(f"{name} has no selected patterns")
        unknown_patterns = [
            pattern for pattern in patterns if pattern.lower() not in valid_patterns
        ]
        if unknown_patterns:
            raise SystemExit(f"{name} has unknown patterns: {unknown_patterns}")

        fields = parse_output_fields(block)
        empty_fields = [
            label for label in FIELD_LABELS if not fields.get(label, "").strip()
        ]
        if empty_fields:
            raise SystemExit(f"{name} has empty output fields: {empty_fields}")

        for fixture_type in type_counts:
            if f"fixture type: {fixture_type}" in block:
                type_counts[fixture_type] += 1

    missing_types = [
        fixture_type for fixture_type, count in type_counts.items() if count == 0
    ]
    if missing_types:
        raise SystemExit(f"fixture smoke missing fixture types: {missing_types}")


def self_test() -> None:
    valid_block = """
Fixture type: codebase-facing
Local context inspected: not-needed
Prompt:
Design a workflow.
Selected patterns:
- Pipeline
Generated workflow output:
- Objective: audit routes.
- Surface: route files.
- Assumptions: routes are discoverable.
- Phases: inventory, audit, verify.
- Workers: auditor and verifier.
- Handoffs: route table and finding ledger.
- Parallelism: batch routes.
- Verification: refute findings.
- Risk gates: read-only until approved.
- Budget: cap batches.
- Resume: cache inventory.
- Execution path: direct Codex work.
- Falsifiable verification: verifier must find counter-evidence.
- Safe default: stop before edits.
Failed criteria: none
Resulting change: none
Overclaims execution: no
"""
    meta_block = valid_block.replace(
        "Fixture type: codebase-facing", "Fixture type: non-code/meta"
    )
    require_fixture_smoke([("valid 1", valid_block), ("valid 2", meta_block)])

    bad_pattern = valid_block.replace("- Pipeline", "- Imaginary Pattern")
    try:
        require_fixture_smoke([("bad pattern", bad_pattern), ("valid 2", meta_block)])
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: unknown pattern passed")

    empty_safe_default = valid_block.replace(
        "- Safe default: stop before edits.", "- Safe default:"
    )
    try:
        require_fixture_smoke(
            [("empty safe default", empty_safe_default), ("valid 2", meta_block)]
        )
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: empty field passed")

    missing_local_context = valid_block.replace(
        "Local context inspected: not-needed\n", ""
    )
    try:
        require_fixture_smoke(
            [("missing local context", missing_local_context), ("valid 2", meta_block)]
        )
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: missing local context passed")

    empty_local_context = valid_block.replace(
        "Local context inspected: not-needed",
        "Local context inspected:",
    )
    try:
        require_fixture_smoke(
            [("empty local context", empty_local_context), ("valid 2", meta_block)]
        )
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: empty local context passed")

    summary = {
        "decision": "keep",
        "fixture_count": 12,
        "candidate_keep_kill_average": 1.8,
        "baseline_keep_kill_averages": {"baseline-a": 1.0},
    }
    good_decision = (
        "Decision: keep\n"
        "- 12 fixtures evaluated.\n"
        "- Candidate keep/kill average: 1.8.\n"
        "- `baseline-a` baseline average: 1.0.\n"
        "The candidate aggregate keep/kill average beats each baseline aggregate. "
        "V0.5 does not claim a per-metric margin.\n"
    )
    require_decision_summary_text(summary, good_decision)
    bad_decision = good_decision.replace("1.8", "1.7")
    try:
        require_decision_summary_text(summary, bad_decision)
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale decision summary passed")

    v1_summary = {
        "suite_id": "final",
        "fixture_count": 78,
        "required_fixture_count": 78,
        "required_passed": 78,
        "passed": 78,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v1_decision = (
        "Decision: keep\n"
        "python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final\n"
        "- `suite_id`: `final`\n"
        "- `fixture_count`: 78\n"
        "- `required_fixture_count`: 78\n"
        "- `required_passed`: 78\n"
        "- `passed`: 78\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim runtime execution.\n"
    )
    require_v1_decision_summary_text(v1_summary, good_v1_decision)
    try:
        require_v1_decision_summary_text(v1_summary, good_v1_decision.replace("78", "77", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V1 decision summary passed")

    v2_summary = {
        "suite_id": "final",
        "fixture_count": 22,
        "required_fixture_count": 21,
        "required_passed": 21,
        "passed": 21,
        "failed": 1,
        "skipped": 0,
        "decision": "keep",
    }
    good_v2_decision = (
        "Decision: keep\n"
        "python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final\n"
        "- `suite_id`: `final`\n"
        "- `fixture_count`: 22\n"
        "- `required_fixture_count`: 21\n"
        "- `required_passed`: 21\n"
        "- `passed`: 21\n"
        "- `failed`: 1\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim multi-slice workflow runtime behavior.\n"
    )
    require_v2_decision_summary_text(v2_summary, good_v2_decision)
    try:
        require_v2_decision_summary_text(v2_summary, good_v2_decision.replace("22", "19", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V2 decision summary passed")

    v25_summary = {
        "suite_id": "final",
        "fixture_count": 9,
        "required_fixture_count": 9,
        "required_passed": 9,
        "passed": 9,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v25_decision = (
        "Decision: keep\n"
        "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final\n"
        "- `suite_id`: `final`\n"
        "- `fixture_count`: 9\n"
        "- `required_fixture_count`: 9\n"
        "- `required_passed`: 9\n"
        "- `passed`: 9\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim backend repair execution.\n"
    )
    require_v25_decision_summary_text(v25_summary, good_v25_decision)
    try:
        require_v25_decision_summary_text(v25_summary, good_v25_decision.replace("9", "5", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V2.5 decision summary passed")

    v3_summary = {
        "suite_id": "final",
        "fixture_count": 13,
        "required_fixture_count": 13,
        "required_passed": 13,
        "passed": 13,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v3_decision = (
        "Decision: keep\n"
        "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final\n"
        "- `suite_id`: `final`\n"
        "- `fixture_count`: 13\n"
        "- `required_fixture_count`: 13\n"
        "- `required_passed`: 13\n"
        "- `passed`: 13\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim execution of later packets.\n"
    )
    require_v3_decision_summary_text(v3_summary, good_v3_decision)
    try:
        require_v3_decision_summary_text(v3_summary, good_v3_decision.replace("13", "7", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V3 decision summary passed")

    v75_status = {
        "run_id": "v32-semantic-dogfood",
        "status": "review-approved",
        "resume_state": "resumable",
        "packet_id": "v6-frontier-0001-release_decision",
        "phase_id": "release_decision",
        "approved_outputs": ["release-decision.md"],
        "snapshots": {
            "source_result_hash": "abc123",
            "source_packet_hash": "def456",
        },
    }
    good_v75_decision = (
        "Decision: keep\n"
        "python scripts/review_frontier_result.py --self-test\n"
        "python scripts/review_frontier_result.py --result out/v7/v32-semantic-dogfood --out out/v7.5/v32-semantic-dogfood\n"
        "python scripts/review_frontier_result.py --resume out/v7.5/v32-semantic-dogfood\n"
        "- `run_id`: `v32-semantic-dogfood`\n"
        "- `status`: `review-approved`\n"
        "- `resume_state`: `resumable`\n"
        "- `packet_id`: `v6-frontier-0001-release_decision`\n"
        "- `phase_id`: `release_decision`\n"
        "- `approved_outputs`: `release-decision.md`\n"
        "- `source_result_hash`: `abc123`\n"
        "- `source_packet_hash`: `def456`\n"
        "This decision does not claim runtime ingestion.\n"
    )
    require_v75_decision_summary_text(v75_status, good_v75_decision)
    try:
        require_v75_decision_summary_text(v75_status, good_v75_decision.replace("abc123", "stale999", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V7.5 decision summary passed")

    v8_status = {
        "run_id": "v32-semantic-dogfood",
        "status": "frontier-ready",
        "resume_state": "resumable",
        "completed_phase_ids": ["release_inventory", "evidence_review", "release_decision"],
        "reviewed_phase_ids": ["evidence_review", "release_decision"],
        "ready_phase_ids": ["human_gate"],
        "selected_phase_ids": ["human_gate"],
        "snapshots": {"state_hash": "abc123"},
    }
    good_v8_decision = (
        "Decision: keep\n"
        "python scripts/ingest_frontier_review.py --self-test\n"
        "python scripts/ingest_frontier_review.py --review out/v7.5/v32-semantic-dogfood --out out/v8/v32-semantic-dogfood\n"
        "python scripts/ingest_frontier_review.py --resume out/v8/v32-semantic-dogfood\n"
        "- `run_id`: `v32-semantic-dogfood`\n"
        "- `status`: `frontier-ready`\n"
        "- `resume_state`: `resumable`\n"
        "- `completed_phase_ids`: `release_inventory, evidence_review, release_decision`\n"
        "- `reviewed_phase_ids`: `evidence_review, release_decision`\n"
        "- `ready_phase_ids`: `human_gate`\n"
        "- `selected_phase_ids`: `human_gate`\n"
        "- `state_hash`: `abc123`\n"
        "This decision does not claim workflow completion.\n"
    )
    require_v8_decision_summary_text(v8_status, good_v8_decision)
    try:
        require_v8_decision_summary_text(v8_status, good_v8_decision.replace("abc123", "stale999", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V8 decision summary passed")

    v9_status = {
        "run_id": "v32-semantic-dogfood",
        "status": "workflow-complete",
        "resume_state": "resumable",
        "completed_phase_ids": ["release_inventory", "evidence_review", "release_decision", "human_gate"],
        "reviewed_phase_ids": ["evidence_review", "release_decision"],
        "human_approved_phase_ids": ["human_gate"],
        "ready_phase_ids": [],
        "selected_phase_ids": [],
        "snapshots": {"state_hash": "abc123"},
    }
    good_v9_decision = (
        "Decision: keep\n"
        "python scripts/resolve_human_gate.py --self-test\n"
        "python scripts/resolve_human_gate.py --frontier out/v8/v32-semantic-dogfood --approval fixtures/v9/approvals/dogfood-human-approval.json --out out/v9/v32-semantic-dogfood\n"
        "python scripts/resolve_human_gate.py --resume out/v9/v32-semantic-dogfood\n"
        "- `run_id`: `v32-semantic-dogfood`\n"
        "- `status`: `workflow-complete`\n"
        "- `resume_state`: `resumable`\n"
        "- `completed_phase_ids`: `release_inventory, evidence_review, release_decision, human_gate`\n"
        "- `reviewed_phase_ids`: `evidence_review, release_decision`\n"
        "- `human_approved_phase_ids`: `human_gate`\n"
        "- `ready_phase_ids`: ``\n"
        "- `selected_phase_ids`: ``\n"
        "- `state_hash`: `abc123`\n"
        "This decision does not claim worker execution.\n"
    )
    require_v9_decision_summary_text(v9_status, good_v9_decision)
    try:
        require_v9_decision_summary_text(v9_status, good_v9_decision.replace("abc123", "stale999", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V9 decision summary passed")

    v10_doctor = {
        "ok": True,
        "final_status": {
            "run_id": "v32-semantic-dogfood",
            "version": "v9",
            "status": "workflow-complete",
            "resume_state": "resumable",
            "completed_phase_ids": ["release_inventory", "evidence_review", "release_decision", "human_gate"],
            "human_approved_phase_ids": ["human_gate"],
            "selected_phase_ids": [],
        },
        "release_commands": ["a", "b", "c"],
    }
    good_v10_decision = (
        "Decision: keep\n"
        "python scripts/dwm.py --self-test\n"
        "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json\n"
        "python scripts/dwm.py doctor --json\n"
        "python scripts/dwm.py commands --kind release --json\n"
        "- `run_id`: `v32-semantic-dogfood`\n"
        "- `version`: `v9`\n"
        "- `status`: `workflow-complete`\n"
        "- `resume_state`: `resumable`\n"
        "- `completed_phase_ids`: `release_inventory, evidence_review, release_decision, human_gate`\n"
        "- `human_approved_phase_ids`: `human_gate`\n"
        "- `selected_phase_ids`: ``\n"
        "- `doctor_ok`: `true`\n"
        "- `release_command_count`: `3`\n"
        "This decision does not claim workflow execution.\n"
    )
    require_v10_decision_summary_text(v10_doctor, good_v10_decision)
    try:
        require_v10_decision_summary_text(v10_doctor, good_v10_decision.replace("`3`", "`4`", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V10 decision summary passed")

    v11_next = {
        "run_id": "v32-semantic-dogfood",
        "version": "v9",
        "status": "workflow-complete",
        "resume_state": "resumable",
        "trusted": True,
        "verified_artifact_hashes": 4,
        "recommendation": {
            "action": "complete",
            "requires_user_approval": False,
        },
    }
    v11_product_commands = {"commands": {"product": ["a", "b", "c", "d"]}}
    good_v11_decision = (
        "Decision: keep\n"
        "python scripts/dwm.py --self-test\n"
        "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json\n"
        "python scripts/dwm.py commands --kind product --json\n"
        "- `run_id`: `v32-semantic-dogfood`\n"
        "- `version`: `v9`\n"
        "- `status`: `workflow-complete`\n"
        "- `resume_state`: `resumable`\n"
        "- `trusted`: `true`\n"
        "- `verified_artifact_hashes`: `4`\n"
        "- `recommendation.action`: `complete`\n"
        "- `recommendation.requires_user_approval`: `false`\n"
        "- `product_command_count`: `4`\n"
        "This decision does not claim workflow execution.\n"
    )
    require_v11_decision_summary_text(v11_next, v11_product_commands, good_v11_decision)
    try:
        require_v11_decision_summary_text(v11_next, v11_product_commands, good_v11_decision.replace("`4`", "`5`", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V11 decision summary passed")

    v13_summary = {
        "suite_id": "final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v13_decision = (
        "Decision: keep\n"
        "python scripts/dwm_runner.py --manifest fixtures/v13/manifest.json --out out/v13/final\n"
        "- `suite_id`: `final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim live Codex execution, worktree creation, durable session attach, or multi-worker fanout.\n"
    )
    require_v13_decision_summary_text(v13_summary, good_v13_decision)
    try:
        require_v13_decision_summary_text(v13_summary, good_v13_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V13 decision summary passed")

    v14_summary = {
        "suite_id": "v14-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v14_decision = (
        "Decision: keep\n"
        "python scripts/dwm_runner.py --manifest fixtures/v14/manifest.json --out out/v13/v14-final\n"
        "- `suite_id`: `v14-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim multi-worker scheduling, automatic worktree cleanup, force push, or secret access.\n"
    )
    require_v14_decision_summary_text(v14_summary, good_v14_decision)
    try:
        require_v14_decision_summary_text(v14_summary, good_v14_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V14 decision summary passed")

    v15_summary = {
        "suite_id": "v15-final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v15_decision = (
        "Decision: keep\n"
        "python scripts/dwm_runner.py --manifest fixtures/v15/manifest.json --out out/v13/v15-final\n"
        "- `suite_id`: `v15-final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim unlimited repair loops, mutation of prior evidence, final self-review approval, risky repair execution, or multi-worker fanout.\n"
    )
    require_v15_decision_summary_text(v15_summary, good_v15_decision)
    try:
        require_v15_decision_summary_text(v15_summary, good_v15_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V15 decision summary passed")

    v16_summary = {
        "suite_id": "v16-final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v16_decision = (
        "Decision: keep\n"
        "python scripts/dwm_runner.py --manifest fixtures/v16/manifest.json --out out/v13/v16-final\n"
        "- `suite_id`: `v16-final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim live multi-Codex execution, automatic output merging, hidden failure suppression, or unbounded worker scheduling.\n"
    )
    require_v16_decision_summary_text(v16_summary, good_v16_decision)
    try:
        require_v16_decision_summary_text(v16_summary, good_v16_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V16 decision summary passed")

    v17_summary = {
        "suite_id": "v17-final",
        "fixture_count": 8,
        "required_fixture_count": 8,
        "required_passed": 8,
        "passed": 8,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v17_decision = (
        "Decision: keep\n"
        "python scripts/dwm_hud.py --manifest fixtures/v17/manifest.json --out out/hud/v17-final\n"
        "- `suite_id`: `v17-final`\n"
        "- `fixture_count`: 8\n"
        "- `required_fixture_count`: 8\n"
        "- `required_passed`: 8\n"
        "- `passed`: 8\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim browser UI rendering, hosted dashboard service, approval of worker execution, or runtime execution authority.\n"
    )
    require_v17_decision_summary_text(v17_summary, good_v17_decision)
    try:
        require_v17_decision_summary_text(v17_summary, good_v17_decision.replace("`passed`: 8", "`passed`: 7", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V17 decision summary passed")

    v18_summary = {
        "suite_id": "v18-final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v18_decision = (
        "Decision: keep\n"
        "python scripts/dwm_install.py --manifest fixtures/v18/manifest.json --out out/install/v18-final\n"
        "- `suite_id`: `v18-final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim hosted distribution, global config mutation without approval, package registry publication, or Claude/Codex adapter execution.\n"
    )
    require_v18_decision_summary_text(v18_summary, good_v18_decision)
    try:
        require_v18_decision_summary_text(v18_summary, good_v18_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V18 decision summary passed")

    v19_summary = {
        "suite_id": "v19-final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v19_decision = (
        "Decision: keep\n"
        "python scripts/dwm_adapters.py --manifest fixtures/v19/manifest.json --out out/adapters/v19-final\n"
        "- `suite_id`: `v19-final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim live Codex execution, live Claude execution, OMX support, network execution, or trusted opaque transcripts.\n"
    )
    require_v19_decision_summary_text(v19_summary, good_v19_decision)
    try:
        require_v19_decision_summary_text(v19_summary, good_v19_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V19 decision summary passed")

    v20_summary = {
        "suite_id": "v20-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v20_decision = (
        "Decision: keep\n"
        "python scripts/dwm_release.py --manifest fixtures/v20/manifest.json --out out/release/v20-final\n"
        "- `suite_id`: `v20-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim hosted distribution, live Codex execution, live Claude execution, OMX support, production deployment, or autonomous execution without gates.\n"
    )
    require_v20_decision_summary_text(v20_summary, good_v20_decision)
    try:
        require_v20_decision_summary_text(v20_summary, good_v20_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V20 decision summary passed")

    v205_summary = {
        "suite_id": "v20.5-final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v205_decision = (
        "Decision: keep\n"
        "python scripts/dwm_review_gate.py --manifest fixtures/v20.5/manifest.json --out out/release-review/v20.5-final\n"
        "- `suite_id`: `v20.5-final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "This decision does not claim package publication, live Codex execution, live Claude execution, hosted distribution, or production deployment.\n"
    )
    require_v205_decision_summary_text(v205_summary, good_v205_decision)
    try:
        require_v205_decision_summary_text(v205_summary, good_v205_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V20.5 decision summary passed")

    v206_summary = {
        "suite_id": "v20.6-final",
        "fixture_count": 4,
        "required_fixture_count": 4,
        "required_passed": 4,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v206_decision = (
        "Decision: keep\n"
        "python scripts/dwm_dogfood_replay.py --manifest fixtures/v20.6/manifest.json --out out/dogfood-replay/v20.6-final\n"
        "- `suite_id`: `v20.6-final`\n"
        "- `fixture_count`: 4\n"
        "- `required_fixture_count`: 4\n"
        "- `required_passed`: 4\n"
        "- `passed`: 4\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted replay requires repo status unchanged, workflow-complete, and recommendation.action complete.\n"
        "This decision does not claim live adapter execution.\n"
    )
    require_v206_decision_summary_text(v206_summary, good_v206_decision)
    try:
        require_v206_decision_summary_text(v206_summary, good_v206_decision.replace("`passed`: 4", "`passed`: 3", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V20.6 decision summary passed")

    print("contract self-test: pass")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    require_terms(
        "SKILL.md",
        [
            "`assumptions`",
            "`execution path`",
            "`workflow.plan.json`",
            "references/workflow-plan-schema.md",
            "downgrade artifact",
            "dependency",
            "database",
            "production",
            "secret",
            "history-rewrite",
        ],
    )
    require_terms(
        "docs/spec.md",
        [
            "fixture smoke gate",
            "docs/fixture-smoke/",
            "generated workflow output",
            "one codebase-facing fixture",
            "one non-code or meta fixture",
            "does not imply the requested work has already been executed",
            "v0.5 remains a separate continuation gate",
        ],
    )
    require_terms(
        "README.md",
        [
            "docs/v0.5-plan-schema-evaluator-spec.md",
            "docs/fixture-smoke/",
            "python scripts/check_contract.py --self-test",
            "python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5",
            "python scripts/check_release_text.py .",
            "python scripts/check_release_text.py --self-test",
            "python scripts/compile_workflow.py --plan workflow.plan.json --out out/v1/<run_id>",
            "python scripts/compile_workflow.py --resume out/v1/<run_id>",
            "python scripts/compile_workflow.py --self-test",
            "python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final",
            "python scripts/execute_packet.py --self-test",
            "python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final",
            "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
            "python scripts/run_workflow.py --self-test",
            "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
            "python scripts/review_frontier_result.py --self-test",
            "python scripts/ingest_frontier_review.py --self-test",
            "python scripts/resolve_human_gate.py --self-test",
            "python scripts/dwm.py --self-test",
            "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood",
            "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood",
            "python scripts/dwm.py commands --kind product",
            "python scripts/dwm.py plan \"<objective>\" --out out/v21/<run_id>",
            "python scripts/dwm.py run \"<objective>\" --out out/v21/<run_id>",
            "python scripts/dwm.py resume --run out/v21/<run_id>",
            "python scripts/dwm_hud.py --self-test",
            "python scripts/dwm_hud.py --manifest fixtures/v17/manifest.json --out out/hud/v17-final",
            "python scripts/dwm_hud.py approve --hud out/hud/<hud_id> --out out/hud/<approval_id> --approver <name>",
            "python scripts/dwm_install.py --self-test",
            "python scripts/dwm_install.py --manifest fixtures/v18/manifest.json --out out/install/v18-final",
            "python scripts/dwm_install.py validate",
            "python scripts/dwm_install.py install --home /tmp/dwm-home --out out/install/<install_id>",
            "python scripts/dwm_adapters.py --self-test",
            "python scripts/dwm_adapters.py --manifest fixtures/v19/manifest.json --out out/adapters/v19-final",
            "python scripts/dwm_adapters.py registry",
            "python scripts/dwm_adapters.py fixture-run --out out/adapters/<run_id>",
            "python scripts/dwm_release.py --self-test",
            "python scripts/dwm_release.py --manifest fixtures/v20/manifest.json --out out/release/v20-final",
            "python scripts/dwm_release.py status --out out/release/<release_id>",
            "python scripts/dwm_review_gate.py --self-test",
            "python scripts/dwm_review_gate.py --manifest fixtures/v20.5/manifest.json --out out/release-review/v20.5-final",
            "python scripts/dwm_review_gate.py review --release out/release/<release_id> --out out/release-review/<review_id>",
            "python scripts/dwm_dogfood_replay.py --self-test",
            "python scripts/dwm_dogfood_replay.py --manifest fixtures/v20.6/manifest.json --out out/dogfood-replay/v20.6-final",
            "python scripts/dwm_dogfood_replay.py replay --out out/dogfood-replay/<replay_id>",
            "docs/v10-product-packaging-spec.md",
            "docs/v10-decision.md",
            "docs/v11-operator-guidance-spec.md",
            "docs/v11-decision.md",
            "docs/v12-to-v20-final-roadmap.md",
            "docs/v12-adapter-command-planner-spec.md",
            "docs/v13-dwm-runner-mvp-spec.md",
            "docs/v20-1.0-release-hardening-spec.md",
            "docs/v20.6-dogfood-replay-spec.md",
            "docs/v21-product-shell-spec.md",
            "planning documents, not implemented runtime claims",
            "docs/v2.5-review-repair-spec.md",
            "docs/v2.5-to-v3.workflow.plan.json",
            "docs/v2.5-decision.md",
            "docs/v3-runtime-entry-spec.md",
            "docs/v3-decision.md",
            "workflow.plan.json` to live under this repository root",
            "out/v1/v2-final-dry-run-ready-readonly",
            "out/v1/v2-final-dry-run-blocked-risk",
            "repo_tracked_diff_unchanged: true",
            "err_exec_blocked_risk",
            "out/v2/final/summary.json",
            "v2 still does not execute omx",
            "advance multi-slice workflows",
            "docs/v7.5-frontier-result-review-spec.md",
            "docs/v7.5-decision.md",
            "does not execute later",
            "docs/v8-frontier-review-ingestion-spec.md",
            "docs/v8-decision.md",
            "docs/v9-human-gate-resolution-spec.md",
            "docs/v9-decision.md",
            "read-only product cli",
            "operator guidance",
        ],
    )
    require_terms("docs/v0.5-plan-schema-evaluator-spec.md", V05_REQUIRED_TERMS)
    require_terms(
        "docs/v1-first-slice-compiler-spec.md",
        [
            "forged previous-invalidated status sections",
            "full invalidated",
            "hybrid clean/invalidated status section shapes",
            "missing, empty, malformed, or invalid utf-8 sentinel status-section",
            "exact ordered invalidator record shapes",
            "rerun compile to restore trusted clean status sections",
            "err_resume_missing_artifact",
        ],
    )
    require_terms(
        "docs/spec.md",
        [
            "references/workflow-plan-schema.md",
            "scripts/evaluate_plan.py --self-test",
            "fixtures/v0.5/manifest.json",
            "samples/v0.5/candidates/",
            "samples/v0.5/raw/",
            "samples/v0.5/consumer/",
            "source-hashed normalization-failure records",
            "exits nonzero",
            "docs/v0.5-decision.md",
            "python scripts/compile_workflow.py --plan workflow.plan.json --out out/v1/<run_id>",
            "python scripts/compile_workflow.py --resume out/v1/<run_id>",
            "python scripts/compile_workflow.py --self-test",
            "python scripts/compile_workflow.py --manifest fixtures/v1/manifest.json --out out/v1/final",
            "python scripts/execute_packet.py --self-test",
            "python scripts/execute_packet.py --manifest fixtures/v2/manifest.json --out out/v2/final",
            "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
            "python scripts/run_workflow.py --self-test",
            "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
            "docs/v2.5-review-repair-spec.md",
            "docs/v2.5-to-v3.workflow.plan.json",
            "docs/v3-runtime-entry-spec.md",
            "docs/v3-decision.md",
            "needs-human",
            "repair-prepared",
            "tampered next-packet invalidation",
            "`source_plan_path` must be repository-relative in v1",
            "out/v1/v2-final-dry-run-ready-readonly",
            "out/v1/v2-final-dry-run-blocked-risk",
            "repo_tracked_diff_unchanged: true",
            "err_exec_blocked_risk",
            "out/v2/final/summary.json",
            "does not advance beyond the first slice",
        ],
    )
    require_terms(
        "docs/v2-execution-adapter-spec.md",
        [
            "required defaults to true",
            "optional fixture failures",
            "does not exercise the installed-codex path",
            "blocked smoke reuses the v1 run generated by the v2 manifest command",
            "repo_tracked_diff_unchanged",
        ],
    )
    require_terms(
        "docs/automation-roadmap.md",
        [
            "v2 release candidate currently means",
            "docs/v2.5-review-repair-spec.md",
            "docs/v2.5-to-v3.workflow.plan.json",
            "review-contracts.json",
            "trusted v2.5 terminal states",
            "v3 entry runtime implemented",
            "repair-prepared",
            "fixtures/v3/manifest.json",
            "does not execute the next packet",
            "public cli refusal",
            "dangerous verification-command refusal",
            "fixture-command mode",
            "installed codex path remains optional live smoke evidence",
            "v7.5 frontier result review implemented",
            "docs/v7.5-frontier-result-review-spec.md",
            "first review slice implemented",
            "v8 frontier review ingestion implemented",
            "docs/v8-frontier-review-ingestion-spec.md",
            "first ingestion slice implemented",
            "v9 human gate resolution implemented",
            "docs/v9-human-gate-resolution-spec.md",
            "first resolution slice implemented",
            "v10 product cli implemented",
            "docs/v10-product-packaging-spec.md",
            "first cli packaging slice implemented",
            "v11 operator guidance implemented",
            "docs/v11-operator-guidance-spec.md",
            "first operator guidance slice implemented",
            "planned v12",
            "planned v13",
            "mvp implemented",
            "planned v20",
            "docs/v12-to-v20-final-roadmap.md",
            "omx optional",
            "scripts/dwm.py",
        ],
    )
    require_terms(
        "docs/v12-to-v20-final-roadmap.md",
        [
            "status: v12-v20 implemented.",
            "dwm core",
            "dwm runner",
            "codex cli workers",
            "omx remains optional",
            "v12",
            "v20",
        ],
    )
    require_terms(
        "docs/v12-adapter-command-planner-spec.md",
        [
            "status: implemented in `scripts/compile_workflow.py --plan-command`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
        ],
    )
    require_terms(
        "docs/v13-dwm-runner-mvp-spec.md",
        [
            "status: implemented in `scripts/dwm_runner.py`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
        ],
    )
    require_terms(
        "docs/v14-session-worktree-runtime-spec.md",
        [
            "status: implemented in `scripts/dwm_runner.py session`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
        ],
    )
    require_terms(
        "docs/v15-runtime-review-repair-spec.md",
        [
            "status: implemented in `scripts/dwm_runner.py review` and `repair`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
        ],
    )
    require_terms(
        "docs/v16-multi-worker-fanout-spec.md",
        [
            "status: implemented in `scripts/dwm_runner.py fanout` and `fanin`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
        ],
    )
    require_terms(
        "docs/v17-dashboard-hud-spec.md",
        [
            "status: implemented in `scripts/dwm_hud.py`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
            "err_hud_stale_evidence",
            "err_hud_approval_source_blocked",
            "err_hud_approval_unsafe",
            "no worker execution, merge, deployment, external message, secret access, or dependency installation is approved by this artifact",
        ],
    )
    require_terms(
        "docs/v18-plugin-install-packaging-spec.md",
        [
            "status: implemented first install packaging slice in `scripts/dwm_install.py`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
            "claude-compatible portable cli metadata",
            "out/install/",
            "config overwrite requires approval",
        ],
    )
    require_terms(
        "docs/v19-adapter-ecosystem-spec.md",
        [
            "status: implemented first registry slice in `scripts/dwm_adapters.py`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
            "packaging/dwm-adapters.json",
            "fixture",
            "codex",
            "claude",
            "normalized evidence",
            "out/adapters/",
        ],
    )
    require_terms(
        "docs/v20-1.0-release-hardening-spec.md",
        [
            "status: implemented first release-candidate gate in `scripts/dwm_release.py`.",
            "## research and prior art",
            "## product position and non-goals",
            "## workflow architecture",
            "## execution model",
            "## safety and verification gates",
            "## evaluation fixtures",
            "## release plan",
            "docs/v20-compatibility-matrix.md",
            "docs/v20-migration-rollback.md",
        ],
    )
    require_terms(
        "docs/v20-compatibility-matrix.md",
        [
            "schema version `1.0`",
            "omx remains optional",
            "stale evidence",
            "untracked approval",
            "dependency installation",
            "history rewrite",
        ],
    )
    require_terms(
        "docs/v20-migration-rollback.md",
        [
            "v11 operator guidance artifacts",
            "generated outputs are evidence, not source truth",
            "do not mutate the original",
            "rollback means",
            "structured blocked status",
        ],
    )
    require_terms(
        "docs/v20.5-reviewer-gate-spec.md",
        [
            "status: implemented first reviewer gate in `scripts/dwm_review_gate.py`.",
            "independent release-review gate",
            "status: accepted",
            "decision: release-candidate",
            "recomputed `gate_hash`",
            "err_review_gate_stale_release",
            "err_review_gate_missing_gate",
        ],
    )
    require_terms(
        "docs/v20.6-dogfood-replay-spec.md",
        [
            "status: implemented dogfood replay gate in `scripts/dwm_dogfood_replay.py`.",
            "repo status unchanged",
            "workflow-complete",
            "recommendation.action",
            "err_dogfood_command_failed",
            "err_dogfood_repo_diff_changed",
            "err_dogfood_final_status",
        ],
    )
    require_terms(
        "docs/v21-product-shell-spec.md",
        [
            "status: implemented first product shell slice in `scripts/dwm.py`.",
            "dwm plan",
            "dwm run",
            "dwm resume",
            "plan-only",
            "blocked-before-live-execution",
            "err_dwm_shell_live_EXECUTION_BLOCKED".lower(),
        ],
    )
    require_terms(
        "docs/v21-decision.md",
        [
            "decision: keep",
            "python scripts/dwm.py plan \"v21 shell smoke\" --out out/v21/release-plan-smoke --json",
            "python scripts/dwm.py run \"v21 shell smoke\" --out out/v21/release-run-smoke --json",
            "python scripts/dwm.py resume --run out/v21/release-run-smoke --json",
            "`plan.status`: `planned`",
            "`run.status`: `blocked`",
            "`resume.trusted`: `true`",
            "err_dwm_shell_live_execution_blocked",
            "live model planning",
        ],
    )
    require_terms(
        "docs/v7.5-decision.md",
        [
            "decision: keep",
            "python scripts/review_frontier_result.py --self-test",
            "python scripts/review_frontier_result.py --result out/v7/v32-semantic-dogfood --out out/v7.5/v32-semantic-dogfood",
            "python scripts/review_frontier_result.py --resume out/v7.5/v32-semantic-dogfood",
            "`status`: `review-approved`",
            "`resume_state`: `resumable`",
            "`approved_outputs`: `release-decision.md`",
            "does not claim runtime ingestion",
        ],
    )
    require_terms(
        "docs/v8-decision.md",
        [
            "decision: keep",
            "python scripts/ingest_frontier_review.py --self-test",
            "python scripts/ingest_frontier_review.py --review out/v7.5/v32-semantic-dogfood --out out/v8/v32-semantic-dogfood",
            "python scripts/ingest_frontier_review.py --resume out/v8/v32-semantic-dogfood",
            "`status`: `frontier-ready`",
            "`resume_state`: `resumable`",
            "`selected_phase_ids`: `human_gate`",
            "does not claim workflow completion",
        ],
    )
    require_terms(
        "docs/v9-decision.md",
        [
            "decision: keep",
            "python scripts/resolve_human_gate.py --self-test",
            "python scripts/resolve_human_gate.py --frontier out/v8/v32-semantic-dogfood --approval fixtures/v9/approvals/dogfood-human-approval.json --out out/v9/v32-semantic-dogfood",
            "python scripts/resolve_human_gate.py --resume out/v9/v32-semantic-dogfood",
            "`status`: `workflow-complete`",
            "`resume_state`: `resumable`",
            "`human_approved_phase_ids`: `human_gate`",
            "does not claim worker execution",
        ],
    )
    require_terms(
        "docs/v10-decision.md",
        [
            "decision: keep",
            "python scripts/dwm.py --self-test",
            "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json",
            "python scripts/dwm.py doctor --json",
            "python scripts/dwm.py commands --kind release --json",
            "`status`: `workflow-complete`",
            "`doctor_ok`: `true`",
            "`release_command_count`: `50`",
            "does not claim workflow execution",
        ],
    )
    require_terms(
        "docs/v11-decision.md",
        [
            "decision: keep",
            "python scripts/dwm.py --self-test",
            "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json",
            "python scripts/dwm.py commands --kind product --json",
            "`trusted`: `true`",
            "`verified_artifact_hashes`: `4`",
            "`recommendation.action`: `complete`",
            "`product_command_count`: `7`",
            "does not claim workflow execution",
        ],
    )
    require_terms(
        "docs/v2.5-review-repair-spec.md",
        [
            "review-contracts.json",
            "repair-contracts.json",
            "review-approved",
            "changes-requested",
            "repair-prepared",
            "repair-verified",
            "needs-human",
            "does not advance to later workflow phases",
            "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
            "v3 may consume only packets with trusted v2.5 terminal states",
        ],
    )
    require_terms(
        "docs/v2.5-decision.md",
        [
            "decision: keep",
            "python scripts/execute_packet.py --manifest fixtures/v2.5/manifest.json --out out/v2.5/final",
            "`fixture_count`: 9",
            "`required_passed`: 9",
            "`failed`: 0",
            "replacement review",
            "stale review",
            "stale repair",
            "review-contracts.json",
            "repair-contracts.json",
            "does not claim backend repair execution",
        ],
    )
    require_terms(
        "docs/v3-runtime-entry-spec.md",
        [
            "trusted v2.5 terminal states",
            "review-approved",
            "repair-verified",
            "needs-human",
            "--human-approved",
            "repair-prepared",
            "err_runtime_stale_v25",
            "err_runtime_artifact_malformed",
            "ownership sentinel",
            "next phase",
            "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
            "does not execute",
        ],
    )
    require_terms(
        "docs/v3-decision.md",
        [
            "decision: keep",
            "python scripts/run_workflow.py --manifest fixtures/v3/manifest.json --out out/v3/final",
            "`fixture_count`: 13",
            "`required_passed`: 13",
            "`failed`: 0",
            "needs-human approval is not sufficient",
            "manual-only `review-approved`",
            "stale v2.5",
            "tampered v3 artifacts",
            "next phase candidate",
            "unmatched first-slice",
            "non-owned runtime directories",
            "does not claim execution of later packets",
        ],
    )
    require_terms(
        "docs/v0.5-decision.md",
        [
            "decision: keep",
            "12 fixtures",
            "workflow-router-skill",
            "claude-agent-workflow-designer",
            "samples/v0.5/raw/",
            "samples/v0.5/consumer/",
            "source-hashed normalization failure",
            "does not claim runtime execution or live model generation",
            "current skill hash",
            "source-backed evidence",
            "blinded sample-review provenance",
            "out/v0.5/summary.json",
        ],
    )
    require_fixture_smoke()
    require_release_commands_pass()
    require_decision_summary_consistency()
    require_v1_decision_summary_consistency()
    require_v2_decision_summary_consistency()
    require_v25_decision_summary_consistency()
    require_v3_decision_summary_consistency()
    require_v75_decision_summary_consistency()
    require_v8_decision_summary_consistency()
    require_v9_decision_summary_consistency()
    require_v10_decision_summary_consistency()
    require_v11_decision_summary_consistency()
    require_v13_decision_summary_consistency()
    require_v14_decision_summary_consistency()
    require_v15_decision_summary_consistency()
    require_v16_decision_summary_consistency()
    require_v17_decision_summary_consistency()
    require_v18_decision_summary_consistency()
    require_v19_decision_summary_consistency()
    require_v20_decision_summary_consistency()
    require_v205_decision_summary_consistency()
    require_v206_decision_summary_consistency()
    print("contract smoke: pass")


if __name__ == "__main__":
    main()
