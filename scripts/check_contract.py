#!/usr/bin/env python3
"""Check release-contract terms for the dynamic workflow designer skill."""

from pathlib import Path
import argparse
import json
import re
import shutil
import signal
import subprocess
import sys

import evaluate_plan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMMAND_TIMEOUT_SECONDS = 180
LONG_COMMAND_TIMEOUT_SECONDS = 420
DEFAULT_STEP_TIMEOUT_SECONDS = 900
SHOW_PROGRESS = False
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


def run_contract_command(args: list[str], *, timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    if SHOW_PROGRESS:
        print("contract command: " + " ".join(args), file=sys.stderr, flush=True)
    try:
        return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "release command failed: "
            + " ".join(args)
            + f"\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            "release command timed out after "
            + str(timeout_seconds)
            + "s: "
            + " ".join(args)
            + f"\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}"
        ) from exc


def run_contract_step(label: str, callback, *, timeout_seconds: int = DEFAULT_STEP_TIMEOUT_SECONDS) -> None:
    if SHOW_PROGRESS:
        print(f"contract step: {label}", file=sys.stderr, flush=True)

    def timeout_handler(_signum, _frame) -> None:
        raise SystemExit(f"contract step timed out after {timeout_seconds}s: {label}")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        callback()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def release_command_timeout(command: list[str]) -> int:
    command_text = " ".join(command)
    if "scripts/dwm_release.py" in command_text:
        return LONG_COMMAND_TIMEOUT_SECONDS
    if "scripts/dwm_demo.py --self-test" in command_text:
        return LONG_COMMAND_TIMEOUT_SECONDS
    return DEFAULT_COMMAND_TIMEOUT_SECONDS


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
            timeout_seconds=LONG_COMMAND_TIMEOUT_SECONDS,
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


def require_v22_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_roles.py --manifest fixtures/v22/manifest.json --out out/roles/v22-final",
        "planner",
        "explorer",
        "worker",
        "reviewer",
        "verifier",
        "operator",
        "does not claim role execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v22-decision.md does not match V22 summary: {missing}")


def require_v22_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_roles.py",
                "--manifest",
                "fixtures/v22/manifest.json",
                "--out",
                "out/roles/v22-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v22_decision_summary_text(summary, (ROOT / "docs" / "v22-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V22 decision consistency failed: {exc}") from exc


def require_v23_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_benchmark.py --manifest fixtures/v23/manifest.json --out out/benchmarks/v23-final",
        "failing-test-fix",
        "small-refactor",
        "auth-permission-audit",
        "ui-render-regression",
        "docs-code-consistency",
        "multi-file-migration",
        "does not claim live harness execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v23-decision.md does not match V23 summary: {missing}")


def require_v23_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_benchmark.py",
                "--manifest",
                "fixtures/v23/manifest.json",
                "--out",
                "out/benchmarks/v23-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v23_decision_summary_text(summary, (ROOT / "docs" / "v23-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V23 decision consistency failed: {exc}") from exc


def require_v24_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_benchmark.py --manifest fixtures/v24/manifest.json --out out/benchmarks-live/v24-final",
        "fixture-control",
        "adapter-availability",
        "err_live_benchmark_corpus_missing",
        "err_live_benchmark_unsafe_mode",
        "err_live_benchmark_stale_score",
        "err_live_benchmark_adapter_unavailable",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v24-decision.md does not match V24 summary: {missing}")


def require_v24_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_benchmark.py",
                "--manifest",
                "fixtures/v24/manifest.json",
                "--out",
                "out/benchmarks-live/v24-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v24_decision_summary_text(summary, (ROOT / "docs" / "v24-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V24 decision consistency failed: {exc}") from exc


def require_v25_tasks_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_benchmark_tasks.py --manifest fixtures/v25/manifest.json --out out/benchmark-tasks/v25-final",
        "materialize-suite",
        "verify-initial",
        "err_benchmark_tasks_corpus_mismatch",
        "err_benchmark_tasks_unsafe_path",
        "err_benchmark_tasks_stale_template",
        "does not claim task solving",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v25-decision.md does not match V25 summary: {missing}")


def require_v25_tasks_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_benchmark_tasks.py",
                "--manifest",
                "fixtures/v25/manifest.json",
                "--out",
                "out/benchmark-tasks/v25-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v25_tasks_decision_summary_text(summary, (ROOT / "docs" / "v25-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V25 decision consistency failed: {exc}") from exc


def require_v26_attempts_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_benchmark_attempts.py --manifest fixtures/v26/manifest.json --out out/benchmark-attempts/v26-final",
        "scripted-fixture",
        "attempt.json",
        "changes.json",
        "verification.json",
        "err_benchmark_attempts_missing_tasks",
        "err_benchmark_attempts_stale_plan",
        "err_benchmark_attempts_unsafe_path",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v26-decision.md does not match V26 summary: {missing}")


def require_v26_attempts_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_benchmark_attempts.py",
                "--manifest",
                "fixtures/v26/manifest.json",
                "--out",
                "out/benchmark-attempts/v26-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v26_attempts_decision_summary_text(summary, (ROOT / "docs" / "v26-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V26 decision consistency failed: {exc}") from exc


def require_v27_smoke_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_adapter_smoke.py --manifest fixtures/v27/manifest.json --out out/adapter-smoke/v27-final",
        "adapter-smoke.json",
        "err_adapter_smoke_unavailable",
        "err_adapter_smoke_unsafe_command",
        "err_adapter_smoke_unknown_task",
        "err_adapter_smoke_stale_template",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v27-decision.md does not match V27 summary: {missing}")


def require_v27_smoke_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_adapter_smoke.py",
                "--manifest",
                "fixtures/v27/manifest.json",
                "--out",
                "out/adapter-smoke/v27-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v27_smoke_decision_summary_text(summary, (ROOT / "docs" / "v27-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V27 decision consistency failed: {exc}") from exc


def require_v28_live_plan_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_attempt_plan.py --manifest fixtures/v28/manifest.json --out out/live-attempt-plans/v28-final",
        "command-plan.json",
        "prompt.md",
        "err_live_attempt_adapter_unavailable",
        "err_live_attempt_stale_smoke",
        "err_live_attempt_unknown_task",
        "err_live_attempt_unsafe_command",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v28-decision.md does not match V28 summary: {missing}")


def require_v28_live_plan_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_attempt_plan.py",
                "--manifest",
                "fixtures/v28/manifest.json",
                "--out",
                "out/live-attempt-plans/v28-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v28_live_plan_decision_summary_text(summary, (ROOT / "docs" / "v28-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V28 decision consistency failed: {exc}") from exc


def require_v29_runner_preflight_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_runner_preflight.py --manifest fixtures/v29/manifest.json --out out/live-runner-preflight/v29-final",
        "preflight.json",
        "ready-for-human-run",
        "err_live_runner_plan_skipped",
        "err_live_runner_stale_plan",
        "err_live_runner_policy_blocked",
        "err_live_runner_artifact_missing",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v29-decision.md does not match V29 summary: {missing}")


def require_v29_runner_preflight_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_runner_preflight.py",
                "--manifest",
                "fixtures/v29/manifest.json",
                "--out",
                "out/live-runner-preflight/v29-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v29_runner_preflight_decision_summary_text(summary, (ROOT / "docs" / "v29-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V29 decision consistency failed: {exc}") from exc


def require_v30_receipt_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_receipt.py --manifest fixtures/v30/manifest.json --out out/live-receipts/v30-final",
        "receipt.json",
        "receipt-ledger.json",
        "err_live_receipt_preflight_not_ready",
        "err_live_receipt_stale_preflight",
        "err_live_receipt_command_mismatch",
        "err_live_receipt_artifact_missing",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v30-decision.md does not match V30 summary: {missing}")


def require_v30_receipt_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_receipt.py",
                "--manifest",
                "fixtures/v30/manifest.json",
                "--out",
                "out/live-receipts/v30-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v30_receipt_decision_summary_text(summary, (ROOT / "docs" / "v30-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V30 decision consistency failed: {exc}") from exc


def require_v31_receipt_judge_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_receipt_judge.py --manifest fixtures/v31/manifest.json --out out/live-receipt-judgments/v31-final",
        "judgment.json",
        "err_live_receipt_judge_artifact_missing",
        "err_live_receipt_judge_stale_receipt",
        "err_live_receipt_judge_receipt_not_accepted",
        "err_live_receipt_judge_hash_mismatch",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v31-decision.md does not match V31 summary: {missing}")


def require_v31_receipt_judge_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_receipt_judge.py",
                "--manifest",
                "fixtures/v31/manifest.json",
                "--out",
                "out/live-receipt-judgments/v31-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v31_receipt_judge_decision_summary_text(summary, (ROOT / "docs" / "v31-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V31 decision consistency failed: {exc}") from exc


def require_v32_live_score_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_score.py --manifest fixtures/v32/manifest.json --out out/live-scores/v32-final",
        "score.json",
        "err_live_score_artifact_missing",
        "err_live_score_stale_judgment",
        "err_live_score_task_mismatch",
        "err_live_score_hash_mismatch",
        "err_live_score_verification_invalid",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v32-decision.md does not match V32 summary: {missing}")


def require_v32_live_score_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_score.py",
                "--manifest",
                "fixtures/v32/manifest.json",
                "--out",
                "out/live-scores/v32-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v32_live_score_decision_summary_text(summary, (ROOT / "docs" / "v32-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V32 decision consistency failed: {exc}") from exc


def require_v33_live_score_aggregate_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_score_aggregate.py --manifest fixtures/v33/manifest.json --out out/live-score-aggregates/v33-final",
        "aggregate-score.json",
        "err_live_score_aggregate_artifact_missing",
        "err_live_score_aggregate_stale_score",
        "err_live_score_aggregate_task_missing",
        "err_live_score_aggregate_task_duplicate",
        "err_live_score_aggregate_unsupported_claim",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v33-decision.md does not match V33 summary: {missing}")


def require_v33_live_score_aggregate_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_score_aggregate.py",
                "--manifest",
                "fixtures/v33/manifest.json",
                "--out",
                "out/live-score-aggregates/v33-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v33_live_score_aggregate_decision_summary_text(summary, (ROOT / "docs" / "v33-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V33 decision consistency failed: {exc}") from exc


def require_v34_live_score_review_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_score_review.py --manifest fixtures/v34/manifest.json --out out/live-score-reviews/v34-final",
        "reviewed-score.json",
        "err_live_score_review_artifact_missing",
        "err_live_score_review_stale_aggregate",
        "err_live_score_review_task_mismatch",
        "err_live_score_review_hash_mismatch",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v34-decision.md does not match V34 summary: {missing}")


def require_v34_live_score_review_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_score_review.py",
                "--manifest",
                "fixtures/v34/manifest.json",
                "--out",
                "out/live-score-reviews/v34-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v34_live_score_review_decision_summary_text(summary, (ROOT / "docs" / "v34-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V34 decision consistency failed: {exc}") from exc


def require_v35_live_report_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_live_report.py --manifest fixtures/v35/manifest.json --out out/live-reports/v35-final",
        "report.json",
        "report.md",
        "err_live_report_artifact_missing",
        "err_live_report_stale_review",
        "err_live_report_hash_mismatch",
        "err_live_report_unsupported_claim",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v35-decision.md does not match V35 summary: {missing}")


def require_v35_live_report_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_live_report.py",
                "--manifest",
                "fixtures/v35/manifest.json",
                "--out",
                "out/live-reports/v35-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v35_live_report_decision_summary_text(summary, (ROOT / "docs" / "v35-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V35 decision consistency failed: {exc}") from exc


def require_v36_readme_graph_decision_summary_text(summary: dict[str, object], decision_text: str) -> None:
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
        "python scripts/dwm_readme_benchmark_graph.py --manifest fixtures/v36/manifest.json --out out/readme-benchmark-graphs/v36-final",
        "benchmark-graph.json",
        "benchmark-graph.svg",
        "readme-snippet.md",
        "err_readme_graph_artifact_missing",
        "err_readme_graph_stale_report",
        "err_readme_graph_metrics_invalid",
        "does not claim live model execution",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in normalized_decision_text]
    if missing:
        raise SystemExit(f"docs/v36-decision.md does not match V36 summary: {missing}")


