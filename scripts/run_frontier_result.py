#!/usr/bin/env python3
"""Run one controlled fixture worker from a trusted V6.5 frontier dispatch."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, sha256_text, write_text_atomic  # noqa: E402
from dispatch_frontier import (  # noqa: E402
    SENTINEL as FRONTIER_DISPATCH_SENTINEL,
    V65_OUT_ROOT,
    FrontierDispatchError,
    read_sentinel as read_frontier_dispatch_sentinel,
    resume_frontier_dispatch,
    start_frontier_dispatch,
)
from ingest_worker_review import V6_OUT_ROOT  # noqa: E402


TOOL = "run_frontier_result.py"
SCHEMA_VERSION = "1.0"
FRONTIER_WORKER_VERSION = "0.1.0"
V7_OUT_ROOT = ROOT / "out" / "v7"
SENTINEL = ".run_frontier_result-owned.json"
FIXTURES = {
    "release-decision": {
        "argv": [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "Path('release-decision.md').write_text("
                "'# Release Decision\\n\\n"
                "Decision: keep\\n\\n"
                "## Evidence\\n\\n"
                "- V6 frontier selected release_decision\\n"
                "- V6.5 dispatch prepared without execution\\n"
                "- Controlled V7 fixture produced this decision artifact\\n\\n"
                "## Next Workflow\\n\\n"
                "Review release-decision.md before runtime ingestion.\\n'"
                ")"
            ),
        ],
        "expected_exit_code": 0,
        "expected_outputs": ["release-decision.md"],
        "phase_id": "release_decision",
    }
}


class FrontierWorkerError(ValueError):
    """Structured V7 frontier-worker failure."""

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
        raise FrontierWorkerError(code, message, path=path)


def check_components_not_symlink(path: Path, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise FrontierWorkerError(code, "path contains a symlink", path=current)


def resolve_under_out(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, "ERR_FRONTIER_WORKER_OUTSIDE_REPO", f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = root.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", f"{label} path must name a run directory", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", f"{label} path must resolve under {out_root}", path=value) from exc
    check_components_not_symlink(candidate, "ERR_FRONTIER_WORKER_DIR_SYMLINK")
    return resolved


def resolve_dispatch(value: str | Path) -> Path:
    return resolve_under_out(value, V65_OUT_ROOT, label="V6.5 dispatch")


def resolve_v7_out(value: str | Path) -> Path:
    return resolve_under_out(value, V7_OUT_ROOT, label="V7 output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, "ERR_FRONTIER_WORKER_OUTSIDE_REPO", "artifact path escapes owned directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", "artifact path escapes owned directory", path=target) from exc


def ensure_artifact_parent(root: Path, path: Path) -> None:
    ensure_contained(root, path)
    current = root.resolve(strict=False)
    for part in path.resolve(strict=False).relative_to(current).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise FrontierWorkerError("ERR_FRONTIER_WORKER_DIR_SYMLINK", "artifact parent is symlinked", path=current)
            if not current.is_dir():
                raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_leaf_not_symlink(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_LEAF_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", "refusing to overwrite non-file leaf", path=path)


def write_text(path: Path, text: str, *, root: Path) -> None:
    ensure_artifact_parent(root, path)
    ensure_leaf_not_symlink(path)
    write_text_atomic(path, text, root=root)


def write_json(path: Path, data: Any, *, root: Path) -> None:
    write_text(path, canonical_json_text(data), root=root)


def read_json_obj(path: Path, *, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FrontierWorkerError(code, f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrontierWorkerError(code, f"{label} is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise FrontierWorkerError(code, f"{label} root must be an object", path=path)
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


def sentinel_payload(run_id: str, dispatch_dir: Path) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "frontier_worker_version": FRONTIER_WORKER_VERSION,
        "run_id": run_id,
        "dispatch_path": rel(dispatch_dir),
        "created_at": now_utc(),
    }


def ensure_worker_dir(path: Path, run_id: str, dispatch_dir: Path) -> None:
    path = resolve_v7_out(path)
    if path.exists():
        if path.is_symlink():
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_DIR_SYMLINK", "V7 output directory is a symlink", path=path)
        if not path.is_dir():
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", "V7 output exists and is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None:
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "existing V7 output is not owned", path=path)
        expected = sentinel_payload(run_id, dispatch_dir)
        expected["created_at"] = sentinel.get("created_at")
        if sentinel != expected:
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "V7 output sentinel does not match this dispatch", path=path)
    path.mkdir(parents=True, exist_ok=True)
    if read_sentinel(path) is None:
        write_json(path / SENTINEL, sentinel_payload(run_id, dispatch_dir), root=path)


def trusted_dispatch_context(dispatch_dir: Path) -> dict[str, Any]:
    dispatch_dir = resolve_dispatch(dispatch_dir)
    if read_frontier_dispatch_sentinel(dispatch_dir, FRONTIER_DISPATCH_SENTINEL) is None:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", "dispatch is missing ownership sentinel", path=dispatch_dir / FRONTIER_DISPATCH_SENTINEL)
    try:
        resumed = resume_frontier_dispatch(dispatch_dir)
    except FrontierDispatchError as exc:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", exc.message, path=exc.path) from exc
    if resumed["status"]["status"] != "prepared" or resumed["status"]["resume_state"] != "resumable":
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", "dispatch resume is not prepared", path=dispatch_dir / "status.json")
    dispatch = read_json_obj(dispatch_dir / "dispatch.json", code="ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", label="dispatch.json")
    packet = read_json_obj(dispatch_dir / "packet.json", code="ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", label="packet.json")
    prompt_path = dispatch_dir / "prompt.md"
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", "prompt.md is missing or symlinked", path=prompt_path)
    prompt = prompt_path.read_text()
    hashes = read_json_obj(dispatch_dir / "hashes.json", code="ERR_FRONTIER_WORKER_UNTRUSTED_DISPATCH", label="hashes.json")
    return {"dispatch_dir": dispatch_dir, "dispatch": dispatch, "packet": packet, "prompt": prompt, "hashes": hashes}


def run_process(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def build_result(context: dict[str, Any], fixture_id: str, process: subprocess.CompletedProcess[str], produced_outputs: list[str]) -> dict[str, Any]:
    dispatch = context["dispatch"]
    fixture = FIXTURES[fixture_id]
    return {
        "schema_version": SCHEMA_VERSION,
        "frontier_worker_version": FRONTIER_WORKER_VERSION,
        "result_id": "0000",
        "fixture_id": fixture_id,
        "status": "executed" if process.returncode == fixture["expected_exit_code"] else "failed",
        "dispatch_id": dispatch.get("dispatch_id"),
        "packet_id": dispatch.get("packet_id"),
        "phase_id": dispatch.get("phase_id"),
        "worker_ids": dispatch.get("worker_ids", []),
        "expected_outputs": fixture["expected_outputs"],
        "produced_outputs": produced_outputs,
        "exit_code": process.returncode,
        "expected_exit_code": fixture["expected_exit_code"],
        "stdout_path": "stdout.txt",
        "stderr_path": "stderr.txt",
        "work_dir": "work",
        "created_at": now_utc(),
    }


def produced_output_hashes(out_dir: Path, outputs: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for output in outputs:
        relative = Path(output)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_OUTSIDE_REPO", "produced output path escapes work dir", path=relative)
        path = out_dir / "work" / relative
        if not path.is_file() or path.is_symlink():
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "produced output is missing or symlinked", path=path)
        hashes[f"output:{output}"] = sha256_text(path.read_text())
    return hashes


def build_hashes(context: dict[str, Any], result: dict[str, Any], stdout: str, stderr: str, output_hashes: dict[str, str]) -> dict[str, str]:
    return {
        "dispatch_hash": canonical_hash(context["dispatch"]),
        "packet_hash": canonical_hash(context["packet"]),
        "prompt_hash": sha256_text(context["prompt"]),
        "dispatch_hashes_hash": canonical_hash(context["hashes"]),
        "result_hash": canonical_hash(result),
        "stdout_hash": sha256_text(stdout),
        "stderr_hash": sha256_text(stderr),
        **output_hashes,
    }


def build_status(
    run_id: str,
    *,
    result: dict[str, Any] | None,
    hashes: dict[str, str] | None,
    status: str,
    resume_state: str,
    invalidators: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "frontier_worker_version": FRONTIER_WORKER_VERSION,
        "run_id": run_id,
        "status": status,
        "resume_state": resume_state,
        "result_path": "result.json" if result else None,
        "packet_id": result.get("packet_id") if result else None,
        "phase_id": result.get("phase_id") if result else None,
        "produced_outputs": result.get("produced_outputs", []) if result else [],
        "invalidators": invalidators or [],
        "snapshots": hashes or {},
        "checked_at": now_utc(),
    }


def render_resume(status: dict[str, Any]) -> str:
    lines = [
        "# V7 Frontier Worker Result Resume",
        "",
        f"Run: `{status['run_id']}`",
        f"Status: `{status['status']}`",
        f"Resume state: `{status['resume_state']}`",
        f"Packet: `{status.get('packet_id')}`",
        f"Phase: `{status.get('phase_id')}`",
        "",
        "## Produced Outputs",
    ]
    for output in status.get("produced_outputs", []):
        lines.append(f"- `{output}`")
    if status.get("invalidators"):
        lines.extend(["", "## Invalidators"])
        for item in status["invalidators"]:
            lines.append(f"- `{item.get('code')}` {item.get('message')}")
    return "\n".join(lines) + "\n"


def write_status(out_dir: Path, status: dict[str, Any]) -> None:
    write_json(out_dir / "status.json", status, root=out_dir)
    write_text(out_dir / "resume.md", render_resume(status), root=out_dir)


def write_error_status(out_dir: Path, run_id: str, dispatch_dir: Path, error: FrontierWorkerError) -> dict[str, Any]:
    ensure_worker_dir(out_dir, run_id, dispatch_dir)
    status = build_status(run_id, result=None, hashes=None, status="blocked", resume_state="invalid", invalidators=[error.to_record()])
    write_status(out_dir, status)
    return status


def validate_fixture(context: dict[str, Any], fixture_id: str) -> None:
    fixture = FIXTURES[fixture_id]
    dispatch = context["dispatch"]
    if dispatch.get("phase_id") != fixture["phase_id"]:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_FIXTURE_UNSUPPORTED", "fixture does not match dispatch phase")
    expected = dispatch.get("expected_outputs")
    if not isinstance(expected, list) or fixture["expected_outputs"][0] not in expected:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_FIXTURE_UNSUPPORTED", "dispatch does not expect release-decision.md")


def start_worker(dispatch_dir: Path, *, out_dir: Path | None = None, fixture_id: str = "release-decision") -> dict[str, Any]:
    dispatch_dir = resolve_dispatch(dispatch_dir)
    out_dir = resolve_v7_out(out_dir) if out_dir is not None else V7_OUT_ROOT / dispatch_dir.name
    run_id = out_dir.name
    try:
        if fixture_id not in FIXTURES:
            raise FrontierWorkerError("ERR_FRONTIER_WORKER_FIXTURE_UNSUPPORTED", "unsupported frontier worker fixture")
        context = trusted_dispatch_context(dispatch_dir)
        validate_fixture(context, fixture_id)
        ensure_worker_dir(out_dir, run_id, dispatch_dir)
        work_dir = out_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        fixture = FIXTURES[fixture_id]
        process = run_process(fixture["argv"], work_dir)
        write_text(out_dir / "stdout.txt", process.stdout, root=out_dir)
        write_text(out_dir / "stderr.txt", process.stderr, root=out_dir)
        produced = [output for output in fixture["expected_outputs"] if (work_dir / output).is_file()]
        result = build_result(context, fixture_id, process, produced)
        output_hashes = produced_output_hashes(out_dir, produced)
        hashes = build_hashes(context, result, process.stdout, process.stderr, output_hashes)
        invalidators = [] if result["status"] == "executed" else [{"code": "ERR_FRONTIER_WORKER_FIXTURE_FAILED", "message": "worker fixture exited unexpectedly"}]
        status = build_status(run_id, result=result, hashes=hashes, status=result["status"], resume_state="fresh", invalidators=invalidators)
    except FrontierWorkerError as exc:
        status = write_error_status(out_dir, run_id, dispatch_dir, exc)
        return {"status": status, "out_dir": out_dir}
    write_json(out_dir / "result.json", result, root=out_dir)
    write_json(out_dir / "hashes.json", hashes, root=out_dir)
    write_status(out_dir, status)
    return {"status": status, "out_dir": out_dir, "result": result}


def validate_worker_sentinel(run_dir: Path, run_id: str, dispatch_dir: Path) -> None:
    sentinel = read_sentinel(run_dir)
    if sentinel is None:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "worker output is missing ownership sentinel", path=run_dir / SENTINEL)
    expected = sentinel_payload(run_id, dispatch_dir)
    expected["created_at"] = sentinel.get("created_at")
    if sentinel != expected:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "worker output sentinel does not match run", path=run_dir / SENTINEL)


def resume_worker(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v7_out(run_dir)
    run_id = run_dir.name
    result = read_json_obj(run_dir / "result.json", code="ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", label="result.json")
    sentinel = read_sentinel(run_dir)
    if sentinel is None or not isinstance(sentinel.get("dispatch_path"), str):
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "sentinel is missing dispatch_path", path=run_dir / SENTINEL)
    dispatch_dir = resolve_dispatch(sentinel["dispatch_path"])
    validate_worker_sentinel(run_dir, run_id, dispatch_dir)
    context = trusted_dispatch_context(dispatch_dir)
    stdout_path = run_dir / str(result.get("stdout_path"))
    stderr_path = run_dir / str(result.get("stderr_path"))
    if not stdout_path.is_file() or stdout_path.is_symlink() or not stderr_path.is_file() or stderr_path.is_symlink():
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "stdout/stderr sidecars are missing or symlinked", path=run_dir)
    stdout = stdout_path.read_text()
    stderr = stderr_path.read_text()
    outputs = result.get("produced_outputs")
    if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "produced_outputs is malformed", path=run_dir / "result.json")
    expected_output_hashes = produced_output_hashes(run_dir, outputs)
    expected_hashes = build_hashes(context, result, stdout, stderr, expected_output_hashes)
    hashes = read_json_obj(run_dir / "hashes.json", code="ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", label="hashes.json")
    invalidators = []
    if hashes != expected_hashes:
        invalidators.append({"code": "ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "message": "hashes do not match current worker evidence"})
    status = build_status(
        run_id,
        result=result,
        hashes=expected_hashes,
        status=str(result.get("status")) if not invalidators else "invalid",
        resume_state="resumable" if not invalidators else "invalidated",
        invalidators=invalidators,
    )
    write_status(run_dir, status)
    return {"status": status, "out_dir": run_dir}


def reset_owned(path: Path) -> None:
    if not path.exists():
        return
    sentinel = read_sentinel(path)
    if sentinel is None or sentinel.get("tool") != TOOL:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "existing self-test output is not frontier-worker-owned", path=path)
    shutil.rmtree(path)


def reset_frontier_dispatch(path: Path) -> None:
    if not path.exists():
        return
    sentinel = read_frontier_dispatch_sentinel(path, FRONTIER_DISPATCH_SENTINEL)
    if sentinel is None or sentinel.get("tool") != "dispatch_frontier.py":
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARTIFACT_MALFORMED", "existing dispatch self-test output is not frontier-dispatch-owned", path=path)
    shutil.rmtree(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_SELF_TEST_FAILED", message)


def self_test() -> None:
    dispatch_dir = V65_OUT_ROOT / "frontier-result-self-test-dispatch"
    out_dir = V7_OUT_ROOT / "frontier-result-self-test"
    reset_frontier_dispatch(dispatch_dir)
    reset_owned(out_dir)
    prepared = start_frontier_dispatch(V6_OUT_ROOT / "v32-semantic-dogfood", out_dir=dispatch_dir)
    require(prepared["status"]["status"] == "prepared", "trusted V6 frontier should prepare dispatch")
    started = start_worker(dispatch_dir, out_dir=out_dir, fixture_id="release-decision")
    require(started["status"]["status"] == "executed", "trusted frontier dispatch should execute fixture")
    require((out_dir / "work" / "release-decision.md").is_file(), "release decision output should exist")
    resumed = resume_worker(out_dir)
    require(resumed["status"]["resume_state"] == "resumable", "clean frontier worker result should resume")
    (out_dir / "work" / "release-decision.md").write_text("tampered\n")
    tampered = resume_worker(out_dir)
    require(tampered["status"]["status"] == "invalid", "tampered frontier output should invalidate")
    print("run_frontier_result self-test: pass")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", help="trusted V6.5 dispatch directory under out/v6.5")
    parser.add_argument("--resume", help="V7 worker output directory under out/v7")
    parser.add_argument("--out", help="V7 output directory")
    parser.add_argument("--fixture", default="release-decision")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.dispatch:
            result = start_worker(Path(args.dispatch), out_dir=Path(args.out) if args.out else None, fixture_id=args.fixture)
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "executed" else 1
        if args.resume:
            result = resume_worker(Path(args.resume))
            print(canonical_json_text(result["status"]))
            return 0 if result["status"]["status"] == "executed" else 1
        raise FrontierWorkerError("ERR_FRONTIER_WORKER_ARGUMENTS", "expected --dispatch, --resume, or --self-test")
    except FrontierWorkerError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
