#!/usr/bin/env python3
"""Review one trusted V7 frontier result before runtime ingestion."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, sha256_text, write_text_atomic  # noqa: E402
from dispatch_frontier import SENTINEL as FRONTIER_DISPATCH_SENTINEL, V65_OUT_ROOT, start_frontier_dispatch  # noqa: E402
from ingest_worker_review import V6_OUT_ROOT  # noqa: E402
from run_frontier_result import (  # noqa: E402
    SENTINEL as V7_SENTINEL,
    V7_OUT_ROOT,
    FrontierWorkerError,
    read_sentinel as read_v7_sentinel,
    resolve_dispatch,
    resume_worker,
    start_worker,
)


TOOL = "review_frontier_result.py"
SCHEMA_VERSION = "1.0"
FRONTIER_REVIEW_VERSION = "0.1.0"
V75_OUT_ROOT = ROOT / "out" / "v7.5"
SENTINEL = ".review_frontier_result-owned.json"
APPROVED_PACKET_ID = "v6-frontier-0001-release_decision"
APPROVED_PHASE = "release_decision"
APPROVED_OUTPUT = "release-decision.md"


class FrontierReviewError(ValueError):
    """Structured V7.5 review failure."""

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


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise FrontierReviewError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise FrontierReviewError(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_FRONTIER_REVIEW_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", f"{label} path must name a run directory", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_FRONTIER_REVIEW_DIR_SYMLINK")
    return resolved


def resolve_v7_result(value: str | Path) -> Path:
    return resolve_under_out(value, V7_OUT_ROOT, label="V7 result")


def resolve_v75_out(value: str | Path) -> Path:
    return resolve_under_out(value, V75_OUT_ROOT, label="V7.5 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise FrontierReviewError("ERR_FRONTIER_REVIEW_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FrontierReviewError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrontierReviewError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise FrontierReviewError(code, f"{label} root must be an object", path=path)
    return data


def read_sentinel(path: Path, name: str = SENTINEL) -> dict[str, Any] | None:
    sentinel = path / name
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sentinel_payload(run_id: str, source_result: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "review_version": FRONTIER_REVIEW_VERSION,
        "run_id": run_id,
        "source_result_path": rel(source_result),
        "created_at": now_utc(),
    }


def ensure_review_dir(path: Path, run_id: str, source_result: Path) -> None:
    path = resolve_v75_out(path)
    if path.exists():
        if path.is_symlink():
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_DIR_SYMLINK", "V7.5 output directory is a symlink", path=path)
        if not path.is_dir():
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "V7.5 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "existing V7.5 output is not owned", path=path)
        expected = sentinel_payload(run_id, source_result)
        expected["created_at"] = sentinel.get("created_at")
        if sentinel != expected:
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "V7.5 output sentinel does not match this source", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, source_result), root=path)


def require_string_list(value: Any, *, code: str, message: str, path: Path) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FrontierReviewError(code, message, path=path)
    return value


def validate_output_path(relative: str, work_dir: Path) -> Path:
    path = Path(relative)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "produced output path escapes work dir", path=relative)
    output = work_dir / path
    try:
        output.resolve(strict=False).relative_to(work_dir.resolve(strict=False))
    except ValueError as exc:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_OUTSIDE_REPO", "produced output path escapes work dir", path=output) from exc
    return output


def validate_v7_hashes(result_dir: Path, result: dict[str, Any], hashes: dict[str, Any], stdout: str, stderr: str) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    produced_outputs = require_string_list(
        result.get("produced_outputs"),
        code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED",
        message="produced_outputs is malformed",
        path=result_dir / "result.json",
    )
    if hashes.get("result_hash") != canonical_hash(result):
        invalidators.append({"code": "ERR_FRONTIER_REVIEW_SOURCE_STALE", "message": "result hash does not match current result.json"})
    if hashes.get("stdout_hash") != sha256_text(stdout):
        invalidators.append({"code": "ERR_FRONTIER_REVIEW_SOURCE_STALE", "message": "stdout hash does not match current stdout.txt"})
    if hashes.get("stderr_hash") != sha256_text(stderr):
        invalidators.append({"code": "ERR_FRONTIER_REVIEW_SOURCE_STALE", "message": "stderr hash does not match current stderr.txt"})
    work_dir = result_dir / str(result.get("work_dir", "work"))
    for output in produced_outputs:
        output_path = validate_output_path(output, work_dir)
        if not output_path.is_file() or output_path.is_symlink():
            invalidators.append({"code": "ERR_FRONTIER_REVIEW_SOURCE_STALE", "message": f"produced output is missing or symlinked: {output}"})
            continue
        if hashes.get(f"output:{output}") != sha256_text(output_path.read_text()):
            invalidators.append({"code": "ERR_FRONTIER_REVIEW_SOURCE_STALE", "message": f"produced output hash does not match: {output}"})
    return invalidators


def trusted_source_context(result_dir: Path) -> dict[str, Any]:
    result_dir = resolve_v7_result(result_dir)
    if read_v7_sentinel(result_dir, V7_SENTINEL) is None:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_UNTRUSTED_RESULT", "V7 result is missing ownership sentinel", path=result_dir / V7_SENTINEL)
    try:
        resumed = resume_worker(result_dir)
    except FrontierWorkerError as exc:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_UNTRUSTED_RESULT", exc.message, path=exc.path) from exc
    if resumed["status"]["status"] != "executed" or resumed["status"]["resume_state"] != "resumable":
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_UNTRUSTED_RESULT", "V7 result is not executed and resumable", path=result_dir / "status.json")

    result = read_json_obj(result_dir / "result.json", code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", label="result.json")
    hashes = read_json_obj(result_dir / "hashes.json", code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", label="hashes.json")
    stdout_path = result_dir / str(result.get("stdout_path"))
    stderr_path = result_dir / str(result.get("stderr_path"))
    if not stdout_path.is_file() or stdout_path.is_symlink() or not stderr_path.is_file() or stderr_path.is_symlink():
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", "stdout/stderr sidecars are missing or symlinked", path=result_dir)
    stdout = stdout_path.read_text()
    stderr = stderr_path.read_text()
    invalidators = validate_v7_hashes(result_dir, result, hashes, stdout, stderr)
    if invalidators:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_SOURCE_STALE", "V7 source hashes do not match current evidence", path=result_dir / "hashes.json")

    sentinel = read_v7_sentinel(result_dir, V7_SENTINEL)
    dispatch_path = sentinel.get("dispatch_path") if sentinel else None
    if not isinstance(dispatch_path, str):
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", "V7 sentinel is missing dispatch_path", path=result_dir / V7_SENTINEL)
    try:
        dispatch_dir = resolve_dispatch(dispatch_path)
    except FrontierWorkerError as exc:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", exc.message, path=exc.path) from exc
    packet = read_json_obj(dispatch_dir / "packet.json", code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", label="dispatch packet.json")
    dispatch = read_json_obj(dispatch_dir / "dispatch.json", code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED", label="dispatch.json")
    return {
        "result_dir": result_dir,
        "result": result,
        "hashes": hashes,
        "stdout": stdout,
        "stderr": stderr,
        "dispatch_dir": dispatch_dir,
        "packet": packet,
        "dispatch": dispatch,
    }


def source_hashes(context: dict[str, Any]) -> dict[str, str]:
    result = context["result"]
    hashes = context["hashes"]
    output_hashes = {
        key: str(value)
        for key, value in hashes.items()
        if isinstance(key, str) and key.startswith("output:") and isinstance(value, str)
    }
    return {
        "source_result_hash": canonical_hash(result),
        "source_hashes_hash": canonical_hash(hashes),
        "source_stdout_hash": sha256_text(context["stdout"]),
        "source_stderr_hash": sha256_text(context["stderr"]),
        "source_packet_hash": canonical_hash(context["packet"]),
        "source_dispatch_hash": canonical_hash(context["dispatch"]),
        **output_hashes,
    }


def stop_conditions_block_runtime_advance(packet: dict[str, Any]) -> bool:
    stop_conditions = require_string_list(
        packet.get("stop_conditions"),
        code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED",
        message="packet stop_conditions is malformed",
        path=Path("packet.json"),
    )
    return any(
        "v7.5 frontier result review" in item.lower() and "runtime ingestion" in item.lower()
        for item in stop_conditions
    )


def output_text(context: dict[str, Any], output_name: str) -> str:
    result_dir = context["result_dir"]
    result = context["result"]
    work_dir = result_dir / str(result.get("work_dir", "work"))
    output_path = validate_output_path(output_name, work_dir)
    if not output_path.is_file() or output_path.is_symlink():
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_SOURCE_STALE", "release-decision.md is missing or symlinked", path=output_path)
    return output_path.read_text()


def classify_review(context: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    result = context["result"]
    packet = context["packet"]
    dispatch = context["dispatch"]
    findings: list[dict[str, Any]] = []
    approved_outputs: list[str] = []
    produced_outputs = require_string_list(
        result.get("produced_outputs"),
        code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED",
        message="produced_outputs is malformed",
        path=context["result_dir"] / "result.json",
    )
    expected_outputs = require_string_list(
        packet.get("expected_outputs"),
        code="ERR_FRONTIER_REVIEW_SOURCE_MALFORMED",
        message="packet expected_outputs is malformed",
        path=context["dispatch_dir"] / "packet.json",
    )

    if (
        result.get("phase_id") != APPROVED_PHASE
        or packet.get("phase_id") != APPROVED_PHASE
        or dispatch.get("phase_id") != APPROVED_PHASE
    ):
        findings.append({"code": "REVIEW_NEEDS_HUMAN_PHASE", "message": "phase is outside first-slice review scope"})
        return "needs-human", findings, approved_outputs
    if (
        result.get("packet_id") != APPROVED_PACKET_ID
        or packet.get("packet_id") != APPROVED_PACKET_ID
        or dispatch.get("packet_id") != APPROVED_PACKET_ID
    ):
        findings.append({"code": "REVIEW_NEEDS_HUMAN_PACKET", "message": "packet is outside first-slice dogfood review scope"})
        return "needs-human", findings, approved_outputs
    if result.get("packet_id") != packet.get("packet_id") or dispatch.get("packet_id") != packet.get("packet_id"):
        findings.append({"code": "REVIEW_NEEDS_HUMAN_PACKET", "message": "result, packet, and dispatch identifiers do not match first-slice scope"})
        return "needs-human", findings, approved_outputs
    if APPROVED_OUTPUT not in produced_outputs:
        findings.append({"code": "REVIEW_MISSING_OUTPUT", "message": "release-decision.md is not listed in produced_outputs"})
        return "request-changes", findings, approved_outputs
    if APPROVED_OUTPUT not in expected_outputs:
        findings.append({"code": "REVIEW_UNEXPECTED_OUTPUT", "message": "source packet does not expect release-decision.md"})
        return "request-changes", findings, approved_outputs
    if produced_outputs != [APPROVED_OUTPUT] or expected_outputs != [APPROVED_OUTPUT]:
        findings.append({"code": "REVIEW_NEEDS_HUMAN_OUTPUT_SCHEMA", "message": "output schema is outside first-slice review scope"})
        return "needs-human", findings, approved_outputs
    text = output_text(context, APPROVED_OUTPUT)
    if not text.strip():
        findings.append({"code": "REVIEW_EMPTY_OUTPUT", "message": "release-decision.md is empty"})
        return "request-changes", findings, approved_outputs
    if not stop_conditions_block_runtime_advance(packet) or not stop_conditions_block_runtime_advance(dispatch):
        findings.append({"code": "REVIEW_RUNTIME_ADVANCE_UNSAFE", "message": "source stop conditions do not require V7.5 frontier result review before runtime ingestion"})
        return "request-changes", findings, approved_outputs

    approved_outputs.append(APPROVED_OUTPUT)
    return "approve", findings, approved_outputs


def build_review(context: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    verdict, findings, approved_outputs = classify_review(context)
    result = context["result"]
    return {
        "schema_version": SCHEMA_VERSION,
        "review_version": FRONTIER_REVIEW_VERSION,
        "review_id": "0000",
        "created_at": created_at or now_utc(),
        "verdict": verdict,
        "source_result_path": rel(context["result_dir"]),
        "source_packet_id": result.get("packet_id"),
        "source_phase_id": result.get("phase_id"),
        "source_hashes": source_hashes(context),
        "findings": findings,
        "approved_outputs": approved_outputs,
        "summary": summary_for_verdict(verdict),
    }


def summary_for_verdict(verdict: str) -> str:
    if verdict == "approve":
        return "Frontier result evidence satisfies the deterministic V7.5 first-slice review."
    if verdict == "request-changes":
        return "Frontier result evidence is valid but does not satisfy deterministic output checks."
    if verdict == "needs-human":
        return "Frontier result evidence is valid but outside the deterministic first-slice review scope."
    return "Frontier result evidence or review artifacts are invalid."


def render_review(review: dict[str, Any]) -> str:
    lines = [
        "# V7.5 Frontier Result Review",
        "",
        f"Review: `{review['review_id']}`",
        f"Verdict: `{review['verdict']}`",
        f"Source result: `{review['source_result_path']}`",
        f"Packet: `{review.get('source_packet_id')}`",
        f"Phase: `{review.get('source_phase_id')}`",
        "",
        "## Approved Outputs",
    ]
    approved = review.get("approved_outputs", [])
    if approved:
        for output in approved:
            lines.append(f"- `{output}`")
    else:
        lines.append("- None")
    if review.get("findings"):
        lines.extend(["", "## Findings"])
        for finding in review["findings"]:
            lines.append(f"- `{finding.get('code')}` {finding.get('message')}")
    lines.extend(["", "## Summary", "", str(review.get("summary", ""))])
    return "\n".join(lines) + "\n"


def build_hashes(context: dict[str, Any], review: dict[str, Any], markdown: str) -> dict[str, str]:
    return {
        "source_result_hash": canonical_hash(context["result"]),
        "source_hashes_hash": canonical_hash(context["hashes"]),
        "source_packet_hash": canonical_hash(context["packet"]),
        "review_hash": canonical_hash(review),
        "review_markdown_hash": sha256_text(markdown),
    }


def status_for_verdict(verdict: str) -> str:
    if verdict == "approve":
        return "review-approved"
    if verdict == "request-changes":
        return "changes-requested"
    if verdict == "needs-human":
        return "needs-human"
    return "invalid"


def build_status(
    run_id: str,
    *,
    review: dict[str, Any] | None,
    hashes: dict[str, str] | None,
    status: str,
    resume_state: str,
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "review_version": FRONTIER_REVIEW_VERSION,
        "run_id": run_id,
        "status": status,
        "resume_state": resume_state,
        "review_path": "review.json" if review else None,
        "latest_review_id": review.get("review_id") if review else None,
        "source_result_path": review.get("source_result_path") if review else None,
        "packet_id": review.get("source_packet_id") if review else None,
        "phase_id": review.get("source_phase_id") if review else None,
        "approved_outputs": review.get("approved_outputs", []) if review else [],
        "invalidators": invalidators or [],
        "snapshots": hashes or {},
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V7.5 Frontier Result Review Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        f"Packet: `{status.get('packet_id')}`",
        f"Phase: `{status.get('phase_id')}`",
        "",
        "## Approved Outputs",
    ]
    outputs = status.get("approved_outputs", [])
    if outputs:
        for output in outputs:
            lines.append(f"- `{output}`")
    else:
        lines.append("- None")
    if status.get("invalidators"):
        lines.extend(["", "## Invalidators"])
        for item in status["invalidators"]:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    return "\n".join(lines) + "\n"


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json(out_dir / "status.json", status, root=out_dir)
    write_text(out_dir / "resume.md", render_resume(status), root=out_dir)


def write_error_status(out_dir: Path, run_id: str, source_result: Path, error: FrontierReviewError) -> dict[str, Any]:
    ensure_review_dir(out_dir, run_id, source_result)
    status = build_status(run_id, review=None, hashes=None, status="invalid", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def start_review(result_dir: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    result_dir = resolve_v7_result(result_dir)
    out_dir = resolve_v75_out(out_dir) if out_dir is not None else V75_OUT_ROOT / result_dir.name
    run_id = out_dir.name
    try:
        ensure_review_dir(out_dir, run_id, result_dir)
        context = trusted_source_context(result_dir)
        review = build_review(context)
        markdown = render_review(review)
        hashes = build_hashes(context, review, markdown)
        status = build_status(
            run_id,
            review=review,
            hashes=hashes,
            status=status_for_verdict(str(review["verdict"])),
            resume_state="fresh",
            invalidators=[],
        )
    except FrontierReviewError as exc:
        status = write_error_status(out_dir, run_id, result_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "review.json", review, root=out_dir)
    write_text(out_dir / "review.md", markdown, root=out_dir)
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "review": review}


def validate_review_sentinel(run_dir: Path, run_id: str, source_result: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "review output is missing ownership sentinel", path=run_dir / SENTINEL)
    expected = sentinel_payload(run_id, source_result)
    expected["created_at"] = sentinel.get("created_at")
    if sentinel != expected:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "review output sentinel does not match source", path=run_dir / SENTINEL)


def resume_review(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v75_out(run_dir)
    run_id = run_dir.name
    sentinel = read_sentinel(run_dir)
    if sentinel is None or not isinstance(sentinel.get("source_result_path"), str):
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "sentinel is missing source_result_path", path=run_dir / SENTINEL)
    source_result = resolve_v7_result(sentinel["source_result_path"])
    validate_review_sentinel(run_dir, run_id, source_result)
    try:
        existing_review = read_json_obj(run_dir / "review.json", code="ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", label="review.json")
        existing_markdown_path = run_dir / "review.md"
        if not existing_markdown_path.is_file() or existing_markdown_path.is_symlink():
            raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "review.md is missing or symlinked", path=existing_markdown_path)
        existing_markdown = existing_markdown_path.read_text()
        existing_hashes = read_json_obj(run_dir / "hashes.json", code="ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", label="hashes.json")
    except FrontierReviewError as exc:
        status = build_status(run_id, review=None, hashes=None, status="invalid", resume_state="invalidated", invalidators=[exc.to_record()])
        write_status(run_dir, status)
        return {"status": status, "out_dir": run_dir}

    invalidators: list[dict[str, Any]] = []
    review = existing_review
    hashes: dict[str, str] | None = None
    try:
        context = trusted_source_context(source_result)
        expected_review = build_review(context, created_at=str(existing_review.get("created_at")))
        expected_markdown = render_review(expected_review)
        expected_hashes = build_hashes(context, expected_review, expected_markdown)
        if existing_review != expected_review:
            invalidators.append({"code": "ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "message": "review.json does not match current source evidence"})
        if existing_markdown != expected_markdown:
            invalidators.append({"code": "ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "message": "review.md does not match review.json"})
        if existing_hashes != expected_hashes:
            invalidators.append({"code": "ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "message": "hashes.json does not match current review evidence"})
        review = expected_review
        hashes = expected_hashes
    except FrontierReviewError as exc:
        invalidators.append(exc.to_record())

    if invalidators:
        status = build_status(run_id, review=review, hashes=hashes, status="invalid", resume_state="invalidated", invalidators=invalidators)
    else:
        status = build_status(
            run_id,
            review=review,
            hashes=hashes,
            status=status_for_verdict(str(review["verdict"])),
            resume_state="resumable",
        )
    write_status(run_dir, status)
    return {"status": status, "out_dir": run_dir}


def reset_owned(path: Path, sentinel_name: str, tool: str) -> None:
    if not path.exists():
        return
    sentinel_path = path / sentinel_name
    if not sentinel_path.is_file() or sentinel_path.is_symlink():
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "existing self-test output is not owned", path=path)
    try:
        sentinel = json.loads(sentinel_path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", f"existing self-test sentinel is malformed: {exc}", path=sentinel_path) from exc
    if not isinstance(sentinel, dict) or sentinel.get("tool") != tool:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", "existing self-test output is not owned by expected tool", path=path)
    shutil.rmtree(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_SELF_TEST_FAILED", message)


def self_test() -> None:
    dispatch = V65_OUT_ROOT / "frontier-review-self-test-dispatch"
    source = V7_OUT_ROOT / "frontier-review-self-test-source"
    review_out = V75_OUT_ROOT / "frontier-review-self-test"
    unsupported_source = V7_OUT_ROOT / "frontier-review-self-test-unsupported-source"
    unsupported_review = V75_OUT_ROOT / "frontier-review-self-test-unsupported"
    reset_owned(dispatch, FRONTIER_DISPATCH_SENTINEL, "dispatch_frontier.py")
    reset_owned(source, V7_SENTINEL, "run_frontier_result.py")
    reset_owned(review_out, SENTINEL, TOOL)
    reset_owned(unsupported_source, V7_SENTINEL, "run_frontier_result.py")
    reset_owned(unsupported_review, SENTINEL, TOOL)

    started_dispatch = start_frontier_dispatch(V6_OUT_ROOT / "v32-semantic-dogfood", out_dir=dispatch)
    require(started_dispatch["status"]["status"] == "prepared", "trusted V6 frontier should prepare dispatch")
    started_source = start_worker(dispatch, out_dir=source, fixture_id="release-decision")
    require(started_source["status"]["status"] == "executed", "trusted V7 source should execute")
    started = start_review(source, out_dir=review_out)
    require(started["status"]["status"] == "review-approved", "trusted worker result should approve")
    trusted_context = trusted_source_context(source)
    phase_mismatch = copy.deepcopy(trusted_context)
    phase_mismatch["packet"]["phase_id"] = "future_phase"
    verdict, findings, approved_outputs = classify_review(phase_mismatch)
    require(verdict == "needs-human", "packet/result phase mismatch should require human review")
    require(not approved_outputs and findings[0]["code"] == "REVIEW_NEEDS_HUMAN_PHASE", "phase mismatch should not approve outputs")
    packet_mismatch = copy.deepcopy(trusted_context)
    packet_mismatch["result"]["packet_id"] = "v6-frontier-0002-release_decision"
    packet_mismatch["packet"]["packet_id"] = "v6-frontier-0002-release_decision"
    packet_mismatch["dispatch"]["packet_id"] = "v6-frontier-0002-release_decision"
    verdict, findings, approved_outputs = classify_review(packet_mismatch)
    require(verdict == "needs-human", "non-dogfood packet should require human review")
    require(not approved_outputs and findings[0]["code"] == "REVIEW_NEEDS_HUMAN_PACKET", "non-dogfood packet should not approve outputs")
    extra_result_output = copy.deepcopy(trusted_context)
    extra_result_output["result"]["produced_outputs"] = [APPROVED_OUTPUT, "extra.md"]
    verdict, findings, approved_outputs = classify_review(extra_result_output)
    require(verdict == "needs-human", "extra produced output should require human review")
    require(not approved_outputs and findings[0]["code"] == "REVIEW_NEEDS_HUMAN_OUTPUT_SCHEMA", "extra produced output should not approve")
    extra_packet_output = copy.deepcopy(trusted_context)
    extra_packet_output["packet"]["expected_outputs"] = [APPROVED_OUTPUT, "extra.md"]
    verdict, findings, approved_outputs = classify_review(extra_packet_output)
    require(verdict == "needs-human", "extra expected output should require human review")
    require(not approved_outputs and findings[0]["code"] == "REVIEW_NEEDS_HUMAN_OUTPUT_SCHEMA", "extra expected output should not approve")
    legacy_stop_condition = copy.deepcopy(trusted_context)
    legacy_stop_condition["packet"]["stop_conditions"] = [
        "route any worker result through V5.5 review before further runtime ingestion"
    ]
    verdict, findings, approved_outputs = classify_review(legacy_stop_condition)
    require(verdict == "request-changes", "legacy V5.5 stop condition should not auto-approve")
    require(not approved_outputs and findings[0]["code"] == "REVIEW_RUNTIME_ADVANCE_UNSAFE", "legacy stop condition should block approval")
    generic_stop_condition = copy.deepcopy(trusted_context)
    generic_stop_condition["packet"]["stop_conditions"] = [
        "route any frontier worker result through frontier result review before runtime ingestion"
    ]
    verdict, findings, approved_outputs = classify_review(generic_stop_condition)
    require(verdict == "request-changes", "generic frontier review stop condition should not auto-approve")
    require(not approved_outputs and findings[0]["code"] == "REVIEW_RUNTIME_ADVANCE_UNSAFE", "generic stop condition should block approval")
    resumed = resume_review(review_out)
    require(resumed["status"]["resume_state"] == "resumable", "clean review should resume")

    review = read_json_obj(review_out / "review.json", code="ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", label="review.json")
    review["verdict"] = "approve-but-tampered"
    write_json(review_out / "review.json", review, root=review_out)
    tampered_review = resume_review(review_out)
    require(tampered_review["status"]["status"] == "invalid", "tampered review should invalidate")

    reset_owned(review_out, SENTINEL, TOOL)
    start_review(source, out_dir=review_out)

    shutil.copytree(source, unsupported_source)
    unsupported_sentinel = read_json_obj(unsupported_source / V7_SENTINEL, code="ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", label=V7_SENTINEL)
    unsupported_sentinel["run_id"] = unsupported_source.name
    write_json(unsupported_source / V7_SENTINEL, unsupported_sentinel, root=unsupported_source)
    unsupported_result = read_json_obj(unsupported_source / "result.json", code="ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", label="result.json")
    unsupported_hashes = read_json_obj(unsupported_source / "hashes.json", code="ERR_FRONTIER_REVIEW_ARTIFACT_MALFORMED", label="hashes.json")
    unsupported_result["phase_id"] = "unsupported_phase"
    unsupported_hashes["result_hash"] = canonical_hash(unsupported_result)
    write_json(unsupported_source / "result.json", unsupported_result, root=unsupported_source)
    write_json(unsupported_source / "hashes.json", unsupported_hashes, root=unsupported_source)
    unsupported = start_review(unsupported_source, out_dir=unsupported_review)
    require(unsupported["status"]["status"] == "needs-human", "unsupported phase should require human review")

    (source / "work" / APPROVED_OUTPUT).write_text("tampered\n")
    tampered_source = resume_review(review_out)
    require(tampered_source["status"]["status"] == "invalid", "tampered source should invalidate")
    print("review_frontier_result self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", help="trusted V7 frontier result directory under out/v7")
    parser.add_argument("--resume", help="V7.5 review output directory under out/v7.5")
    parser.add_argument("--out", help="V7.5 output directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.result:
            result = start_review(Path(args.result), out_dir=Path(args.out) if args.out else None)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] in {"review-approved", "changes-requested", "needs-human"} else 1
        if args.resume:
            result = resume_review(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] in {"review-approved", "changes-requested", "needs-human"} else 1
        raise FrontierReviewError("ERR_FRONTIER_REVIEW_ARGUMENTS", "expected --result, --resume, or --self-test")
    except FrontierReviewError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