def require_v36_readme_graph_decision_summary_consistency() -> None:
    try:
        completed = run_contract_command(
            [
                sys.executable,
                "scripts/dwm_readme_benchmark_graph.py",
                "--manifest",
                "fixtures/v36/manifest.json",
                "--out",
                "out/readme-benchmark-graphs/v36-final",
            ],
        )
        summary = json.loads(completed.stdout)
        require_v36_readme_graph_decision_summary_text(summary, (ROOT / "docs" / "v36-decision.md").read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"V36 decision consistency failed: {exc}") from exc


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
        [sys.executable, "scripts/dwm_adapters.py", "--manifest", "fixtures/v49/manifest.json", "--out", "out/adapters/v49-final"],
        [sys.executable, "scripts/dwm_release.py", "--self-test"],
        [sys.executable, "scripts/dwm_release_candidate.py", "--self-test"],
        [sys.executable, "scripts/dwm_release_candidate.py", "--manifest", "fixtures/v50/manifest.json", "--out", "out/release-candidates/v50-final"],
        [sys.executable, "scripts/dwm_adapter_live_matrix.py", "--self-test"],
        [sys.executable, "scripts/dwm_adapter_live_matrix.py", "--manifest", "fixtures/v55/manifest.json", "--out", "out/adapter-live-matrix/v55-final"],
        [sys.executable, "scripts/dwm_demo.py", "--self-test"],
        [sys.executable, "scripts/dwm_demo.py", "--manifest", "fixtures/v51/manifest.json", "--out", "out/demo/v51-final"],
        [sys.executable, "scripts/dwm_demo.py", "--manifest", "fixtures/v53/manifest.json", "--out", "out/demo/v53-final"],
        [sys.executable, "scripts/dwm_review_gate.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_replay.py", "--self-test"],
        [sys.executable, "scripts/dwm.py", "plan", "V21 shell smoke", "--out", "out/v21/release-plan-smoke", "--json"],
        [sys.executable, "scripts/dwm.py", "run", "V21 shell smoke", "--out", "out/v21/release-run-smoke", "--json"],
        [sys.executable, "scripts/dwm.py", "resume", "--run", "out/v21/release-run-smoke", "--json"],
        [sys.executable, "scripts/dwm_roles.py", "--self-test"],
        [sys.executable, "scripts/dwm_roles.py", "--manifest", "fixtures/v22/manifest.json", "--out", "out/roles/v22-final"],
        [sys.executable, "scripts/dwm_benchmark.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark.py", "--manifest", "fixtures/v23/manifest.json", "--out", "out/benchmarks/v23-final"],
        [sys.executable, "scripts/dwm_live_benchmark.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_benchmark.py", "--manifest", "fixtures/v24/manifest.json", "--out", "out/benchmarks-live/v24-final"],
        [sys.executable, "scripts/dwm_benchmark_tasks.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_tasks.py", "--manifest", "fixtures/v25/manifest.json", "--out", "out/benchmark-tasks/v25-final"],
        [sys.executable, "scripts/dwm_benchmark_attempts.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_attempts.py", "--manifest", "fixtures/v26/manifest.json", "--out", "out/benchmark-attempts/v26-final"],
        [sys.executable, "scripts/dwm_adapter_smoke.py", "--self-test"],
        [sys.executable, "scripts/dwm_adapter_smoke.py", "--manifest", "fixtures/v27/manifest.json", "--out", "out/adapter-smoke/v27-final"],
        [sys.executable, "scripts/dwm_live_attempt_plan.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_attempt_plan.py", "--manifest", "fixtures/v28/manifest.json", "--out", "out/live-attempt-plans/v28-final"],
        [sys.executable, "scripts/dwm_live_runner_preflight.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_runner_preflight.py", "--manifest", "fixtures/v29/manifest.json", "--out", "out/live-runner-preflight/v29-final"],
        [sys.executable, "scripts/dwm_live_receipt.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_receipt.py", "--manifest", "fixtures/v30/manifest.json", "--out", "out/live-receipts/v30-final"],
        [sys.executable, "scripts/dwm_live_receipt_judge.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_receipt_judge.py", "--manifest", "fixtures/v31/manifest.json", "--out", "out/live-receipt-judgments/v31-final"],
        [sys.executable, "scripts/dwm_live_score.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_score.py", "--manifest", "fixtures/v32/manifest.json", "--out", "out/live-scores/v32-final"],
        [sys.executable, "scripts/dwm_live_score_aggregate.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_score_aggregate.py", "--manifest", "fixtures/v33/manifest.json", "--out", "out/live-score-aggregates/v33-final"],
        [sys.executable, "scripts/dwm_live_score_review.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_score_review.py", "--manifest", "fixtures/v34/manifest.json", "--out", "out/live-score-reviews/v34-final"],
        [sys.executable, "scripts/dwm_live_report.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_report.py", "--manifest", "fixtures/v35/manifest.json", "--out", "out/live-reports/v35-final"],
        [sys.executable, "scripts/dwm_readme_benchmark_graph.py", "--self-test"],
        [sys.executable, "scripts/dwm_readme_benchmark_graph.py", "--manifest", "fixtures/v36/manifest.json", "--out", "out/readme-benchmark-graphs/v36-final"],
        [sys.executable, "scripts/dwm_benchmark_history.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_history.py", "--manifest", "fixtures/v38/manifest.json", "--out", "out/benchmark-history/v38-final"],
        [sys.executable, "scripts/dwm_benchmark_promotion.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_promotion.py", "--manifest", "fixtures/v39/manifest.json", "--out", "out/benchmark-promotions/v39-final"],
        [sys.executable, "scripts/dwm_benchmark_snapshot.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_snapshot.py", "--manifest", "fixtures/v40/manifest.json", "--out", "out/benchmark-snapshots/v40-final"],
        [sys.executable, "scripts/dwm_benchmark_series.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_series.py", "--manifest", "fixtures/v41/manifest.json", "--out", "out/benchmark-series/v41-final"],
        [sys.executable, "scripts/dwm_benchmark_candidate.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_candidate.py", "--manifest", "fixtures/v42/manifest.json", "--out", "out/benchmark-candidates/v42-final"],
        [sys.executable, "scripts/dwm_dogfood_attempts.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_attempts.py", "--manifest", "fixtures/v54/manifest.json", "--out", "out/dogfood-attempts/v54-final"],
        [sys.executable, "scripts/dwm_dogfood_measure.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_measure.py", "--manifest", "fixtures/v56/manifest.json", "--out", "out/dogfood-measurements/v56-final"],
        [sys.executable, "scripts/dwm_dogfood_pair.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_pair.py", "--manifest", "fixtures/v57/manifest.json", "--out", "out/dogfood-pairs/v57-final"],
        [sys.executable, "scripts/dwm_dogfood_pair_series.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_pair_series.py", "--manifest", "fixtures/v58/manifest.json", "--out", "out/dogfood-pair-series/v58-final"],
        [sys.executable, "scripts/dwm_dogfood_chart_candidate.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_chart_candidate.py", "--manifest", "fixtures/v59/manifest.json", "--out", "out/dogfood-chart-candidates/v59-final"],
        [sys.executable, "scripts/dwm_dogfood_chart_review.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_chart_review.py", "--manifest", "fixtures/v60/manifest.json", "--out", "out/dogfood-chart-reviews/v60-final"],
        [sys.executable, "scripts/dwm_dogfood_acquire.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_acquire.py", "--manifest", "fixtures/v61/manifest.json", "--out", "out/dogfood-acquisitions/v61-final"],
        [sys.executable, "scripts/dwm_dogfood_operator.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_operator.py", "--manifest", "fixtures/v62/manifest.json", "--out", "out/dogfood-operator/v62-final"],
        [sys.executable, "scripts/dwm_dogfood_operator.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_operator.py", "--manifest", "fixtures/v63/manifest.json", "--out", "out/dogfood-operator/v63-final"],
        [sys.executable, "scripts/dwm_dogfood_pair_select.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_pair_select.py", "--manifest", "fixtures/v64/manifest.json", "--out", "out/dogfood-pair-selections/v64-final"],
        [sys.executable, "scripts/dwm_dogfood_chart_render.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_chart_render.py", "--manifest", "fixtures/v65/manifest.json", "--out", "out/dogfood-chart-renders/v65-final"],
        [sys.executable, "scripts/dwm_dogfood_progress.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_progress.py", "--manifest", "fixtures/v66/manifest.json", "--out", "out/dogfood-progress/v66-final"],
        [sys.executable, "scripts/dwm_dogfood_progress_asset_promotion.py", "--self-test"],
        [sys.executable, "scripts/dwm_dogfood_progress_asset_promotion.py", "--manifest", "fixtures/v67/manifest.json", "--out", "out/dogfood-progress-asset-promotions/v67-final"],
        [sys.executable, "scripts/check_readme_quality.py", "--self-test"],
        [sys.executable, "scripts/check_readme_quality.py", "README.md"],
        [sys.executable, "scripts/dwm_release_timing.py", "--self-test"],
        [sys.executable, "scripts/dwm_release_timing.py", "--manifest", "fixtures/v71/manifest.json", "--out", "out/release-timing/v71-final"],
        [sys.executable, "scripts/dwm_release_timing_history.py", "--self-test"],
        [sys.executable, "scripts/dwm_release_timing_history.py", "--manifest", "fixtures/v72/manifest.json", "--out", "out/release-timing-history/v72-final"],
        [sys.executable, "scripts/dwm_large_workflow_control.py", "--self-test"],
        [sys.executable, "scripts/dwm_large_workflow_control.py", "--manifest", "fixtures/v73/manifest.json", "--out", "out/large-workflow-control/v73-final"],
        [sys.executable, "scripts/evaluate_plan.py", "--plan", "docs/v73-large-workflow-control.workflow.plan.json"],
        [sys.executable, "scripts/dwm_large_workflow_dogfood.py", "--self-test"],
        [sys.executable, "scripts/dwm_large_workflow_dogfood.py", "--manifest", "fixtures/v74/manifest.json", "--out", "out/large-workflow-dogfood/v74-final"],
        [sys.executable, "scripts/dwm_large_workflow_dogfood.py", "record", "--run", "out/v9/v32-semantic-dogfood", "--out", "out/large-workflow-dogfood/v74-canonical"],
        [sys.executable, "scripts/dwm_large_workflow_next.py", "--self-test"],
        [sys.executable, "scripts/dwm_large_workflow_next.py", "--manifest", "fixtures/v75/manifest.json", "--out", "out/large-workflow-next/v75-final"],
        [sys.executable, "scripts/dwm_large_workflow_next.py", "select", "--control", "out/large-workflow-dogfood/v74-canonical/dogfood-control.json", "--out", "out/large-workflow-next/v75-canonical"],
        [sys.executable, "scripts/dwm_large_workflow_queue_bridge.py", "--self-test"],
        [sys.executable, "scripts/dwm_large_workflow_queue_bridge.py", "--manifest", "fixtures/v76/manifest.json", "--out", "out/large-workflow-queue-bridge/v76-final"],
        [sys.executable, "scripts/dwm_large_workflow_queue_bridge.py", "bridge", "--selection", "out/large-workflow-next/v75-canonical/large-workflow-next.json", "--out", "out/large-workflow-queue-bridge/v76-canonical", "--queue-out", "out/workflow-queues/v76-canonical"],
        [sys.executable, "scripts/dwm_large_workflow_queue_preflight.py", "--self-test"],
        [sys.executable, "scripts/dwm_large_workflow_queue_preflight.py", "--manifest", "fixtures/v77/manifest.json", "--out", "out/large-workflow-queue-preflight/v77-final"],
        [sys.executable, "scripts/dwm_large_workflow_queue_preflight.py", "preflight", "--queue", "out/workflow-queues/v76-canonical/queue.json", "--out", "out/large-workflow-queue-preflight/v77-canonical"],
        [sys.executable, "scripts/dwm_graph_timing_gate.py", "--self-test"],
        [sys.executable, "scripts/dwm_graph_timing_gate.py", "--manifest", "fixtures/v78/manifest.json", "--out", "out/graph-timing/v78-final"],
        [sys.executable, "scripts/dwm_graph_timing_gate.py", "check", "--progress", "out/dogfood-progress/local-v66-current/dogfood-progress.json", "--readiness", "out/dogfood-pair-series/local-v64-selected-series/graph-readiness.json", "--preflight", "out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json", "--out", "out/graph-timing/v78-canonical"],
        [sys.executable, "scripts/dwm_readme_graph_visibility.py", "--self-test"],
        [sys.executable, "scripts/dwm_readme_graph_visibility.py", "--manifest", "fixtures/v79/manifest.json", "--out", "out/readme-graph-visibility/v79-final"],
        [sys.executable, "scripts/dwm_readme_graph_visibility.py", "audit", "--readme", "README.md", "--timing", "out/graph-timing/v78-canonical/graph-timing.json", "--out", "out/readme-graph-visibility/v79-canonical"],
        [sys.executable, "scripts/dwm_continuation_boundary.py", "--self-test"],
        [sys.executable, "scripts/dwm_continuation_boundary.py", "--manifest", "fixtures/v80/manifest.json", "--out", "out/continuation-boundaries/v80-final"],
        [sys.executable, "scripts/dwm_continuation_boundary.py", "assess", "--preflight", "out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json", "--timing", "out/graph-timing/v78-canonical/graph-timing.json", "--visibility", "out/readme-graph-visibility/v79-canonical/readme-graph-visibility.json", "--out", "out/continuation-boundaries/v80-canonical"],
        [sys.executable, "scripts/dwm_multi_slice_batch.py", "--self-test"],
        [sys.executable, "scripts/dwm_multi_slice_batch.py", "--manifest", "fixtures/v81/manifest.json", "--out", "out/multi-slice-batches/v81-final"],
        [sys.executable, "scripts/dwm_multi_slice_batch.py", "plan", "--boundary", "out/continuation-boundaries/v80-canonical/continuation-boundary.json", "--out", "out/multi-slice-batches/v81-canonical"],
        [sys.executable, "scripts/dwm_execution_receipt_schema.py", "--self-test"],
        [sys.executable, "scripts/dwm_execution_receipt_schema.py", "--manifest", "fixtures/v82/manifest.json", "--out", "out/execution-receipt-schemas/v82-final"],
        [sys.executable, "scripts/dwm_execution_receipt_schema.py", "preflight", "--batch", "out/multi-slice-batches/v81-canonical/multi-slice-batch.json", "--out", "out/execution-receipt-schemas/v82-canonical"],
        [sys.executable, "scripts/dwm_runner_receipt_dry_run.py", "--self-test"],
        [sys.executable, "scripts/dwm_runner_receipt_dry_run.py", "--manifest", "fixtures/v83/manifest.json", "--out", "out/runner-receipt-dry-runs/v83-final"],
        [sys.executable, "scripts/dwm_runner_receipt_dry_run.py", "dry-run", "--schema", "out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json", "--batch", "out/multi-slice-batches/v81-canonical/multi-slice-batch.json", "--out", "out/runner-receipt-dry-runs/v83-canonical"],
        [sys.executable, "scripts/dwm_installed_surface_audit.py", "--self-test"],
        [sys.executable, "scripts/dwm_installed_surface_audit.py", "--manifest", "fixtures/v84/manifest.json", "--out", "out/installed-surface-audits/v84-final"],
        [sys.executable, "scripts/dwm_installed_surface_audit.py", "audit", "--active-skill", "SKILL.md", "--out", "out/installed-surface-audits/v84-canonical"],
        [sys.executable, "scripts/dwm_workflow_activation.py", "--self-test"],
        [sys.executable, "scripts/dwm_workflow_activation.py", "--manifest", "fixtures/v85/manifest.json", "--out", "out/workflow-activations/v85-final"],
        [sys.executable, "scripts/dwm_workflow_activation.py", "activate", "--audit", "out/installed-surface-audits/v84-canonical/installed-surface-audit.json", "--receipt", "out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json", "--status", "out/v9/v32-semantic-dogfood/status.json", "--out", "out/workflow-activations/v85-canonical"],
        [sys.executable, "scripts/dwm_brand_boundary_audit.py", "--self-test"],
        [sys.executable, "scripts/dwm_brand_boundary_audit.py", "--manifest", "fixtures/v87/manifest.json", "--out", "out/brand-boundary-audits/v87-final"],
        [sys.executable, "scripts/dwm_brand_boundary_audit.py", "audit", "--out", "out/brand-boundary-audits/v87-canonical"],
        [sys.executable, "scripts/dwm_roadmap_reconciliation.py", "--self-test"],
        [sys.executable, "scripts/dwm_roadmap_reconciliation.py", "--manifest", "fixtures/v88/manifest.json", "--out", "out/roadmap-reconciliations/v88-final"],
        [sys.executable, "scripts/dwm_roadmap_reconciliation.py", "audit", "--out", "out/roadmap-reconciliations/v88-canonical"],
        [sys.executable, "scripts/dwm_command_safety.py", "--self-test"],
        [sys.executable, "scripts/dwm_command_safety.py", "--manifest", "fixtures/v89/manifest.json", "--out", "out/command-safety/v89-final"],
        [sys.executable, "scripts/dwm_workflow_activation.py", "--manifest", "fixtures/v90/manifest.json", "--out", "out/workflow-activations/v90-final"],
        [
            sys.executable,
            "scripts/dwm_workflow_activation.py",
            "activate",
            "--audit",
            "out/installed-surface-audits/v84-canonical/installed-surface-audit.json",
            "--receipt",
            "out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json",
            "--status",
            "out/v9/v32-semantic-dogfood/status.json",
            "--brand-audit",
            "out/brand-boundary-audits/v87-canonical/brand-boundary-audit.json",
            "--roadmap-reconciliation",
            "out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json",
            "--command-safety",
            "out/command-safety/v89-final/summary.json",
            "--out",
            "out/workflow-activations/v90-canonical",
        ],
        [sys.executable, "scripts/dwm_evidence_oracle.py", "--self-test"],
        [sys.executable, "scripts/dwm_evidence_oracle.py", "--manifest", "fixtures/v92/manifest.json", "--out", "out/evidence-oracles/v92-final"],
        [sys.executable, "scripts/dwm_evidence_oracle.py", "verify", "--claims", "fixtures/v92/canonical-claims.json", "--out", "out/evidence-oracles/v92-canonical"],
        [sys.executable, "scripts/dwm_workflow_narrative.py", "--self-test"],
        [sys.executable, "scripts/dwm_workflow_narrative.py", "--manifest", "fixtures/v93/manifest.json", "--out", "out/workflow-narratives/v93-final"],
        [
            sys.executable,
            "scripts/dwm_workflow_narrative.py",
            "render",
            "--roadmap",
            "out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json",
            "--command-safety",
            "out/command-safety/v89-final/summary.json",
            "--activation",
            "out/workflow-activations/v90-canonical/workflow-activation.json",
            "--oracle",
            "out/evidence-oracles/v92-canonical/evidence-oracle.json",
            "--out",
            "out/workflow-narratives/v93-canonical",
        ],
        [sys.executable, "scripts/dwm_control_deck_score.py", "--self-test"],
        [sys.executable, "scripts/dwm_control_deck_score.py", "--manifest", "fixtures/v94/manifest.json", "--out", "out/control-deck-scores/v94-final"],
        [
            sys.executable,
            "scripts/dwm_control_deck_score.py",
            "score",
            "--narrative",
            "out/workflow-narratives/v93-canonical/workflow-narrative.json",
            "--roadmap",
            "out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json",
            "--command-safety",
            "out/command-safety/v89-final/summary.json",
            "--activation",
            "out/workflow-activations/v90-canonical/workflow-activation.json",
            "--oracle",
            "out/evidence-oracles/v92-canonical/evidence-oracle.json",
            "--out",
            "out/control-deck-scores/v94-canonical",
        ],
        [sys.executable, "scripts/dwm_control_deck_score_history.py", "--self-test"],
        [sys.executable, "scripts/dwm_control_deck_score_history.py", "--manifest", "fixtures/v95/manifest.json", "--out", "out/control-deck-score-history/v95-final"],
        [
            sys.executable,
            "scripts/dwm_control_deck_score_history.py",
            "build",
            "--score",
            "out/control-deck-scores/v94-canonical",
            "--out",
            "out/control-deck-score-history/v95-canonical",
        ],
        [sys.executable, "scripts/dwm_metric_ladder.py", "--self-test"],
        [sys.executable, "scripts/dwm_metric_ladder.py", "--manifest", "fixtures/v96/manifest.json", "--out", "out/metric-ladders/v96-final"],
        [
            sys.executable,
            "scripts/dwm_metric_ladder.py",
            "assess",
            "--history",
            "out/control-deck-score-history/v95-canonical/control-deck-score-history.json",
            "--graph-timing",
            "out/graph-timing/v78-canonical/graph-timing.json",
            "--out",
            "out/metric-ladders/v96-canonical",
        ],
        [sys.executable, "scripts/dwm_benchmark_readiness.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_readiness.py", "--manifest", "fixtures/v97/manifest.json", "--out", "out/benchmark-readiness/v97-final"],
        [
            sys.executable,
            "scripts/dwm_benchmark_readiness.py",
            "assess",
            "--ladder",
            "out/metric-ladders/v96-canonical/metric-ladder.json",
            "--out",
            "out/benchmark-readiness/v97-canonical",
        ],
        [sys.executable, "scripts/dwm_wave_operator.py", "--self-test"],
        [sys.executable, "scripts/dwm_wave_operator.py", "--manifest", "fixtures/v98/manifest.json", "--out", "out/wave-operators/v98-final"],
        [
            sys.executable,
            "scripts/dwm_wave_operator.py",
            "select",
            "--readiness",
            "out/benchmark-readiness/v97-canonical/benchmark-readiness.json",
            "--activation",
            "out/workflow-activations/v90-canonical/workflow-activation.json",
            "--out",
            "out/wave-operators/v98-canonical",
        ],
        [sys.executable, "scripts/dwm_wave_receipt.py", "--self-test"],
        [sys.executable, "scripts/dwm_wave_receipt.py", "--manifest", "fixtures/v99/manifest.json", "--out", "out/wave-receipts/v99-final"],
        [
            sys.executable,
            "scripts/dwm_wave_receipt.py",
            "record",
            "--wave",
            "out/wave-operators/v98-canonical/wave-operator.json",
            "--acquisition",
            "out/dogfood-acquisitions/v61-final/summary.json",
            "--out",
            "out/wave-receipts/v99-canonical",
        ],
        [sys.executable, "scripts/dwm_promotion_evidence.py", "--self-test"],
        [sys.executable, "scripts/dwm_promotion_evidence.py", "--manifest", "fixtures/v100/manifest.json", "--out", "out/promotion-evidence/v100-final"],
        [
            sys.executable,
            "scripts/dwm_promotion_evidence.py",
            "record",
            "--receipt",
            "out/wave-receipts/v99-canonical/wave-receipt.json",
            "--readiness",
            "out/benchmark-readiness/v97-canonical/benchmark-readiness.json",
            "--out",
            "out/promotion-evidence/v100-canonical",
        ],
        [sys.executable, "scripts/dwm_promotion_route.py", "--self-test"],
        [sys.executable, "scripts/dwm_promotion_route.py", "--manifest", "fixtures/v101/manifest.json", "--out", "out/promotion-routes/v101-final"],
        [
            sys.executable,
            "scripts/dwm_promotion_route.py",
            "route",
            "--evidence",
            "out/promotion-evidence/v100-canonical/promotion-evidence.json",
            "--out",
            "out/promotion-routes/v101-canonical",
        ],
        [sys.executable, "scripts/dwm_live_proof.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_proof.py", "--manifest", "fixtures/v102/manifest.json", "--out", "out/v102/final"],
        [sys.executable, "scripts/dwm_live_proof.py", "--manifest", "fixtures/v103/manifest.json", "--out", "out/v103/final"],
        [sys.executable, "scripts/v105_verify_wedge.py", "--self-test"],
        [sys.executable, "scripts/v106_multi_wave.py", "--self-test"],
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
    for index, command in enumerate(commands, 1):
        if SHOW_PROGRESS:
            print(f"contract release command {index}/{len(commands)}", file=sys.stderr, flush=True)
        run_contract_command(command, timeout_seconds=release_command_timeout(command))
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


def require_smoke_commands_pass() -> None:
    commands = [
        [sys.executable, "scripts/quick_validate_skill.py", "."],
        [sys.executable, "scripts/dwm.py", "doctor", "--json"],
        [sys.executable, "scripts/check_whitespace.py", "."],
        [sys.executable, "scripts/check_release_text.py", "."],
    ]
    for command in commands:
        run_contract_command(command, timeout_seconds=release_command_timeout(command))


def require_changed_surface_commands_pass() -> None:
    commands = [
        [sys.executable, "scripts/dwm_readme_graph_visibility.py", "--self-test"],
        [sys.executable, "scripts/dwm_readme_graph_visibility.py", "--manifest", "fixtures/v79/manifest.json", "--out", "out/readme-graph-visibility/v79-final"],
        [sys.executable, "scripts/dwm_readme_graph_visibility.py", "audit", "--readme", "README.md", "--timing", "out/graph-timing/v78-canonical/graph-timing.json", "--out", "out/readme-graph-visibility/v79-canonical"],
        [sys.executable, "scripts/dwm_continuation_boundary.py", "--self-test"],
        [sys.executable, "scripts/dwm_continuation_boundary.py", "--manifest", "fixtures/v80/manifest.json", "--out", "out/continuation-boundaries/v80-final"],
        [sys.executable, "scripts/dwm_continuation_boundary.py", "assess", "--preflight", "out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json", "--timing", "out/graph-timing/v78-canonical/graph-timing.json", "--visibility", "out/readme-graph-visibility/v79-canonical/readme-graph-visibility.json", "--out", "out/continuation-boundaries/v80-canonical"],
        [sys.executable, "scripts/dwm_multi_slice_batch.py", "--self-test"],
        [sys.executable, "scripts/dwm_multi_slice_batch.py", "--manifest", "fixtures/v81/manifest.json", "--out", "out/multi-slice-batches/v81-final"],
        [sys.executable, "scripts/dwm_multi_slice_batch.py", "plan", "--boundary", "out/continuation-boundaries/v80-canonical/continuation-boundary.json", "--out", "out/multi-slice-batches/v81-canonical"],
        [sys.executable, "scripts/dwm_execution_receipt_schema.py", "--self-test"],
        [sys.executable, "scripts/dwm_execution_receipt_schema.py", "--manifest", "fixtures/v82/manifest.json", "--out", "out/execution-receipt-schemas/v82-final"],
        [sys.executable, "scripts/dwm_execution_receipt_schema.py", "preflight", "--batch", "out/multi-slice-batches/v81-canonical/multi-slice-batch.json", "--out", "out/execution-receipt-schemas/v82-canonical"],
        [sys.executable, "scripts/dwm_runner_receipt_dry_run.py", "--self-test"],
        [sys.executable, "scripts/dwm_runner_receipt_dry_run.py", "--manifest", "fixtures/v83/manifest.json", "--out", "out/runner-receipt-dry-runs/v83-final"],
        [sys.executable, "scripts/dwm_runner_receipt_dry_run.py", "dry-run", "--schema", "out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json", "--batch", "out/multi-slice-batches/v81-canonical/multi-slice-batch.json", "--out", "out/runner-receipt-dry-runs/v83-canonical"],
        [sys.executable, "scripts/dwm_installed_surface_audit.py", "--self-test"],
        [sys.executable, "scripts/dwm_installed_surface_audit.py", "--manifest", "fixtures/v84/manifest.json", "--out", "out/installed-surface-audits/v84-final"],
        [sys.executable, "scripts/dwm_installed_surface_audit.py", "audit", "--active-skill", "SKILL.md", "--out", "out/installed-surface-audits/v84-canonical"],
        [sys.executable, "scripts/dwm_brand_boundary_audit.py", "--self-test"],
        [sys.executable, "scripts/dwm_brand_boundary_audit.py", "--manifest", "fixtures/v87/manifest.json", "--out", "out/brand-boundary-audits/v87-final"],
        [sys.executable, "scripts/dwm_brand_boundary_audit.py", "audit", "--out", "out/brand-boundary-audits/v87-canonical"],
        [sys.executable, "scripts/dwm_roadmap_reconciliation.py", "--self-test"],
        [sys.executable, "scripts/dwm_roadmap_reconciliation.py", "--manifest", "fixtures/v88/manifest.json", "--out", "out/roadmap-reconciliations/v88-final"],
        [sys.executable, "scripts/dwm_roadmap_reconciliation.py", "audit", "--out", "out/roadmap-reconciliations/v88-canonical"],
        [sys.executable, "scripts/dwm_command_safety.py", "--self-test"],
        [sys.executable, "scripts/dwm_command_safety.py", "--manifest", "fixtures/v89/manifest.json", "--out", "out/command-safety/v89-final"],
        [sys.executable, "scripts/dwm_workflow_activation.py", "--self-test"],
        [sys.executable, "scripts/dwm_workflow_activation.py", "--manifest", "fixtures/v90/manifest.json", "--out", "out/workflow-activations/v90-final"],
        [
            sys.executable,
            "scripts/dwm_workflow_activation.py",
            "activate",
            "--audit",
            "out/installed-surface-audits/v84-canonical/installed-surface-audit.json",
            "--receipt",
            "out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json",
            "--status",
            "out/v9/v32-semantic-dogfood/status.json",
            "--brand-audit",
            "out/brand-boundary-audits/v87-canonical/brand-boundary-audit.json",
            "--roadmap-reconciliation",
            "out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json",
            "--command-safety",
            "out/command-safety/v89-final/summary.json",
            "--out",
            "out/workflow-activations/v90-canonical",
        ],
        [sys.executable, "scripts/dwm_evidence_oracle.py", "--self-test"],
        [sys.executable, "scripts/dwm_evidence_oracle.py", "--manifest", "fixtures/v92/manifest.json", "--out", "out/evidence-oracles/v92-final"],
        [sys.executable, "scripts/dwm_evidence_oracle.py", "verify", "--claims", "fixtures/v92/canonical-claims.json", "--out", "out/evidence-oracles/v92-canonical"],
        [sys.executable, "scripts/dwm_workflow_narrative.py", "--self-test"],
        [sys.executable, "scripts/dwm_workflow_narrative.py", "--manifest", "fixtures/v93/manifest.json", "--out", "out/workflow-narratives/v93-final"],
        [
            sys.executable,
            "scripts/dwm_workflow_narrative.py",
            "render",
            "--roadmap",
            "out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json",
            "--command-safety",
            "out/command-safety/v89-final/summary.json",
            "--activation",
            "out/workflow-activations/v90-canonical/workflow-activation.json",
            "--oracle",
            "out/evidence-oracles/v92-canonical/evidence-oracle.json",
            "--out",
            "out/workflow-narratives/v93-canonical",
        ],
        [sys.executable, "scripts/dwm_control_deck_score.py", "--self-test"],
        [sys.executable, "scripts/dwm_control_deck_score.py", "--manifest", "fixtures/v94/manifest.json", "--out", "out/control-deck-scores/v94-final"],
        [
            sys.executable,
            "scripts/dwm_control_deck_score.py",
            "score",
            "--narrative",
            "out/workflow-narratives/v93-canonical/workflow-narrative.json",
            "--roadmap",
            "out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json",
            "--command-safety",
            "out/command-safety/v89-final/summary.json",
            "--activation",
            "out/workflow-activations/v90-canonical/workflow-activation.json",
            "--oracle",
            "out/evidence-oracles/v92-canonical/evidence-oracle.json",
            "--out",
            "out/control-deck-scores/v94-canonical",
        ],
        [sys.executable, "scripts/dwm_control_deck_score_history.py", "--self-test"],
        [sys.executable, "scripts/dwm_control_deck_score_history.py", "--manifest", "fixtures/v95/manifest.json", "--out", "out/control-deck-score-history/v95-final"],
        [
            sys.executable,
            "scripts/dwm_control_deck_score_history.py",
            "build",
            "--score",
            "out/control-deck-scores/v94-canonical",
            "--out",
            "out/control-deck-score-history/v95-canonical",
        ],
        [sys.executable, "scripts/dwm_metric_ladder.py", "--self-test"],
        [sys.executable, "scripts/dwm_metric_ladder.py", "--manifest", "fixtures/v96/manifest.json", "--out", "out/metric-ladders/v96-final"],
        [
            sys.executable,
            "scripts/dwm_metric_ladder.py",
            "assess",
            "--history",
            "out/control-deck-score-history/v95-canonical/control-deck-score-history.json",
            "--graph-timing",
            "out/graph-timing/v78-canonical/graph-timing.json",
            "--out",
            "out/metric-ladders/v96-canonical",
        ],
        [sys.executable, "scripts/dwm_benchmark_readiness.py", "--self-test"],
        [sys.executable, "scripts/dwm_benchmark_readiness.py", "--manifest", "fixtures/v97/manifest.json", "--out", "out/benchmark-readiness/v97-final"],
        [
            sys.executable,
            "scripts/dwm_benchmark_readiness.py",
            "assess",
            "--ladder",
            "out/metric-ladders/v96-canonical/metric-ladder.json",
            "--out",
            "out/benchmark-readiness/v97-canonical",
        ],
        [sys.executable, "scripts/dwm_wave_operator.py", "--self-test"],
        [sys.executable, "scripts/dwm_wave_operator.py", "--manifest", "fixtures/v98/manifest.json", "--out", "out/wave-operators/v98-final"],
        [
            sys.executable,
            "scripts/dwm_wave_operator.py",
            "select",
            "--readiness",
            "out/benchmark-readiness/v97-canonical/benchmark-readiness.json",
            "--activation",
            "out/workflow-activations/v90-canonical/workflow-activation.json",
            "--out",
            "out/wave-operators/v98-canonical",
        ],
        [sys.executable, "scripts/dwm_wave_receipt.py", "--self-test"],
        [sys.executable, "scripts/dwm_wave_receipt.py", "--manifest", "fixtures/v99/manifest.json", "--out", "out/wave-receipts/v99-final"],
        [
            sys.executable,
            "scripts/dwm_wave_receipt.py",
            "record",
            "--wave",
            "out/wave-operators/v98-canonical/wave-operator.json",
            "--acquisition",
            "out/dogfood-acquisitions/v61-final/summary.json",
            "--out",
            "out/wave-receipts/v99-canonical",
        ],
        [sys.executable, "scripts/dwm_promotion_evidence.py", "--self-test"],
        [sys.executable, "scripts/dwm_promotion_evidence.py", "--manifest", "fixtures/v100/manifest.json", "--out", "out/promotion-evidence/v100-final"],
        [
            sys.executable,
            "scripts/dwm_promotion_evidence.py",
            "record",
            "--receipt",
            "out/wave-receipts/v99-canonical/wave-receipt.json",
            "--readiness",
            "out/benchmark-readiness/v97-canonical/benchmark-readiness.json",
            "--out",
            "out/promotion-evidence/v100-canonical",
        ],
        [sys.executable, "scripts/dwm_promotion_route.py", "--self-test"],
        [sys.executable, "scripts/dwm_promotion_route.py", "--manifest", "fixtures/v101/manifest.json", "--out", "out/promotion-routes/v101-final"],
        [
            sys.executable,
            "scripts/dwm_promotion_route.py",
            "route",
            "--evidence",
            "out/promotion-evidence/v100-canonical/promotion-evidence.json",
            "--out",
            "out/promotion-routes/v101-canonical",
        ],
        [sys.executable, "scripts/dwm_live_proof.py", "--self-test"],
        [sys.executable, "scripts/dwm_live_proof.py", "--manifest", "fixtures/v102/manifest.json", "--out", "out/v102/final"],
        [sys.executable, "scripts/dwm_live_proof.py", "--manifest", "fixtures/v103/manifest.json", "--out", "out/v103/final"],
        [sys.executable, "scripts/v105_verify_wedge.py", "--self-test"],
        [sys.executable, "scripts/v106_multi_wave.py", "--self-test"],
        [sys.executable, "scripts/dwm.py", "doctor", "--json"],
        [sys.executable, "scripts/check_release_text.py", "."],
    ]
    for command in commands:
        run_contract_command(command, timeout_seconds=release_command_timeout(command))


def contract_steps_for_tier(tier: str) -> list[tuple[str, object, int]]:
    if tier == "smoke":
        return [
            ("fixture smoke", require_fixture_smoke, DEFAULT_STEP_TIMEOUT_SECONDS),
            ("smoke command tier", require_smoke_commands_pass, 300),
        ]
    if tier == "changed":
        return [
            ("fixture smoke", require_fixture_smoke, DEFAULT_STEP_TIMEOUT_SECONDS),
            ("changed-surface command tier", require_changed_surface_commands_pass, 600),
        ]
    if tier != "full":
        raise SystemExit(f"unknown contract tier: {tier}")
    return [
        ("fixture smoke", require_fixture_smoke, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("release command corpus", require_release_commands_pass, 1800),
        ("v0.5 decision summary consistency", require_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v1 decision summary consistency", require_v1_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v2 decision summary consistency", require_v2_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v2.5 decision summary consistency", require_v25_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v3 decision summary consistency", require_v3_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v7.5 decision summary consistency", require_v75_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v8 decision summary consistency", require_v8_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v9 decision summary consistency", require_v9_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v10 decision summary consistency", require_v10_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v11 decision summary consistency", require_v11_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v13 decision summary consistency", require_v13_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v14 decision summary consistency", require_v14_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v15 decision summary consistency", require_v15_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v16 decision summary consistency", require_v16_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v17 decision summary consistency", require_v17_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v18 decision summary consistency", require_v18_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v19 decision summary consistency", require_v19_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v20 decision summary consistency", require_v20_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v20.5 decision summary consistency", require_v205_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v20.6 decision summary consistency", require_v206_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v22 decision summary consistency", require_v22_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v23 decision summary consistency", require_v23_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v24 decision summary consistency", require_v24_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v25 task decision summary consistency", require_v25_tasks_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v26 attempts decision summary consistency", require_v26_attempts_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v27 smoke decision summary consistency", require_v27_smoke_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v28 live plan decision summary consistency", require_v28_live_plan_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v29 runner preflight decision summary consistency", require_v29_runner_preflight_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v30 receipt decision summary consistency", require_v30_receipt_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v31 receipt judge decision summary consistency", require_v31_receipt_judge_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v32 live score decision summary consistency", require_v32_live_score_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v33 live score aggregate decision summary consistency", require_v33_live_score_aggregate_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v34 live score review decision summary consistency", require_v34_live_score_review_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v35 live report decision summary consistency", require_v35_live_report_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
        ("v36 readme graph decision summary consistency", require_v36_readme_graph_decision_summary_consistency, DEFAULT_STEP_TIMEOUT_SECONDS),
    ]


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
    if release_command_timeout([sys.executable, "scripts/dwm_release.py", "--self-test"]) != LONG_COMMAND_TIMEOUT_SECONDS:
        raise SystemExit("self-test failed: long release command timeout not selected")
    if release_command_timeout([sys.executable, "scripts/dwm_demo.py", "--self-test"]) != LONG_COMMAND_TIMEOUT_SECONDS:
        raise SystemExit("self-test failed: demo release command timeout not selected")
    if release_command_timeout([sys.executable, "scripts/dwm.py", "--self-test"]) != DEFAULT_COMMAND_TIMEOUT_SECONDS:
        raise SystemExit("self-test failed: default release command timeout not selected")
    if [label for label, _callback, _timeout in contract_steps_for_tier("smoke")] != ["fixture smoke", "smoke command tier"]:
        raise SystemExit("self-test failed: smoke tier steps changed")
    if [label for label, _callback, _timeout in contract_steps_for_tier("changed")] != ["fixture smoke", "changed-surface command tier"]:
        raise SystemExit("self-test failed: changed tier steps changed")
    if "release command corpus" not in [label for label, _callback, _timeout in contract_steps_for_tier("full")]:
        raise SystemExit("self-test failed: full tier does not include release command corpus")
    try:
        run_contract_command([sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=1)
    except SystemExit as exc:
        if "release command timed out after 1s" not in str(exc):
            raise
    else:
        raise SystemExit("self-test failed: timed-out contract command passed")

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

    v22_summary = {
        "suite_id": "v22-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v22_decision = (
        "Decision: keep\n"
        "python scripts/dwm_roles.py --manifest fixtures/v22/manifest.json --out out/roles/v22-final\n"
        "- `suite_id`: `v22-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted registry covers planner, explorer, worker, reviewer, verifier, and operator.\n"
        "This decision does not claim role execution.\n"
    )
    require_v22_decision_summary_text(v22_summary, good_v22_decision)
    try:
        require_v22_decision_summary_text(v22_summary, good_v22_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V22 decision summary passed")

    v23_summary = {
        "suite_id": "v23-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v23_decision = (
        "Decision: keep\n"
        "python scripts/dwm_benchmark.py --manifest fixtures/v23/manifest.json --out out/benchmarks/v23-final\n"
        "- `suite_id`: `v23-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted corpus covers failing-test-fix, small-refactor, auth-permission-audit, ui-render-regression, docs-code-consistency, and multi-file-migration.\n"
        "This decision does not claim live harness execution.\n"
    )
    require_v23_decision_summary_text(v23_summary, good_v23_decision)
    try:
        require_v23_decision_summary_text(v23_summary, good_v23_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V23 decision summary passed")

    v24_summary = {
        "suite_id": "v24-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 1,
        "decision": "keep",
    }
    good_v24_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_benchmark.py --manifest fixtures/v24/manifest.json --out out/benchmarks-live/v24-final\n"
        "- `suite_id`: `v24-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 1\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers fixture-control, adapter-availability, ERR_LIVE_BENCHMARK_CORPUS_MISSING, ERR_LIVE_BENCHMARK_UNSAFE_MODE, ERR_LIVE_BENCHMARK_STALE_SCORE, and ERR_LIVE_BENCHMARK_ADAPTER_UNAVAILABLE.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v24_decision_summary_text(v24_summary, good_v24_decision)
    try:
        require_v24_decision_summary_text(v24_summary, good_v24_decision.replace("`skipped`: 1", "`skipped`: 0", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V24 decision summary passed")

    v25_summary = {
        "suite_id": "v25-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v25_decision = (
        "Decision: keep\n"
        "python scripts/dwm_benchmark_tasks.py --manifest fixtures/v25/manifest.json --out out/benchmark-tasks/v25-final\n"
        "- `suite_id`: `v25-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers materialize-suite, verify-initial, ERR_BENCHMARK_TASKS_CORPUS_MISMATCH, ERR_BENCHMARK_TASKS_UNSAFE_PATH, and ERR_BENCHMARK_TASKS_STALE_TEMPLATE.\n"
        "This decision does not claim task solving.\n"
    )
    require_v25_tasks_decision_summary_text(v25_summary, good_v25_decision)
    try:
        require_v25_tasks_decision_summary_text(v25_summary, good_v25_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V25 decision summary passed")

    v26_summary = {
        "suite_id": "v26-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v26_decision = (
        "Decision: keep\n"
        "python scripts/dwm_benchmark_attempts.py --manifest fixtures/v26/manifest.json --out out/benchmark-attempts/v26-final\n"
        "- `suite_id`: `v26-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers scripted-fixture, attempt.json, changes.json, verification.json, ERR_BENCHMARK_ATTEMPTS_MISSING_TASKS, ERR_BENCHMARK_ATTEMPTS_STALE_PLAN, and ERR_BENCHMARK_ATTEMPTS_UNSAFE_PATH.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v26_attempts_decision_summary_text(v26_summary, good_v26_decision)
    try:
        require_v26_attempts_decision_summary_text(v26_summary, good_v26_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V26 decision summary passed")

    v27_summary = {
        "suite_id": "v27-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 1,
        "decision": "keep",
    }
    good_v27_decision = (
        "Decision: keep\n"
        "python scripts/dwm_adapter_smoke.py --manifest fixtures/v27/manifest.json --out out/adapter-smoke/v27-final\n"
        "- `suite_id`: `v27-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 1\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers adapter-smoke.json, ERR_ADAPTER_SMOKE_UNAVAILABLE, ERR_ADAPTER_SMOKE_UNSAFE_COMMAND, ERR_ADAPTER_SMOKE_UNKNOWN_TASK, and ERR_ADAPTER_SMOKE_STALE_TEMPLATE.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v27_smoke_decision_summary_text(v27_summary, good_v27_decision)
    try:
        require_v27_smoke_decision_summary_text(v27_summary, good_v27_decision.replace("`skipped`: 1", "`skipped`: 0", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V27 decision summary passed")

    v28_summary = {
        "suite_id": "v28-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 1,
        "decision": "keep",
    }
    good_v28_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_attempt_plan.py --manifest fixtures/v28/manifest.json --out out/live-attempt-plans/v28-final\n"
        "- `suite_id`: `v28-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 1\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers command-plan.json, prompt.md, ERR_LIVE_ATTEMPT_ADAPTER_UNAVAILABLE, ERR_LIVE_ATTEMPT_STALE_SMOKE, ERR_LIVE_ATTEMPT_UNKNOWN_TASK, and ERR_LIVE_ATTEMPT_UNSAFE_COMMAND.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v28_live_plan_decision_summary_text(v28_summary, good_v28_decision)
    try:
        require_v28_live_plan_decision_summary_text(v28_summary, good_v28_decision.replace("`skipped`: 1", "`skipped`: 0", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V28 decision summary passed")

    v29_summary = {
        "suite_id": "v29-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 1,
        "decision": "keep",
    }
    good_v29_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_runner_preflight.py --manifest fixtures/v29/manifest.json --out out/live-runner-preflight/v29-final\n"
        "- `suite_id`: `v29-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 1\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers preflight.json, ready-for-human-run, ERR_LIVE_RUNNER_PLAN_SKIPPED, ERR_LIVE_RUNNER_STALE_PLAN, ERR_LIVE_RUNNER_POLICY_BLOCKED, and ERR_LIVE_RUNNER_ARTIFACT_MISSING.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v29_runner_preflight_decision_summary_text(v29_summary, good_v29_decision)
    try:
        require_v29_runner_preflight_decision_summary_text(v29_summary, good_v29_decision.replace("`skipped`: 1", "`skipped`: 0", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V29 decision summary passed")

    v30_summary = {
        "suite_id": "v30-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v30_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_receipt.py --manifest fixtures/v30/manifest.json --out out/live-receipts/v30-final\n"
        "- `suite_id`: `v30-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers receipt.json, receipt-ledger.json, ERR_LIVE_RECEIPT_PREFLIGHT_NOT_READY, ERR_LIVE_RECEIPT_STALE_PREFLIGHT, ERR_LIVE_RECEIPT_COMMAND_MISMATCH, and ERR_LIVE_RECEIPT_ARTIFACT_MISSING.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v30_receipt_decision_summary_text(v30_summary, good_v30_decision)
    try:
        require_v30_receipt_decision_summary_text(v30_summary, good_v30_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V30 decision summary passed")

    v31_summary = {
        "suite_id": "v31-final",
        "fixture_count": 6,
        "required_fixture_count": 6,
        "required_passed": 6,
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v31_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_receipt_judge.py --manifest fixtures/v31/manifest.json --out out/live-receipt-judgments/v31-final\n"
        "- `suite_id`: `v31-final`\n"
        "- `fixture_count`: 6\n"
        "- `required_fixture_count`: 6\n"
        "- `required_passed`: 6\n"
        "- `passed`: 6\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers judgment.json, ERR_LIVE_RECEIPT_JUDGE_ARTIFACT_MISSING, ERR_LIVE_RECEIPT_JUDGE_STALE_RECEIPT, ERR_LIVE_RECEIPT_JUDGE_RECEIPT_NOT_ACCEPTED, and ERR_LIVE_RECEIPT_JUDGE_HASH_MISMATCH.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v31_receipt_judge_decision_summary_text(v31_summary, good_v31_decision)
    try:
        require_v31_receipt_judge_decision_summary_text(v31_summary, good_v31_decision.replace("`passed`: 6", "`passed`: 5", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V31 decision summary passed")

    v32_summary = {
        "suite_id": "v32-final",
        "fixture_count": 7,
        "required_fixture_count": 7,
        "required_passed": 7,
        "passed": 7,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v32_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_score.py --manifest fixtures/v32/manifest.json --out out/live-scores/v32-final\n"
        "- `suite_id`: `v32-final`\n"
        "- `fixture_count`: 7\n"
        "- `required_fixture_count`: 7\n"
        "- `required_passed`: 7\n"
        "- `passed`: 7\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers score.json, ERR_LIVE_SCORE_ARTIFACT_MISSING, ERR_LIVE_SCORE_STALE_JUDGMENT, ERR_LIVE_SCORE_TASK_MISMATCH, ERR_LIVE_SCORE_HASH_MISMATCH, and ERR_LIVE_SCORE_VERIFICATION_INVALID.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v32_live_score_decision_summary_text(v32_summary, good_v32_decision)
    try:
        require_v32_live_score_decision_summary_text(v32_summary, good_v32_decision.replace("`passed`: 7", "`passed`: 6", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V32 decision summary passed")

    v33_summary = {
        "suite_id": "v33-final",
        "fixture_count": 7,
        "required_fixture_count": 7,
        "required_passed": 7,
        "passed": 7,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v33_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_score_aggregate.py --manifest fixtures/v33/manifest.json --out out/live-score-aggregates/v33-final\n"
        "- `suite_id`: `v33-final`\n"
        "- `fixture_count`: 7\n"
        "- `required_fixture_count`: 7\n"
        "- `required_passed`: 7\n"
        "- `passed`: 7\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers aggregate-score.json, ERR_LIVE_SCORE_AGGREGATE_ARTIFACT_MISSING, ERR_LIVE_SCORE_AGGREGATE_STALE_SCORE, ERR_LIVE_SCORE_AGGREGATE_TASK_MISSING, ERR_LIVE_SCORE_AGGREGATE_TASK_DUPLICATE, and ERR_LIVE_SCORE_AGGREGATE_UNSUPPORTED_CLAIM.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v33_live_score_aggregate_decision_summary_text(v33_summary, good_v33_decision)
    try:
        require_v33_live_score_aggregate_decision_summary_text(v33_summary, good_v33_decision.replace("`passed`: 7", "`passed`: 6", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V33 decision summary passed")

    v34_summary = {
        "suite_id": "v34-final",
        "fixture_count": 7,
        "required_fixture_count": 7,
        "required_passed": 7,
        "passed": 7,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v34_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_score_review.py --manifest fixtures/v34/manifest.json --out out/live-score-reviews/v34-final\n"
        "- `suite_id`: `v34-final`\n"
        "- `fixture_count`: 7\n"
        "- `required_fixture_count`: 7\n"
        "- `required_passed`: 7\n"
        "- `passed`: 7\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers reviewed-score.json, ERR_LIVE_SCORE_REVIEW_ARTIFACT_MISSING, ERR_LIVE_SCORE_REVIEW_STALE_AGGREGATE, ERR_LIVE_SCORE_REVIEW_TASK_MISMATCH, and ERR_LIVE_SCORE_REVIEW_HASH_MISMATCH.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v34_live_score_review_decision_summary_text(v34_summary, good_v34_decision)
    try:
        require_v34_live_score_review_decision_summary_text(v34_summary, good_v34_decision.replace("`passed`: 7", "`passed`: 6", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V34 decision summary passed")

    v35_summary = {
        "suite_id": "v35-final",
        "fixture_count": 7,
        "required_fixture_count": 7,
        "required_passed": 7,
        "passed": 7,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v35_decision = (
        "Decision: keep\n"
        "python scripts/dwm_live_report.py --manifest fixtures/v35/manifest.json --out out/live-reports/v35-final\n"
        "- `suite_id`: `v35-final`\n"
        "- `fixture_count`: 7\n"
        "- `required_fixture_count`: 7\n"
        "- `required_passed`: 7\n"
        "- `passed`: 7\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers report.json, report.md, ERR_LIVE_REPORT_ARTIFACT_MISSING, ERR_LIVE_REPORT_STALE_REVIEW, ERR_LIVE_REPORT_HASH_MISMATCH, and ERR_LIVE_REPORT_UNSUPPORTED_CLAIM.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v35_live_report_decision_summary_text(v35_summary, good_v35_decision)
    try:
        require_v35_live_report_decision_summary_text(v35_summary, good_v35_decision.replace("`passed`: 7", "`passed`: 6", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V35 decision summary passed")

    v36_summary = {
        "suite_id": "v36-final",
        "fixture_count": 5,
        "required_fixture_count": 5,
        "required_passed": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
        "decision": "keep",
    }
    good_v36_decision = (
        "Decision: keep\n"
        "python scripts/dwm_readme_benchmark_graph.py --manifest fixtures/v36/manifest.json --out out/readme-benchmark-graphs/v36-final\n"
        "- `suite_id`: `v36-final`\n"
        "- `fixture_count`: 5\n"
        "- `required_fixture_count`: 5\n"
        "- `required_passed`: 5\n"
        "- `passed`: 5\n"
        "- `failed`: 0\n"
        "- `skipped`: 0\n"
        "- `decision`: `keep`\n"
        "The accepted suite covers benchmark-graph.json, benchmark-graph.svg, README-snippet.md, ERR_README_GRAPH_ARTIFACT_MISSING, ERR_README_GRAPH_STALE_REPORT, and ERR_README_GRAPH_METRICS_INVALID.\n"
        "This decision does not claim live model execution.\n"
    )
    require_v36_readme_graph_decision_summary_text(v36_summary, good_v36_decision)
    try:
        require_v36_readme_graph_decision_summary_text(v36_summary, good_v36_decision.replace("`passed`: 5", "`passed`: 4", 1))
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: stale V36 decision summary passed")

    print("contract self-test: pass")


def main() -> None:
    global SHOW_PROGRESS
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--tier", choices=["smoke", "changed", "full"], default="full", help="verification depth; default preserves the full release contract")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    SHOW_PROGRESS = True

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
            "# depone",
            "dwm core",
            "depone",
            "python scripts/dwm_demo.py run --out out/demo/quickstart",
            "python scripts/dwm_demo.py inspect --demo out/demo/quickstart",
            "python scripts/dwm.py status --run out/v9/v32-semantic-dogfood",
            "python scripts/dwm.py next --run out/v9/v32-semantic-dogfood",
            "python scripts/dwm.py commands --kind product",
            "python scripts/check_contract.py",
            "python scripts/check_readme_quality.py readme.md",
            "python scripts/dwm.py commands --kind release",
            "assets/dwm-dogfood-progress.svg",
            "assets/dwm-live-benchmark.svg",
            "docs/command-reference.md",
            "docs/release-history.md",
            "generated `out/` directories are verification evidence, not source of truth",
            "direct-agent superiority",
            "public trend promotion requires real release history",
            "not a public benchmark graph",
        ],
    )
    require_terms(
        "docs/command-reference.md",
        [
            'python scripts/dwm.py plan "<objective>" --out out/v21/<run_id>',
            'python scripts/dwm.py run "<objective>" --out out/v21/<run_id>',
            "python scripts/dwm.py resume --run out/v21/<run_id>",
            "python scripts/check_readme_quality.py readme.md",
            "python scripts/dwm_roles.py registry",
            "python scripts/dwm_benchmark.py corpus",
            "python scripts/dwm_benchmark.py claim --min-margin 8",
            "python scripts/dwm_live_benchmark.py capture --out out/benchmarks-live/<capture_id>",
            "python scripts/dwm_live_attempt_plan.py plan --adapter-command codex --task-id failing-test-fix --out out/live-attempt-plans/<plan_id>",
            "python scripts/dwm_live_runner_preflight.py preflight --plan out/live-attempt-plans/<plan_id> --out out/live-runner-preflight/<preflight_id>",
            "python scripts/dwm_live_receipt.py ingest --preflight out/live-runner-preflight/<preflight_id> --receipt receipt.json --out out/live-receipts/<receipt_id>",
            "python scripts/dwm_live_report.py publish --review out/live-score-reviews/<review_id> --out out/live-reports/<report_id>",
            "python scripts/dwm_benchmark_snapshot.py record --report out/live-reports/<report_id> --release-id <release_id> --out out/benchmark-snapshots/<snapshot_id>",
            "python scripts/dwm_benchmark_series.py build --snapshot-root out/benchmark-snapshots --out out/benchmark-series/<series_id>",
            "python scripts/dwm_benchmark_candidate.py make --series out/benchmark-series/<series_id> --out out/benchmark-candidates/<candidate_id>",
            "python scripts/dwm_benchmark_candidate_review.py review --candidate out/benchmark-candidates/<candidate_id> --out out/benchmark-candidate-reviews/<review_id>",
            "python scripts/dwm_readme_asset_promotion.py promote --review out/benchmark-candidate-reviews/<review_id> --out out/readme-asset-promotions/<promotion_id>",
            "python scripts/dwm_workflow_queue.py create --packets packets.json --out out/workflow-queues/<queue_id>",
            "python scripts/dwm_workflow_queue.py resume --queue out/workflow-queues/<queue_id>",
            "python scripts/dwm_dogfood_corpus.py record --out out/dogfood-corpus/<corpus_id>",
            "python scripts/dwm_dogfood_attempts.py record --corpus out/dogfood-corpus/<corpus_id> --attempts attempts.json --out out/dogfood-attempts/<attempt_id>",
            "python scripts/dwm_dogfood_measure.py sample --out out/dogfood-measurements/<measurement_id>",
            "python scripts/dwm_dogfood_pair.py pair --dwm-measure out/dogfood-measurements/<measurement_id> --direct-receipt direct-receipt.json --out out/dogfood-pairs/<pair_id>",
            "python scripts/dwm_dogfood_pair_series.py build --pair-root out/dogfood-pairs --out out/dogfood-pair-series/<series_id>",
            "python scripts/dwm_dogfood_chart_candidate.py candidate --series out/dogfood-pair-series/<series_id> --out out/dogfood-chart-candidates/<chart_id>",
            "python scripts/dwm_dogfood_chart_review.py review --candidate out/dogfood-chart-candidates/<chart_id> --receipt review-receipt.json --out out/dogfood-chart-reviews/<review_id>",
            "python scripts/dwm_dogfood_acquire.py acquire --task-id <task_id> --out out/dogfood-acquisitions/<acquisition_id>",
            "python scripts/dwm_dogfood_operator.py recommend --out out/dogfood-operator/<operator_id>",
            "python scripts/dwm_dogfood_pair_select.py select --pair-root out/dogfood-pairs --out out/dogfood-pair-selections/<selection_id>",
            "python scripts/dwm_dogfood_chart_render.py render --review out/dogfood-chart-reviews/<review_id> --out out/dogfood-chart-renders/<render_id>",
            "python scripts/dwm_dogfood_progress.py build --out out/dogfood-progress/<progress_id>",
            "python scripts/dwm_dogfood_progress_asset_promotion.py promote --progress out/dogfood-progress/<progress_id> --out out/dogfood-progress-asset-promotions/<promotion_id>",
            "python scripts/dwm_daily_operator.py today --corpus out/dogfood-corpus/<corpus_id> --out out/daily-operator/<operator_id>",
            "python scripts/dwm_benchmark_history.py build --report out/live-reports/<report_id> --out out/benchmark-history/<history_id>",
            "python scripts/dwm_benchmark_promotion.py promote --history out/benchmark-history/<history_id> --out out/benchmark-promotions/<promotion_id>",
            "python scripts/dwm_readme_benchmark_graph.py generate --report out/live-reports/<report_id> --out out/readme-benchmark-graphs/<graph_id>",
            "python scripts/dwm_hud.py approve --hud out/hud/<hud_id> --out out/hud/<approval_id> --approver <name>",
            "python scripts/dwm_install.py validate",
            "python scripts/dwm_adapters.py registry",
            "python scripts/dwm_adapters.py parity --out out/adapters/<parity_id>",
            "python scripts/dwm_adapter_live_matrix.py matrix --out out/adapter-live-matrix/<matrix_id>",
            "python scripts/dwm_release_candidate.py cut --parity out/adapters/<parity_id> --operator out/daily-operator/<operator_id> --out out/release-candidates/<candidate_id>",
            "python scripts/dwm_release.py status --out out/release/<release_id>",
            "python scripts/dwm_release_timing.py plan --out out/release-timing/<timing_id>",
            "python scripts/dwm_release_timing.py measure --limit 3 --out out/release-timing/<timing_id>",
            "python scripts/dwm_release_timing_history.py build --timing-root out/release-timing --out out/release-timing-history/<history_id>",
            "python scripts/dwm_large_workflow_control.py assess --workflow workflow.json --out out/large-workflow-control/<control_id>",
            "python scripts/dwm_large_workflow_dogfood.py record --run out/v9/v32-semantic-dogfood --out out/large-workflow-dogfood/<dogfood_id>",
            "python scripts/dwm_large_workflow_next.py select --control out/large-workflow-dogfood/v74-canonical/dogfood-control.json --out out/large-workflow-next/<next_id>",
            "python scripts/dwm_large_workflow_queue_bridge.py bridge --selection out/large-workflow-next/v75-canonical/large-workflow-next.json --out out/large-workflow-queue-bridge/<bridge_id> --queue-out out/workflow-queues/<queue_id>",
            "python scripts/dwm_large_workflow_queue_preflight.py preflight --queue out/workflow-queues/v76-canonical/queue.json --out out/large-workflow-queue-preflight/<preflight_id>",
            "python scripts/dwm_graph_timing_gate.py check --progress out/dogfood-progress/local-v66-current/dogfood-progress.json --readiness out/dogfood-pair-series/local-v64-selected-series/graph-readiness.json --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --out out/graph-timing/<timing_id>",
            "python scripts/dwm_readme_graph_visibility.py audit --readme readme.md --timing out/graph-timing/v78-canonical/graph-timing.json --out out/readme-graph-visibility/<visibility_id>",
            "python scripts/dwm_continuation_boundary.py assess --preflight out/large-workflow-queue-preflight/v77-canonical/queue-preflight.json --timing out/graph-timing/v78-canonical/graph-timing.json --visibility out/readme-graph-visibility/v79-canonical/readme-graph-visibility.json --out out/continuation-boundaries/<boundary_id>",
            "python scripts/dwm_multi_slice_batch.py plan --boundary out/continuation-boundaries/v80-canonical/continuation-boundary.json --out out/multi-slice-batches/<batch_id>",
            "python scripts/dwm_execution_receipt_schema.py preflight --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/execution-receipt-schemas/<schema_id>",
            "python scripts/dwm_runner_receipt_dry_run.py dry-run --schema out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/runner-receipt-dry-runs/<dry_run_id>",
            "python scripts/dwm_installed_surface_audit.py audit --active-skill skill.md --out out/installed-surface-audits/<audit_id>",
            "python scripts/dwm_workflow_activation.py activate --audit out/installed-surface-audits/v84-canonical/installed-surface-audit.json --receipt out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json --status out/v9/v32-semantic-dogfood/status.json --out out/workflow-activations/<activation_id>",
            "python scripts/dwm_brand_boundary_audit.py audit --out out/brand-boundary-audits/<audit_id>",
            "python scripts/dwm_roadmap_reconciliation.py audit --out out/roadmap-reconciliations/<audit_id>",
            "python scripts/dwm_command_safety.py --manifest fixtures/v89/manifest.json --out out/command-safety/<safety_id>",
            "python scripts/dwm_workflow_activation.py activate --audit out/installed-surface-audits/v84-canonical/installed-surface-audit.json --receipt out/runner-receipt-dry-runs/v83-canonical/runner-receipt.json --status out/v9/v32-semantic-dogfood/status.json --brand-audit out/brand-boundary-audits/v87-canonical/brand-boundary-audit.json --roadmap-reconciliation out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --out out/workflow-activations/<activation_id>",
            "python scripts/dwm_evidence_oracle.py verify --claims fixtures/v92/canonical-claims.json --out out/evidence-oracles/<oracle_id>",
            "python scripts/dwm_workflow_narrative.py render --roadmap out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --oracle out/evidence-oracles/v92-canonical/evidence-oracle.json --out out/workflow-narratives/<narrative_id>",
            "python scripts/dwm_control_deck_score.py score --narrative out/workflow-narratives/v93-canonical/workflow-narrative.json --roadmap out/roadmap-reconciliations/v88-canonical/roadmap-reconciliation.json --command-safety out/command-safety/v89-final/summary.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --oracle out/evidence-oracles/v92-canonical/evidence-oracle.json --out out/control-deck-scores/<score_id>",
            "python scripts/dwm_control_deck_score_history.py build --score out/control-deck-scores/<score_id> --out out/control-deck-score-history/<history_id>",
            "python scripts/dwm_metric_ladder.py assess --history out/control-deck-score-history/<history_id>/control-deck-score-history.json --graph-timing out/graph-timing/<timing_id>/graph-timing.json --out out/metric-ladders/<ladder_id>",
            "python scripts/dwm_benchmark_readiness.py assess --ladder out/metric-ladders/<ladder_id>/metric-ladder.json --out out/benchmark-readiness/<readiness_id>",
            "python scripts/dwm_wave_operator.py select --readiness out/benchmark-readiness/<readiness_id>/benchmark-readiness.json --activation out/workflow-activations/<activation_id>/workflow-activation.json --out out/wave-operators/<wave_id>",
            "python scripts/dwm_wave_receipt.py record --wave out/wave-operators/<wave_id>/wave-operator.json --acquisition out/dogfood-acquisitions/<acquisition_id>/summary.json --out out/wave-receipts/<receipt_id>",
            "python scripts/dwm_promotion_evidence.py record --receipt out/wave-receipts/<receipt_id>/wave-receipt.json --readiness out/benchmark-readiness/<readiness_id>/benchmark-readiness.json --out out/promotion-evidence/<evidence_id>",
            "python scripts/dwm_promotion_route.py route --evidence out/promotion-evidence/<evidence_id>/promotion-evidence.json --out out/promotion-routes/<route_id>",
            "report.json.graph_metrics",
            "benchmark-graph.json",
            "dogfood-progress.json",
            "large-workflow-next.json",
            "large-workflow-next.md",
            "queue-bridge.json",
            "queue-packets.json",
            "queue-bridge.md",
            "queue-preflight.json",
            "queue-preflight.md",
            "graph-timing.json",
            "graph-timing.md",
            "readme-graph-visibility.json",
            "readme-graph-visibility.md",
            "continuation-boundary.json",
            "continuation-boundary.md",
            "multi-slice-batch.json",
            "multi-slice-batch.md",
            "execution-receipt-schema.json",
            "execution-receipt-schema.md",
            "sample-receipt.json",
            "runner-receipt.json",
            "runner-receipt.md",
            "installed-surface-audit.json",
            "installed-surface-audit.md",
            "workflow-activation.json",
            "workflow-activation.md",
            "brand-boundary-audit.json",
            "brand-boundary-audit.md",
            "roadmap-reconciliation.json",
            "roadmap-reconciliation.md",
            "evidence-oracle.json",
            "evidence-oracle.md",
            "workflow-narrative.json",
            "workflow-narrative.md",
            "control-deck-score.json",
            "control-deck-score.md",
            "control-deck-score-history.json",
            "control-deck-score-history.md",
            "control-deck-score-history.svg",
            "metric-ladder.json",
            "metric-ladder.md",
            "benchmark-readiness.json",
            "benchmark-readiness.md",
            "wave-operator.json",
            "wave-operator.md",
            "wave-receipt.json",
            "wave-receipt.md",
            "promotion-evidence.json",
            "promotion-evidence.md",
            "promotion-route.json",
            "promotion-route.md",
            "command safety",
            "workflow narrative",
            "evidence oracle",
            "workflow activation v2",
            "dwm-dogfood-progress.svg",
            "assets/dwm-hero.svg",
            "assets/dwm-live-benchmark.svg",
            "assets/dwm-dogfood-progress.svg",
            "docs/spec.md",
            "docs/automation-roadmap.md",
            "docs/github-research.md",
            "docs/v12-to-v20-final-roadmap.md",
        ],
    )
    require_terms(
        "docs/release-history.md",
        [
            "v28 command plan",
            "v36 readme graph artifacts",
            "docs/v36-readme-benchmark-graph-spec.md",
            "docs/v45-readme-asset-promotion-spec.md",
            "docs/v52-readme-ux-spec.md",
            "docs/v67-dogfood-progress-asset-promotion-spec.md",
            "docs/v69-readme-quality-gate-spec.md",
            "docs/v70-contract-timeout-spec.md",
            "docs/v71-release-timing-spec.md",
            "docs/v72-release-timing-history-spec.md",
            "docs/v73-large-workflow-control-spec.md",
            "docs/v74-large-workflow-dogfood-spec.md",
            "docs/v75-large-workflow-next-spec.md",
            "docs/v76-large-workflow-queue-bridge-spec.md",
            "docs/v77-large-workflow-queue-preflight-spec.md",
            "docs/v78-graph-timing-gate-spec.md",
            "docs/v79-readme-graph-visibility-spec.md",
            "docs/v80-continuation-boundary-spec.md",
            "docs/v81-multi-slice-batch-spec.md",
            "docs/v82-execution-receipt-schema-spec.md",
            "docs/v83-runner-receipt-dry-run-spec.md",
            "docs/v84-installed-surface-audit-spec.md",
            "docs/v85-workflow-activation-spec.md",
            "docs/v86-keelplane-brand-spec.md",
            "docs/v87-brand-boundary-audit-spec.md",
            "docs/v88-roadmap-reconciliation-spec.md",
            "docs/v89-command-safety-spec.md",
            "docs/v90-workflow-activation-v2-spec.md",
            "docs/v91-contract-tiering-spec.md",
            "docs/v92-evidence-oracle-spec.md",
            "docs/v93-workflow-narrative-spec.md",
            "docs/v94-control-deck-score-spec.md",
            "docs/v95-control-deck-score-history-spec.md",
            "docs/v96-metric-ladder-spec.md",
            "docs/v97-benchmark-readiness-spec.md",
            "docs/v98-wave-operator-spec.md",
            "docs/v99-wave-receipt-spec.md",
            "docs/v100-promotion-evidence-spec.md",
            "docs/v101-promotion-route-spec.md",
            "generated `out/` directories are verification evidence, not source of truth",
            "direct-agent superiority is not claimed",
            "process progress is not an upward benchmark claim",
            "multi-slice continuation is allowed only for source-only or fixture-only",
            "receipt work is allowed through dry-run evidence only",
            "active local skill path",
            "next safe action is workflow design",
            "brand boundary audits preserve depone as the public brand",
            "roadmap reconciliation audits keep spec, roadmap, and release history aligned",
            "evidence oracle checks must pass before future scoring or graph promotion",
            "workflow narrative labels are status rendering only",
            "control deck readiness scores are operator status",
            "control deck score history is internal operator readiness history",
            "the metric ladder treats readiness history as a real operator metric",
            "benchmark readiness is an internal indicator",
            "wave selection is source-only",
            "wave receipts are source-only evidence links",
        ],
    )
    require_terms(
        "docs/dwm-branding.md",
        [
            "depone is the public product brand",
            "dwm core stands for",
            "codex skill name is `depone`",
            "repository slug remains `dwm`",
            "`dwm_*.py` file prefix",
            "do not claim autonomous execution",
        ],
    )
    require_terms(
        "docs/v86-keelplane-brand-spec.md",
        [
            "status: implemented first depone brand decision",
            "public product brand: `depone`",
            "internal engine name: `dwm core`",
            "skill name: `depone`",
            "`dwm_*.py` file prefix",
            "do not rename cli commands",
            "do not claim autonomous execution",
        ],
    )
    require_terms(
        "docs/v86-decision.md",
        [
            "decision: keep",
            "`readme.md` now leads with `depone`",
            "`docs/dwm-branding.md` defines `depone`",
            "`assets/dwm-hero.svg` names `depone`",
            "does not claim autonomous execution",
        ],
    )
    require_terms(
        "docs/v87-brand-boundary-audit-spec.md",
        [
            "status: implemented brand boundary audit",
            "`scripts/dwm_brand_boundary_audit.py`",
            "`brand-boundary-audit.json`",
            "`brand-boundary-audit.md`",
            "public product brand: `depone`",
            "internal engine name: `dwm core`",
            "skill name: `depone`",
            "repository slug remains `dwm`",
            "does not claim autonomous execution",
        ],
    )
    require_terms(
        "docs/v87-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_brand_boundary_audit.py --manifest fixtures/v87/manifest.json --out out/brand-boundary-audits/v87-final",
            "`suite_id`: `v87-brand-boundary-audit`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "`decision`: `brand_boundary_ready`",
            "`public_product_brand`: `depone`",
            "`skill_name`: `depone`",
            "does not claim autonomous execution",
        ],
    )
    require_terms(
        "docs/v88-roadmap-reconciliation-spec.md",
        [
            "status: implemented roadmap reconciliation audit",
            "`scripts/dwm_roadmap_reconciliation.py`",
            "`roadmap-reconciliation.json`",
            "`roadmap-reconciliation.md`",
            "public product brand: `depone`",
            "internal engine name: `dwm core`",
            "latest reconciled version: `v119`",
            "does not claim autonomous execution",
        ],
    )
    require_terms(
        "docs/v88-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_roadmap_reconciliation.py --manifest fixtures/v88/manifest.json --out out/roadmap-reconciliations/v88-final",
            "`suite_id`: `v88-roadmap-reconciliation`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "`decision`: `roadmap_reconciled`",
            "`latest_version`: `v119`",
            "does not execute queued commands",
        ],
    )
    require_terms(
        "docs/v89-command-safety-spec.md",
        [
            "status: implemented shared command safety inference",
            "`scripts/dwm_command_safety.py`",
            "`assess_command_safety(command, declared_risk_codes)`",
            "`gated_risk_codes`",
            "do not treat candidate-declared `risk_codes` as authoritative",
            "undeclared runner write risk",
            "url-inferring network risk",
        ],
    )
    require_terms(
        "docs/v89-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_command_safety.py --manifest fixtures/v89/manifest.json --out out/command-safety/v89-final",
            "`suite_id`: `v89-command-safety`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "undeclared runner write-risk inference",
            "unsupported shell command blocking",
            "url-inferring network risk",
        ],
    )
    require_terms(
        "docs/v90-workflow-activation-v2-spec.md",
        [
            "status: implemented product-evidence activation",
            "`scripts/dwm_workflow_activation.py`",
            "`ready_for_next_workflow_design`",
            "`brand_boundary_ready`",
            "`roadmap_reconciled`",
            "the roadmap latest version is not the current reconciled version",
            "command safety did not keep all required fixtures",
            "does not execute commands",
        ],
    )
    require_terms(
        "docs/v90-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_workflow_activation.py --manifest fixtures/v90/manifest.json --out out/workflow-activations/v90-final",
            "`suite_id`: `v90-workflow-activation-v2`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "`roadmap_latest_version`: `v119`",
            "`command_safety_decision`: `keep`",
        ],
    )
    require_terms(
        "docs/v91-contract-tiering-spec.md",
        [
            "status: implemented release-contract tiering",
            "`scripts/check_contract.py`",
            "`--tier smoke`",
            "`--tier changed`",
            "`--tier full`",
            "full release verification as the publishing boundary",
            "do not treat smoke or changed tiers as publish approval",
        ],
    )
    require_terms(
        "docs/v91-decision.md",
        [
            "decision: keep",
            "python scripts/check_contract.py --self-test",
            "python scripts/check_contract.py --tier smoke",
            "python scripts/check_contract.py --tier changed",
            "`smoke`: pass",
            "`changed`: pass",
            "`full_default`: preserved by `python scripts/check_contract.py`",
        ],
    )
    require_terms(
        "docs/v92-evidence-oracle-spec.md",
        [
            "status: implemented read-only evidence oracle",
            "`scripts/dwm_evidence_oracle.py`",
            "`evidence-oracle.json`",
            "`evidence-oracle.md`",
            "`json_equals`",
            "`json_hash_equals`",
            "do not execute commands",
            "do not publish benchmark claims",
        ],
    )
    require_terms(
        "docs/v92-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_evidence_oracle.py --manifest fixtures/v92/manifest.json --out out/evidence-oracles/v92-final",
            "`suite_id`: `v92-evidence-oracle`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "source-hash drift blocks",
            "missing artifacts block",
        ],
    )
    require_terms(
        "docs/v93-workflow-narrative-spec.md",
        [
            "status: implemented workflow narrative",
            "`scripts/dwm_workflow_narrative.py`",
            "`workflow-narrative.json`",
            "`workflow-narrative.md`",
            "`chart`",
            "`gate`",
            "`oracle`",
            "do not claim autonomous execution",
            "status rendering only",
        ],
    )
    require_terms(
        "docs/v93-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_workflow_narrative.py --manifest fixtures/v93/manifest.json --out out/workflow-narratives/v93-final",
            "`suite_id`: `v93-workflow-narrative`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "activation source-hash drift blocks",
            "status rendering only",
        ],
    )
    require_terms(
        "docs/v94-control-deck-score-spec.md",
        [
            "status: implemented operator-readiness scoring",
            "`scripts/dwm_control_deck_score.py`",
            "`control-deck-score.json`",
            "`control-deck-score.md`",
            "`is_public_benchmark: false`",
            "`is_upward_trend_claim: false`",
            "do not claim benchmark success",
            "do not claim upward performance",
        ],
    )
    require_terms(
        "docs/v94-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_control_deck_score.py --manifest fixtures/v94/manifest.json --out out/control-deck-scores/v94-final",
            "`suite_id`: `v94-control-deck-score`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "unsafe voice policy blocks",
            "not a public benchmark score",
        ],
    )
    require_terms(
        "docs/v95-control-deck-score-history-spec.md",
        [
            "status: implemented operator-readiness history",
            "`scripts/dwm_control_deck_score_history.py`",
            "`control-deck-score-history.json`",
            "`control-deck-score-history.md`",
            "`control-deck-score-history.svg`",
            "`is_public_benchmark: false`",
            "`is_upward_trend_claim: false`",
            "do not publish benchmark performance",
            "do not claim upward product quality",
        ],
    )
    require_terms(
        "docs/v95-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_control_deck_score_history.py --manifest fixtures/v95/manifest.json --out out/control-deck-score-history/v95-final",
            "`suite_id`: `v95-control-deck-score-history`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "unsafe public benchmark claim blocks",
            "not a public benchmark graph",
        ],
    )
    require_terms(
        "docs/v96-metric-ladder-spec.md",
        [
            "status: implemented graph claim-level gate",
            "`scripts/dwm_metric_ladder.py`",
            "`metric-ladder.json`",
            "`metric-ladder.md`",
            "process progress graphs",
            "operator readiness graphs",
            "public benchmark graphs",
            "do not publish readiness history as benchmark evidence",
        ],
    )
    require_terms(
        "docs/v96-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_metric_ladder.py --manifest fixtures/v96/manifest.json --out out/metric-ladders/v96-final",
            "`suite_id`: `v96-metric-ladder`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "public benchmark claims require promotion evidence",
            "not a public benchmark graph",
        ],
    )
    require_terms(
        "docs/v97-benchmark-readiness-spec.md",
        [
            "status: implemented benchmark readiness report",
            "`scripts/dwm_benchmark_readiness.py`",
            "`benchmark-readiness.json`",
            "`benchmark-readiness.md`",
            "`readiness_score_is_public_benchmark: false`",
            "`requires_promotion_for_public_graph: true`",
            "not a public benchmark graph",
            "public benchmark claims require promotion evidence",
        ],
    )
    require_terms(
        "docs/v97-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_benchmark_readiness.py --manifest fixtures/v97/manifest.json --out out/benchmark-readiness/v97-final",
            "`suite_id`: `v97-benchmark-readiness`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "public benchmark claims require promotion evidence",
            "not a public benchmark graph",
        ],
    )
    require_terms(
        "docs/v98-wave-operator-spec.md",
        [
            "status: implemented next wave operator",
            "`scripts/dwm_wave_operator.py`",
            "`wave-operator.json`",
            "`wave-operator.md`",
            "`dogfood-evidence-wave`",
            "`human_gate_required`",
            "does not execute commands",
            "public benchmark graph publication still requires promotion evidence and human review",
        ],
    )
    require_terms(
        "docs/v98-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_wave_operator.py --manifest fixtures/v98/manifest.json --out out/wave-operators/v98-final",
            "`suite_id`: `v98-wave-operator`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "`dogfood-evidence-wave`",
            "does not execute commands",
        ],
    )
    require_terms(
        "docs/v99-wave-receipt-spec.md",
        [
            "status: implemented wave receipt",
            "`scripts/dwm_wave_receipt.py`",
            "`wave-receipt.json`",
            "`wave-receipt.md`",
            "`wave_receipt_ready`",
            "`wave_receipt_is_public_benchmark: false`",
            "public benchmark graph publication still requires promotion evidence and human review",
            "does not execute commands",
        ],
    )
    require_terms(
        "docs/v99-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_wave_receipt.py --manifest fixtures/v99/manifest.json --out out/wave-receipts/v99-final",
            "`suite_id`: `v99-wave-receipt`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "real dogfood acquisition evidence",
            "does not execute commands",
        ],
    )
    require_terms(
        "docs/v100-promotion-evidence-spec.md",
        [
            "status: implemented promotion evidence ledger",
            "`scripts/dwm_promotion_evidence.py`",
            "`promotion-evidence.json`",
            "`promotion-evidence.md`",
            "`promotion_evidence_recorded`",
            "`promotion_evidence_is_public_benchmark`: false",
            "readme graph publication remains blocked until promotion evidence passes and a human approves publication",
            "does not execute commands",
        ],
    )
    require_terms(
        "docs/v100-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_promotion_evidence.py --manifest fixtures/v100/manifest.json --out out/promotion-evidence/v100-final",
            "`suite_id`: `v100-promotion-evidence`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "requires human review",
            "does not execute commands",
        ],
    )
    require_terms(
        "docs/v101-promotion-route-spec.md",
        [
            "status: implemented promotion route planner",
            "`scripts/dwm_promotion_route.py`",
            "`promotion-route.json`",
            "`promotion-route.md`",
            "`route_ready`",
            "`human_gate_required`",
            "does not execute commands",
            "does not approve readme graph publication",
        ],
    )
    require_terms(
        "docs/v101-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_promotion_route.py --manifest fixtures/v101/manifest.json --out out/promotion-routes/v101-final",
            "`suite_id`: `v101-promotion-route`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "human gate routing",
            "does not execute commands",
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
            "optional adapter targets",
            "external runtimes optional adapter targets",
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
        "docs/v22-role-pack-spec.md",
        [
            "status: implemented first role pack contract in `scripts/dwm_roles.py`.",
            "planner",
            "explorer",
            "worker",
            "reviewer",
            "verifier",
            "operator",
            "err_role_permission_escalation",
            "err_role_output_schema_missing",
            "err_role_reviewer_self_repair",
        ],
    )
    require_terms(
        "docs/v23-harness-benchmark-spec.md",
        [
            "status: implemented first harness benchmark gate in `scripts/dwm_benchmark.py`.",
            "failing-test-fix",
            "small-refactor",
            "auth-permission-audit",
            "ui-render-regression",
            "docs-code-consistency",
            "multi-file-migration",
            "err_benchmark_baseline_missing",
            "err_benchmark_safety_regression",
            "err_benchmark_unsupported_claim",
        ],
    )
    require_terms(
        "docs/v24-live-benchmark-evidence-spec.md",
        [
            "status: implemented first live benchmark evidence capture in",
            "fixture-control",
            "adapter-availability",
            "run.json",
            "commands.json",
            "evidence.json",
            "score.json",
            "status.json",
            "err_live_benchmark_corpus_missing",
            "err_live_benchmark_unsafe_mode",
            "err_live_benchmark_stale_score",
            "err_live_benchmark_adapter_unavailable",
        ],
    )
    require_terms(
        "docs/v25-benchmark-task-materializer-spec.md",
        [
            "status: implemented first benchmark task materializer in",
            "failing-test-fix",
            "small-refactor",
            "auth-permission-audit",
            "ui-render-regression",
            "docs-code-consistency",
            "multi-file-migration",
            "prompt.md",
            "verifier.json",
            "initial-verification.json",
            "err_benchmark_tasks_corpus_mismatch",
            "err_benchmark_tasks_unsafe_path",
            "err_benchmark_tasks_stale_template",
        ],
    )
    require_terms(
        "docs/v26-benchmark-attempt-harness-spec.md",
        [
            "status: implemented first benchmark attempt harness in",
            "scripted-fixture",
            "attempt.json",
            "changes.json",
            "verification.json",
            "ledger.json",
            "err_benchmark_attempts_missing_tasks",
            "err_benchmark_attempts_stale_plan",
            "err_benchmark_attempts_unsafe_path",
        ],
    )
    require_terms(
        "docs/v27-adapter-smoke-spec.md",
        [
            "status: implemented first adapter smoke evidence in",
            "adapter-smoke.json",
            "status.json",
            "err_adapter_smoke_unavailable",
            "err_adapter_smoke_unsafe_command",
            "err_adapter_smoke_unknown_task",
            "err_adapter_smoke_stale_template",
        ],
    )
    require_terms(
        "docs/v28-live-attempt-planner-spec.md",
        [
            "status: implemented first live attempt planner in",
            "prompt.md",
            "command-plan.json",
            "status.json",
            "err_live_attempt_adapter_unavailable",
            "err_live_attempt_stale_smoke",
            "err_live_attempt_unknown_task",
            "err_live_attempt_unsafe_command",
        ],
    )
    require_terms(
        "docs/v29-live-runner-preflight-spec.md",
        [
            "status: implemented first live runner preflight gate in",
            "preflight.json",
            "ready-for-human-run",
            "err_live_runner_plan_skipped",
            "err_live_runner_stale_plan",
            "err_live_runner_policy_blocked",
            "err_live_runner_artifact_missing",
        ],
    )
    require_terms(
        "docs/v30-live-receipt-ingestion-spec.md",
        [
            "status: implemented first live receipt ingestion gate in",
            "receipt.json",
            "receipt-ledger.json",
            "err_live_receipt_preflight_not_ready",
            "err_live_receipt_stale_preflight",
            "err_live_receipt_command_mismatch",
            "err_live_receipt_artifact_missing",
        ],
    )
    require_terms(
        "docs/v31-live-receipt-judgment-spec.md",
        [
            "status: implemented first live receipt judgment gate in",
            "judgment.json",
            "err_live_receipt_judge_artifact_missing",
            "err_live_receipt_judge_stale_receipt",
            "err_live_receipt_judge_receipt_not_accepted",
            "err_live_receipt_judge_hash_mismatch",
        ],
    )
    require_terms(
        "docs/v32-live-score-verifier-spec.md",
        [
            "status: implemented first live score verifier bridge in",
            "score.json",
            "err_live_score_artifact_missing",
            "err_live_score_stale_judgment",
            "err_live_score_task_mismatch",
            "err_live_score_hash_mismatch",
            "err_live_score_verification_invalid",
        ],
    )
    require_terms(
        "docs/v32-to-v35-live-scoring-workflow.md",
        [
            "turn v31 live receipt judgments into benchmark-scoring evidence",
            "pipeline with adversarial verification",
            "v32 task verifier",
            "v33 aggregate scorer",
            "v34 adversarial review",
            "v35 report",
            "report.json.graph_metrics",
        ],
    )
    require_terms(
        "docs/v33-live-score-aggregate-spec.md",
        [
            "status: implemented first live score aggregate gate in",
            "aggregate-score.json",
            "err_live_score_aggregate_artifact_missing",
            "err_live_score_aggregate_stale_score",
            "err_live_score_aggregate_task_missing",
            "err_live_score_aggregate_task_duplicate",
            "err_live_score_aggregate_unsupported_claim",
        ],
    )
    require_terms(
        "docs/v34-live-score-review-spec.md",
        [
            "status: implemented first adversarial live score review gate in",
            "reviewed-score.json",
            "err_live_score_review_artifact_missing",
            "err_live_score_review_stale_aggregate",
            "err_live_score_review_task_mismatch",
            "err_live_score_review_hash_mismatch",
        ],
    )
    require_terms(
        "docs/v35-live-report-spec.md",
        [
            "status: implemented first live benchmark report gate in",
            "report.json",
            "report.md",
            "graph_metrics",
            "err_live_report_artifact_missing",
            "err_live_report_stale_review",
            "err_live_report_hash_mismatch",
            "err_live_report_unsupported_claim",
        ],
    )
    require_terms(
        "docs/v36-readme-benchmark-graph-spec.md",
        [
            "status: implemented first readme benchmark graph artifact generator in",
            "benchmark-graph.json",
            "benchmark-graph.svg",
            "readme-snippet.md",
            "report.json.graph_metrics",
            "err_readme_graph_artifact_missing",
            "err_readme_graph_stale_report",
            "err_readme_graph_metrics_invalid",
        ],
    )
    require_terms(
        "docs/v38-benchmark-history-spec.md",
        [
            "status: implemented first benchmark history ledger and trend graph in",
            "history.json",
            "trend.svg",
            "report.json.graph_metrics",
            "err_benchmark_history_artifact_missing",
            "err_benchmark_history_stale_report",
            "err_benchmark_history_metrics_invalid",
            "err_benchmark_history_duplicate_report",
        ],
    )
    require_terms(
        "docs/v39-benchmark-promotion-spec.md",
        [
            "status: implemented first benchmark trend promotion gate in",
            "promotion.json",
            "promoted-trend.svg",
            "err_benchmark_promotion_insufficient_history",
            "err_benchmark_promotion_source_not_release",
            "err_benchmark_promotion_not_upward",
            "err_benchmark_promotion_delta_too_small",
            "err_benchmark_promotion_stale_history",
        ],
    )
    require_terms(
        "docs/v40-benchmark-snapshot-spec.md",
        [
            "status: implemented first release benchmark snapshot recorder in",
            "snapshot.json",
            "source_kind: release",
            "err_benchmark_snapshot_artifact_missing",
            "err_benchmark_snapshot_release_id_missing",
            "err_benchmark_snapshot_stale_report",
            "err_benchmark_snapshot_metrics_invalid",
        ],
    )
    require_terms(
        "docs/v41-benchmark-series-spec.md",
        [
            "status: implemented first benchmark snapshot series builder in",
            "series.json",
            "err_benchmark_series_insufficient_snapshots",
            "err_benchmark_series_duplicate_release",
            "err_benchmark_series_duplicate_report",
            "err_benchmark_series_stale_snapshot",
            "err_benchmark_series_source_not_release",
        ],
    )
    require_terms(
        "docs/v42-benchmark-candidate-spec.md",
        [
            "status: implemented first benchmark publish candidate workflow in",
            "candidate.json",
            "err_benchmark_candidate_artifact_missing",
            "err_benchmark_candidate_stale_series",
            "err_benchmark_candidate_promotion_not_upward",
            "err_benchmark_candidate_promotion_delta_too_small",
        ],
    )
    require_terms(
        "docs/v43-direction-check-roadmap.md",
        [
            "status: direction checkpoint written after v42 benchmark candidate workflow",
            "dwm is still on a useful path",
            "what this does not prove yet",
            "v44: publish candidate review gate",
            "v45: readme asset promotion",
            "v46: long-run workflow queue",
            "v47: real dogfood task corpus",
            "v48: daily operator loop",
            "v49: adapter parity matrix",
            "status: first parity matrix implemented",
            "v50: release candidate cut",
            "status: first release candidate cut implemented",
            "it is drifting if",
        ],
    )
    require_terms(
        "docs/v44-candidate-review-gate-spec.md",
        [
            "status: implemented first benchmark candidate review gate in",
            "candidate-review.json",
            "publish-checklist.md",
            "err_benchmark_candidate_review_stale_candidate",
            "err_benchmark_candidate_review_promotion_missing",
            "err_benchmark_candidate_review_hash_mismatch",
            "err_benchmark_candidate_review_overclaim",
        ],
    )
    require_terms(
        "docs/v45-readme-asset-promotion-spec.md",
        [
            "status: implemented first readme asset promotion bundle in",
            "asset-promotion.json",
            "asset-diff.md",
            "err_readme_asset_promotion_stale_review",
            "err_readme_asset_promotion_asset_missing",
            "err_readme_asset_promotion_hash_mismatch",
            "err_readme_asset_promotion_review_not_approved",
            "err_readme_asset_promotion_overclaim",
        ],
    )
    require_terms(
        "docs/v46-long-run-workflow-queue-spec.md",
        [
            "status: implemented first long-run workflow queue in",
            "queue.json",
            "next-action.md",
            "err_dwm_queue_evidence_missing",
            "err_dwm_queue_unsafe_action",
            "err_dwm_queue_verification_failed",
            "err_dwm_queue_human_gate_required",
            "err_dwm_queue_stale_status",
        ],
    )
    require_terms(
        "docs/v47-real-dogfood-corpus-spec.md",
        [
            "status: implemented first real dogfood corpus recorder in",
            "dogfood-corpus.json",
            "queue-packets.json",
            "not-run",
            "err_dogfood_corpus_required_task_missing",
            "err_dogfood_corpus_unsafe_task",
            "err_dogfood_corpus_public_claim",
            "err_dogfood_corpus_evidence_missing",
        ],
    )
    require_terms(
        "docs/v48-daily-operator-loop-spec.md",
        [
            "status: implemented first daily operator loop in",
            "operator-loop.json",
            "today.md",
            "err_daily_operator_corpus_missing",
            "err_daily_operator_stale_queue",
            "err_daily_operator_queue_missing",
        ],
    )
    require_terms(
        "docs/v49-adapter-parity-matrix-spec.md",
        [
            "status: implemented first adapter parity matrix in",
            "adapter-parity.json",
            "adapter-parity.md",
            "support_level",
            "err_adapter_parity_incomplete",
            "err_adapter_parity_unknown_adapter",
            "err_adapter_parity_unsupported_action",
            "err_adapter_parity_planned_only",
        ],
    )
    require_terms(
        "docs/v50-release-candidate-cut-spec.md",
        [
            "status: implemented first release candidate cut in",
            "release-candidate.json",
            "release-notes.md",
            "release-checklist.md",
            "err_release_candidate_parity_missing",
            "err_release_candidate_parity_stale",
            "err_release_candidate_operator_missing",
            "err_release_candidate_operator_stale",
            "err_release_candidate_overclaim",
        ],
    )
    require_terms(
        "docs/v51-canonical-demo-spec.md",
        [
            "status: implemented first canonical demo in",
            "demo.json",
            "status.json",
            "readme.md",
            "err_demo_path_unsafe",
            "err_demo_path_symlink",
            "err_demo_command_failed",
        ],
    )
    require_terms(
        "docs/v52-readme-ux-spec.md",
        [
            "status: implemented readme ux consolidation in",
            "one-command local demo",
            "normal loop",
            "explicit honesty table",
            "benchmark graph language tied to source-bound evidence",
            "do not add a fake benchmark trend",
            "docs/spec.md remains outside this slice",
        ],
    )
    require_terms(
        "docs/v52-decision.md",
        [
            "decision: keep",
            "python scripts/check_contract.py",
            "canonical demo as the first action",
            "current honesty boundaries",
            "does not claim live adapter execution",
            "promoted public benchmark trend",
        ],
    )
    require_terms(
        "docs/v53-demo-inspect-spec.md",
        [
            "status: implemented first demo inspect surface in",
            "python scripts/dwm_demo.py inspect --demo out/demo/quickstart",
            "demo-inspect.json",
            "demo-summary.md",
            "err_demo_artifact_missing",
            "err_demo_stale_hash",
            "do not refresh stale demo artifacts silently",
        ],
    )
    require_terms(
        "docs/v53-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_demo.py --manifest fixtures/v53/manifest.json --out out/demo/v53-final",
            "demo-inspect.json",
            "demo-summary.md",
            "missing demo artifact blocking",
            "stale command hash blocking",
            "does not claim live adapter execution",
        ],
    )
    require_terms(
        "docs/v54-dogfood-attempts-spec.md",
        [
            "status: implemented first measured dogfood comparison ledger in",
            "python scripts/dwm_dogfood_attempts.py record --corpus out/dogfood-corpus/<corpus_id> --attempts attempts.json --out out/dogfood-attempts/<attempt_id>",
            "dogfood-attempts.json",
            "comparison-ledger.json",
            "err_dogfood_attempts_unknown_task",
            "err_dogfood_attempts_evidence_missing",
            "err_dogfood_attempts_metric_invalid",
            "err_dogfood_attempts_overclaim",
            "do not execute attempts automatically",
        ],
    )
    require_terms(
        "docs/v54-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_attempts.py --manifest fixtures/v54/manifest.json --out out/dogfood-attempts/v54-final",
            "dogfood-attempts.json",
            "comparison-ledger.json",
            "missing evidence blocking",
            "invalid metric blocking",
            "does not claim live adapter execution",
        ],
    )
    require_terms(
        "docs/v55-adapter-live-matrix-spec.md",
        [
            "status: implemented first adapter live availability matrix in",
            "python scripts/dwm_adapter_live_matrix.py matrix --out out/adapter-live-matrix/<matrix_id>",
            "adapter-live-matrix.json",
            "adapter-live-matrix.md",
            "err_adapter_live_matrix_unsafe_command",
            "err_adapter_live_matrix_command_missing",
            "err_adapter_live_matrix_not_registered",
            "do not execute task prompts",
            "do not read secrets or tokens",
        ],
    )
    require_terms(
        "docs/v55-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_adapter_live_matrix.py --manifest fixtures/v55/manifest.json --out out/adapter-live-matrix/v55-final",
            "adapter-live-matrix.json",
            "adapter-live-matrix.md",
            "missing command blocking",
            "unregistered target blocking",
            "does not claim live task execution",
        ],
    )
    require_terms(
        "docs/v56-dogfood-measure-spec.md",
        [
            "status: implemented first measured local dogfood sample runner in",
            "python scripts/dwm_dogfood_measure.py sample --out out/dogfood-measurements/<measurement_id>",
            "measurement.json",
            "attempts.json",
            "err_dogfood_measure_direct_requires_gate",
            "err_dogfood_measure_unknown_task",
            "err_dogfood_measure_command_unsafe",
            "do not fill `direct-codex` comparison slots without a human-gated live",
        ],
    )
    require_terms(
        "docs/v56-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_measure.py --manifest fixtures/v56/manifest.json --out out/dogfood-measurements/v56-final",
            "measurement.json",
            "attempts.json",
            "linked `dogfood-attempts.json`",
            "direct codex gate blocking",
            "does not claim live adapter execution",
        ],
    )
    require_terms(
        "docs/v57-dogfood-pair-spec.md",
        [
            "status: implemented first gated dogfood comparison pair in",
            "python scripts/dwm_dogfood_pair.py pair --dwm-measure out/dogfood-measurements/<measurement_id> --direct-receipt direct-receipt.json --out out/dogfood-pairs/<pair_id>",
            "comparison-pair.json",
            "comparison-pair.md",
            "pair-status.json",
            "err_dogfood_pair_gate_missing",
            "err_dogfood_pair_task_mismatch",
            "err_dogfood_pair_evidence_missing",
            "err_dogfood_pair_overclaim",
            "do not run live codex",
        ],
    )
    require_terms(
        "docs/v57-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_pair.py --manifest fixtures/v57/manifest.json --out out/dogfood-pairs/v57-final",
            "comparison-pair.json",
            "comparison-pair.md",
            "missing direct codex gate blocking",
            "task mismatch blocking",
            "does not claim live codex execution",
        ],
    )
    require_terms(
        "docs/v58-dogfood-pair-series-spec.md",
        [
            "status: implemented first dogfood pair series and graph-readiness gate in",
            "python scripts/dwm_dogfood_pair_series.py build --pair-root out/dogfood-pairs --out out/dogfood-pair-series/<series_id>",
            "pair-series.json",
            "pair-series.md",
            "graph-readiness.json",
            "err_dogfood_pair_series_duplicate_pair",
            "err_dogfood_pair_series_stale_pair",
            "err_dogfood_pair_series_overclaim",
            "err_dogfood_pair_series_insufficient_pairs",
            "do not publish readme benchmark graphs",
        ],
    )
    require_terms(
        "docs/v58-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_pair_series.py --manifest fixtures/v58/manifest.json --out out/dogfood-pair-series/v58-final",
            "pair-series.json",
            "pair-series.md",
            "graph-readiness.json",
            "insufficient pair readiness blocking",
            "does not claim readme graph promotion",
        ],
    )
    require_terms(
        "docs/v59-dogfood-chart-candidate-spec.md",
        [
            "status: implemented first local dogfood chart candidate gate in",
            "python scripts/dwm_dogfood_chart_candidate.py candidate --series out/dogfood-pair-series/<series_id> --out out/dogfood-chart-candidates/<chart_id>",
            "chart-candidate.json",
            "chart-candidate.md",
            "chart-data.csv",
            "err_dogfood_chart_candidate_not_ready",
            "err_dogfood_chart_candidate_stale_series",
            "err_dogfood_chart_candidate_overclaim",
            "do not publish readme benchmark graphs",
        ],
    )
    require_terms(
        "docs/v59-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_chart_candidate.py --manifest fixtures/v59/manifest.json --out out/dogfood-chart-candidates/v59-final",
            "chart-candidate.json",
            "chart-candidate.md",
            "chart-data.csv",
            "not-ready series blocking",
            "does not claim readme graph promotion",
        ],
    )
    require_terms(
        "docs/v60-dogfood-chart-review-spec.md",
        [
            "status: implemented first local dogfood chart review gate in",
            "python scripts/dwm_dogfood_chart_review.py review --candidate out/dogfood-chart-candidates/<chart_id> --receipt review-receipt.json --out out/dogfood-chart-reviews/<review_id>",
            "chart-review.json",
            "chart-review.md",
            "err_dogfood_chart_review_receipt_missing",
            "err_dogfood_chart_review_rejected",
            "err_dogfood_chart_review_stale_receipt",
            "err_dogfood_chart_review_overclaim",
            "do not publish readme benchmark graphs",
        ],
    )
    require_terms(
        "docs/v60-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_chart_review.py --manifest fixtures/v60/manifest.json --out out/dogfood-chart-reviews/v60-final",
            "chart-review.json",
            "chart-review.md",
            "missing receipt blocking",
            "does not claim readme graph promotion",
        ],
    )
    require_terms(
        "docs/v61-dogfood-acquire-spec.md",
        [
            "status: implemented first one-command dogfood evidence acquisition loop in",
            "python scripts/dwm_dogfood_acquire.py acquire --task-id <task_id> --out out/dogfood-acquisitions/<acquisition_id>",
            "direct-receipt-template.json",
            "err_dogfood_acquire_direct_receipt_required",
            "err_dogfood_acquire_receipt_missing",
            "err_dogfood_pair_task_mismatch",
            "do not run live codex",
        ],
    )
    require_terms(
        "docs/v61-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_acquire.py --manifest fixtures/v61/manifest.json --out out/dogfood-acquisitions/v61-final",
            "acquisition.json",
            "direct-receipt-template.json",
            "chart candidate creation when enough pairs exist",
            "does not claim live codex execution",
        ],
    )
    require_terms(
        "docs/v62-dogfood-operator-spec.md",
        [
            "status: implemented first deterministic dogfood acquisition recommendation loop in",
            "python scripts/dwm_dogfood_operator.py recommend --out out/dogfood-operator/<operator_id>",
            "dogfood-operator.json",
            "dogfood-operator.md",
            "err_dogfood_operator_stale_pair",
            "err_dogfood_operator_stale_acquisition",
            "err_dogfood_operator_direct_receipt_required",
            "do not run live codex",
        ],
    )
    require_terms(
        "docs/v62-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_operator.py --manifest fixtures/v62/manifest.json --out out/dogfood-operator/v62-final",
            "dogfood-operator.json",
            "next acquisition command recommendation",
            "waiting direct receipt blocking",
            "stale pair blocking",
            "does not claim live codex execution",
        ],
    )
    require_terms(
        "docs/v63-dogfood-operator-duplicate-root-spec.md",
        [
            "status: implemented duplicate pair-root blocking in",
            "python scripts/dwm_dogfood_operator.py recommend --out out/dogfood-operator/<operator_id>",
            "err_dogfood_operator_duplicate_task",
            "duplicate_task_ids",
            "do not delete duplicate pairs",
            "do not treat duplicate task pairs as graph-ready",
        ],
    )
    require_terms(
        "docs/v63-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_operator.py --manifest fixtures/v63/manifest.json --out out/dogfood-operator/v63-final",
            "err_dogfood_operator_duplicate_task",
            "resolve-duplicate-pair-root",
            "waiting direct receipt blocking",
            "does not claim live codex execution",
        ],
    )
    require_terms(
        "docs/v64-dogfood-pair-select-spec.md",
        [
            "status: implemented clean pair-root selector in",
            "python scripts/dwm_dogfood_pair_select.py select --pair-root out/dogfood-pairs --out out/dogfood-pair-selections/<selection_id>",
            "pair-selection.json",
            "pair-selection.md",
            "lexicographic-last",
            "err_dogfood_pair_select_stale_pair",
            "err_dogfood_pair_select_clean_root_unsafe",
            "do not delete source pairs",
        ],
    )
    require_terms(
        "docs/v64-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_pair_select.py --manifest fixtures/v64/manifest.json --out out/dogfood-pair-selections/v64-final",
            "pair-selection.json",
            "clean pair root generation",
            "v58 series generation",
            "duplicate rejection recording",
            "does not claim source pair deletion",
        ],
    )
    require_terms(
        "docs/v65-dogfood-chart-render-spec.md",
        [
            "status: implemented reviewed local dogfood chart rendering in",
            "python scripts/dwm_dogfood_chart_render.py render --review out/dogfood-chart-reviews/<review_id> --out out/dogfood-chart-renders/<render_id>",
            "chart-render.json",
            "chart-render.svg",
            "err_dogfood_chart_render_stale_review",
            "err_dogfood_chart_render_overclaim",
            "err_dogfood_chart_render_stale_candidate",
            "do not publish readme graph assets",
        ],
    )
    require_terms(
        "docs/v65-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_chart_render.py --manifest fixtures/v65/manifest.json --out out/dogfood-chart-renders/v65-final",
            "chart-render.json",
            "chart-render.svg",
            "approved local render creation",
            "stale review blocking",
            "does not claim readme graph promotion",
        ],
    )
    require_terms(
        "docs/v66-dogfood-progress-spec.md",
        [
            "status: implemented dogfood evidence process progress graph in",
            "python scripts/dwm_dogfood_progress.py build --out out/dogfood-progress/<progress_id>",
            "dogfood-progress.json",
            "dogfood-progress.svg",
            "err_dogfood_progress_stale_artifact",
            "do not claim upward performance",
            "process completion, not upward performance claim",
        ],
    )
    require_terms(
        "docs/v66-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_progress.py --manifest fixtures/v66/manifest.json --out out/dogfood-progress/v66-final",
            "dogfood-progress.json",
            "partial progress rendering",
            "full progress rendering",
            "stale artifact blocking",
            "does not claim upward performance",
        ],
    )
    require_terms(
        "docs/v67-dogfood-progress-asset-promotion-spec.md",
        [
            "status: implemented readme process-progress asset promotion bundle in",
            "python scripts/dwm_dogfood_progress_asset_promotion.py promote --progress out/dogfood-progress/<progress_id> --out out/dogfood-progress-asset-promotions/<promotion_id>",
            "asset-promotion.json",
            "dwm-dogfood-progress.svg",
            "err_dogfood_progress_asset_promotion_stale_progress",
            "do not publish upward benchmark claims",
            "process completion, not upward performance claim",
        ],
    )
    require_terms(
        "docs/v67-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_dogfood_progress_asset_promotion.py --manifest fixtures/v67/manifest.json --out out/dogfood-progress-asset-promotions/v67-final",
            "asset-promotion.json",
            "readme-snippet.md",
            "stale progress blocking",
            "missing svg blocking",
            "hash drift blocking",
            "overclaim blocking",
            "does not edit tracked readme assets",
        ],
    )
    require_terms(
        "docs/v69-readme-quality-gate-spec.md",
        [
            "status: implemented readme product-page quality gate in",
            "python scripts/check_readme_quality.py readme.md",
            "maximum readme length",
            "excessive `v<number>` release-history mentions",
            "do not require readme to contain every command",
            "process graph non-benchmark wording",
        ],
    )
    require_terms(
        "docs/v69-decision.md",
        [
            "decision: keep",
            "python scripts/check_readme_quality.py --self-test",
            "readme maximum length",
            "required product-page sections",
            "release-note overgrowth blocking",
            "missing reference-doc blocking",
        ],
    )
    require_terms(
        "docs/v70-contract-timeout-spec.md",
        [
            "status: implemented release-contract command timeout and progress reporting in",
            "`run_contract_command()` now runs child commands with a default timeout",
            "release command index to stderr",
            "known long self-tests can receive a longer bounded timeout",
            "the timeout gate is fail-closed",
            "do not treat timeout as success",
        ],
    )
    require_terms(
        "docs/v70-decision.md",
        [
            "decision: keep",
            "python scripts/check_contract.py --self-test",
            "timed-out child command failure",
            "command name reporting",
            "contract step progress reporting",
            "longer bounded timeout selection",
            "does not claim the full contract is fast",
        ],
    )
    require_terms(
        "docs/v71-release-timing-spec.md",
        [
            "status: implemented release command timing planner and bounded measurement",
            "canonical command source remains `scripts/dwm.py:release_commands`",
            "`release-timing.json`",
            "`release-timing.md`",
            "`status.json`",
            "do not rerun the full release corpus by default",
            "do not treat timeout as success",
            "release-timing-blocked",
        ],
    )
    require_terms(
        "docs/v71-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_release_timing.py --manifest fixtures/v71/manifest.json --out out/release-timing/v71-final",
            "`suite_id`: `v71-release-timing`",
            "`fixture_count`: 3",
            "`required_passed`: 3",
            "`decision`: `keep`",
            "release command inventory",
            "bounded measurement",
            "timeout blocking",
            "does not claim the full release corpus is fast",
        ],
    )
    require_terms(
        "docs/v72-release-timing-history-spec.md",
        [
            "status: implemented release timing history ledger in",
            "`scripts/dwm_release_timing_history.py`",
            "`timing-history.json`",
            "`timing-history.md`",
            "`status.json`",
            "do not publish upward benchmark claims",
            "does not execute release commands",
            "duplicate `timing_id` values",
            "read-only against timing inputs",
        ],
    )
    require_terms(
        "docs/v72-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_release_timing_history.py --manifest fixtures/v72/manifest.json --out out/release-timing-history/v72-final",
            "`suite_id`: `v72-release-timing-history`",
            "`fixture_count`: 2",
            "`required_passed`: 2",
            "`decision`: `keep`",
            "mixed planned/recorded/blocked history aggregation",
            "duplicate timing id blocking",
            "source hash recording",
            "does not publish an upward benchmark claim",
        ],
    )
    require_terms(
        "docs/v73-large-workflow-control-spec.md",
        [
            "status: implemented large-workflow control-plane fitness evaluator in",
            "`scripts/dwm_large_workflow_control.py`",
            "direction fidelity",
            "large-work decomposition",
            "execution quality",
            "efficiency",
            "recovery ability",
            "evidence quality",
            "`large-workflow-control.json`",
            "`large-workflow-control.md`",
            "large-workflow-blocked",
            "does not claim fully autonomous completion",
        ],
    )
    require_terms(
        "docs/v73-large-workflow-control-blueprint.md",
        [
            "objective",
            "surface",
            "phases",
            "workers",
            "handoffs",
            "parallelism",
            "verification",
            "risk gates",
            "resume plan",
            "execution path",
        ],
    )
    require_terms(
        "docs/v73-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_large_workflow_control.py --manifest fixtures/v73/manifest.json --out out/large-workflow-control/v73-final",
            "`suite_id`: `v73-large-workflow-control`",
            "`fixture_count`: 3",
            "`required_passed`: 3",
            "`decision`: `keep`",
            "missing direction drift blocking",
            "overclaim blocking",
            "does not claim fully autonomous completion",
        ],
    )
    require_terms(
        "docs/v74-large-workflow-dogfood-spec.md",
        [
            "status: implemented v73 control receipt over real dwm dogfood state in",
            "`scripts/dwm_large_workflow_dogfood.py`",
            "`out/v9/v32-semantic-dogfood`",
            "`dogfood-control.json`",
            "`dogfood-control.md`",
            "`large-workflow-control.json`",
            "missing human gate blocking",
            "invalidated dogfood blocking",
            "does not claim fully autonomous completion",
        ],
    )
    require_terms(
        "docs/v74-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_large_workflow_dogfood.py --manifest fixtures/v74/manifest.json --out out/large-workflow-dogfood/v74-final",
            "`suite_id`: `v74-large-workflow-dogfood`",
            "`fixture_count`: 3",
            "`required_passed`: 3",
            "`decision`: `keep`",
            "applying v73 control to dogfood status",
            "missing human gate blocking",
            "invalidator blocking",
            "does not execute live adapters",
        ],
    )
    require_terms(
        "docs/v75-large-workflow-next-spec.md",
        [
            "status: implemented control-bound next-action selection in",
            "`scripts/dwm_large_workflow_next.py`",
            "`large-workflow-next.json`",
            "`large-workflow-next.md`",
            "`command_ready`",
            "`human_gate_required`",
            "`blocked`",
            "source hash drift",
            "write, delete, network, deploy, secret, or external-message",
            "does not run adapters",
            "do not publish upward trend or external superiority claims",
        ],
    )
    require_terms(
        "docs/v75-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_large_workflow_next.py --manifest fixtures/v75/manifest.json --out out/large-workflow-next/v75-final",
            "`suite_id`: `v75-large-workflow-next`",
            "`fixture_count`: 6",
            "`required_passed`: 6",
            "`decision`: `keep`",
            "control-bound next-action selection",
            "source hash drift blocking",
            "human gate handling for write-risk candidates",
            "does not execute selected commands",
        ],
    )
    require_terms(
        "docs/v76-large-workflow-queue-bridge-spec.md",
        [
            "status: implemented v75-to-v46 queue bridge in",
            "`scripts/dwm_large_workflow_queue_bridge.py`",
            "`queue-bridge.json`",
            "`queue-packets.json`",
            "`queue-bridge.md`",
            "`next-workflow-ready`",
            "`command_ready`",
            "write, delete, network, deploy, secret, or external-message",
            "does not execute the selected command",
            "do not claim market superiority",
        ],
    )
    require_terms(
        "docs/v76-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_large_workflow_queue_bridge.py --manifest fixtures/v76/manifest.json --out out/large-workflow-queue-bridge/v76-final",
            "`suite_id`: `v76-large-workflow-queue-bridge`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "v75 command-ready selection to v46 queue packet bridging",
            "human gate blocking",
            "selection hash drift blocking",
            "no selected-command execution",
        ],
    )
    require_terms(
        "docs/v77-large-workflow-queue-preflight-spec.md",
        [
            "status: implemented queue-packet preflight gate in",
            "`scripts/dwm_large_workflow_queue_preflight.py`",
            "`queue-preflight.json`",
            "`queue-preflight.md`",
            "`queue-preflight-ready`",
            "`queue-preflight-blocked`",
            "do not execute the queued command",
            "write, delete, network, deploy, secret, dependency, database",
            "unsupported command blocking",
            "actual command execution remains a separate gated step",
        ],
    )
    require_terms(
        "docs/v77-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_large_workflow_queue_preflight.py --manifest fixtures/v77/manifest.json --out out/large-workflow-queue-preflight/v77-final",
            "`suite_id`: `v77-large-workflow-queue-preflight`",
            "`fixture_count`: 6",
            "`required_passed`: 6",
            "`decision`: `keep`",
            "queued packet preflight",
            "unsafe risk blocking",
            "queue hash drift blocking",
            "unsupported command blocking",
            "no queued-command execution",
        ],
    )
    require_terms(
        "docs/v78-graph-timing-gate-spec.md",
        [
            "status: implemented graph timing gate in",
            "`scripts/dwm_graph_timing_gate.py`",
            "`graph-timing.json`",
            "`graph-timing.md`",
            "`process_progress`",
            "`local_benchmark_candidate`",
            "`public_benchmark_trend`",
            "does not draw a new graph",
            "process progress, not benchmark performance",
            "err_graph_timing_public_promotion_missing",
            "fake upward trend",
        ],
    )
    require_terms(
        "docs/v78-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_graph_timing_gate.py --manifest fixtures/v78/manifest.json --out out/graph-timing/v78-final",
            "`suite_id`: `v78-graph-timing-gate`",
            "`fixture_count`: 5",
            "`required_passed`: 5",
            "`decision`: `keep`",
            "process-only visibility",
            "public benchmark and upward-trend claims blocked",
            "does not draw a new graph",
        ],
    )
    require_terms(
        "docs/v79-readme-graph-visibility-spec.md",
        [
            "status: implemented readme graph visibility audit in",
            "`scripts/dwm_readme_graph_visibility.py`",
            "`readme-graph-visibility.json`",
            "`readme-graph-visibility.md`",
            "`progress-only-visible`",
            "not a public benchmark graph",
            "trend promotion is blocked",
            "public upward benchmark claims remain blocked",
            "does not generate a graph",
        ],
    )
    require_terms(
        "docs/v79-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_readme_graph_visibility.py --manifest fixtures/v79/manifest.json --out out/readme-graph-visibility/v79-final",
            "`suite_id`: `v79-readme-graph-visibility`",
            "`fixture_count`: 5",
            "`required_passed`: 5",
            "`decision`: `keep`",
            "readme graph surface aligned with v78",
            "not a public benchmark graph",
            "keeps public upward benchmark claims blocked",
        ],
    )
    require_terms(
        "docs/v80-continuation-boundary-spec.md",
        [
            "status: implemented continuation boundary gate in",
            "`scripts/dwm_continuation_boundary.py`",
            "`continuation-boundary.json`",
            "`continuation-boundary.md`",
            "source-only control-plane work through v83",
            "must stop before queued command execution",
            "v84 is the first human gate",
            "write, delete, network, deploy, secret",
        ],
    )
    require_terms(
        "docs/v80-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_continuation_boundary.py --manifest fixtures/v80/manifest.json --out out/continuation-boundaries/v80-final",
            "`suite_id`: `v80-continuation-boundary`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "source-only control-plane continuation through v83",
            "human gate before queued command execution",
        ],
    )
    require_terms(
        "docs/v81-multi-slice-batch-spec.md",
        [
            "status: implemented multi-slice batch planner in",
            "`scripts/dwm_multi_slice_batch.py`",
            "`multi-slice-batch.json`",
            "`multi-slice-batch.md`",
            "does not execute commands",
            "v84 human gate",
            "`continue_source_control_plane`",
            "`can_continue_without_human: true`",
        ],
    )
    require_terms(
        "docs/v81-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_multi_slice_batch.py --manifest fixtures/v81/manifest.json --out out/multi-slice-batches/v81-final",
            "`suite_id`: `v81-multi-slice-batch`",
            "`fixture_count`: 3",
            "`required_passed`: 3",
            "`decision`: `keep`",
            "plan-only multi-slice batch",
            "v84 as the first human gate",
        ],
    )
    require_terms(
        "docs/v82-execution-receipt-schema-spec.md",
        [
            "status: implemented execution receipt schema preflight in",
            "`scripts/dwm_execution_receipt_schema.py`",
            "`execution-receipt-schema.json`",
            "`sample-receipt.json`",
            "schema-only",
            "dry-run receipts must use `executed: false`",
            "actual execution remains behind the v84 human gate",
        ],
    )
    require_terms(
        "docs/v82-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_execution_receipt_schema.py --manifest fixtures/v82/manifest.json --out out/execution-receipt-schemas/v82-final",
            "`suite_id`: `v82-execution-receipt-schema`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "schema-only",
            "v84 human gate",
        ],
    )
    require_terms(
        "docs/v83-runner-receipt-dry-run-spec.md",
        [
            "status: implemented runner receipt dry-run gate in",
            "`scripts/dwm_runner_receipt_dry_run.py`",
            "`runner-receipt.json`",
            "`runner-receipt.md`",
            "`executed: false`",
            "does not execute commands",
            "actual execution remains behind the v84 human gate",
        ],
    )
    require_terms(
        "docs/v83-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_runner_receipt_dry_run.py --manifest fixtures/v83/manifest.json --out out/runner-receipt-dry-runs/v83-final",
            "`suite_id`: `v83-runner-receipt-dry-run`",
            "`fixture_count`: 3",
            "`required_passed`: 3",
            "`decision`: `keep`",
            "`executed: false`",
            "v84 remains the first human gate",
        ],
    )
    require_terms(
        "docs/v84-installed-surface-audit-spec.md",
        [
            "status: implemented installed surface audit gate in",
            "`scripts/dwm_installed_surface_audit.py`",
            "`installed-surface-audit.json`",
            "`installed-surface-audit.md`",
            "`repo_backed_active_surface`",
            "`installed_copy_synced`",
            "symlinked install surfaces",
            "stale copied install",
            "v84 is audit-only",
        ],
    )
    require_terms(
        "docs/v84-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_installed_surface_audit.py --manifest fixtures/v84/manifest.json --out out/installed-surface-audits/v84-final",
            "`suite_id`: `v84-installed-surface-audit`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "`decision`: `installed_copy_synced`",
            "resolves through a symlink to the repo `skill.md`",
            "does not claim automatic package update behavior",
        ],
    )
    require_terms(
        "docs/v85-workflow-activation-spec.md",
        [
            "status: implemented next workflow activation gate in",
            "`scripts/dwm_workflow_activation.py`",
            "`workflow-activation.json`",
            "`workflow-activation.md`",
            "`ready_for_next_workflow_design`",
            "`design_next_workflow`",
            "live execution remains behind a human gate",
        ],
    )
    require_terms(
        "docs/v85-decision.md",
        [
            "decision: keep",
            "python scripts/dwm_workflow_activation.py --manifest fixtures/v85/manifest.json --out out/workflow-activations/v85-final",
            "`suite_id`: `v85-workflow-activation`",
            "`fixture_count`: 4",
            "`required_passed`: 4",
            "`decision`: `keep`",
            "`decision`: `ready_for_next_workflow_design`",
            "`next_safe_action`: `design_next_workflow`",
            "does not claim autonomous execution",
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
            "`release_command_count`: `226`",
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
    steps = contract_steps_for_tier(args.tier)
    for label, callback, timeout_seconds in steps:
        run_contract_step(label, callback, timeout_seconds=timeout_seconds)
    print(f"contract {args.tier}: pass")


if __name__ == "__main__":
    main()
