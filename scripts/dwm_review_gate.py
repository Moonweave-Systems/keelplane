#!/usr/bin/env python3
"""V20.5 independent release reviewer gate."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_review_gate.py"
SCHEMA_VERSION = "1.0"
REVIEW_GATE_VERSION = "20.5.0"
REVIEW_ROOT = ROOT / "out" / "release-review"
RELEASE_ROOT = ROOT / "out" / "release"
SENTINEL = ".dwm_review_gate-owned.json"
REQUIRED_GATES = {"compatibility", "security", "migration", "release_corpus"}


class ReviewGateError(ValueError):
    """Structured V20.5 review-gate failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | str | None = None,
        fixture_id: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None
        self.fixture_id = fixture_id

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
        if self.fixture_id is not None:
            record["fixture_id"] = self.fixture_id
        return record


def now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, *, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise ReviewGateError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReviewGateError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_REVIEW_GATE_PATH_UNSAFE", message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", f"{label} path must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", f"{label} path must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_REVIEW_GATE_PATH_SYMLINK")
    return resolved


def resolve_review_out(value: str | Path) -> Path:
    return resolve_under(value, REVIEW_ROOT, label="release review output")


def resolve_release_dir(value: str | Path) -> Path:
    return resolve_under(value, RELEASE_ROOT, label="release")


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, review_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReviewGateError("ERR_REVIEW_GATE_PATH_SYMLINK", "review output is a symlink", path=path)
        if not path.is_dir():
            raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", "review output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("review_id") != review_id:
            raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", "existing review output is not review-owned", path=path)
        shutil.rmtree(path)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "review_gate_version": REVIEW_GATE_VERSION,
            "review_id": review_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def read_release_status(release_dir: Path) -> dict[str, Any]:
    release_dir = resolve_release_dir(release_dir)
    path = release_dir / "release-status.json"
    if not path.is_file() or path.is_symlink():
        raise ReviewGateError("ERR_REVIEW_GATE_RELEASE_NOT_ACCEPTED", "release-status.json is missing", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewGateError("ERR_REVIEW_GATE_RELEASE_NOT_ACCEPTED", f"release-status.json is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise ReviewGateError("ERR_REVIEW_GATE_RELEASE_NOT_ACCEPTED", "release-status.json root must be an object", path=path)
    return data


def validate_release_status(status: dict[str, Any], *, path: Path | None = None) -> None:
    if status.get("status") != "accepted" or status.get("decision") != "release-candidate":
        raise ReviewGateError("ERR_REVIEW_GATE_RELEASE_NOT_ACCEPTED", "release status is not accepted", path=path)
    gates = status.get("gates")
    if not isinstance(gates, dict) or set(gates) != REQUIRED_GATES:
        raise ReviewGateError("ERR_REVIEW_GATE_MISSING_GATE", "release gates are missing or unexpected", path=path)
    for gate_name, gate in gates.items():
        if not isinstance(gate, dict) or gate.get("status") != "accepted":
            raise ReviewGateError("ERR_REVIEW_GATE_RELEASE_NOT_ACCEPTED", f"release gate {gate_name} is not accepted", path=path)
    if status.get("gate_hash") != canonical_hash(gates):
        raise ReviewGateError("ERR_REVIEW_GATE_STALE_RELEASE", "release gate hash does not match gates", path=path)


def render_review(review: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V20.5 Release Review",
            "",
            f"Decision: `{review['decision']}`",
            f"Release status: `{review['release_status']}`",
            f"Gate count: `{review['gate_count']}`",
            "",
            "The review approves release-candidate evidence only. It does not publish packages or execute live adapters.",
            "",
        ]
    )


def review_release(release_dir: Path, out_dir: Path) -> dict[str, Any]:
    release_dir = resolve_release_dir(release_dir)
    out_dir = resolve_review_out(out_dir)
    review_id = out_dir.name
    prepare_out_dir(out_dir, review_id, source=release_dir)
    status = read_release_status(release_dir)
    validate_release_status(status, path=release_dir / "release-status.json")
    review = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "review_gate_version": REVIEW_GATE_VERSION,
        "review_id": review_id,
        "created_at": now_utc(),
        "release_path": rel(release_dir),
        "release_status": status["status"],
        "release_decision": status["decision"],
        "release_hash": canonical_hash(status),
        "gate_hash": status["gate_hash"],
        "gate_count": len(status["gates"]),
        "decision": "approved",
        "independent_review_required": True,
    }
    review_status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "review_id": review_id,
        "status": "reviewed",
        "decision": "approved",
        "release_path": rel(release_dir),
    }
    write_json_atomic(out_dir / "review.json", review, root=out_dir)
    write_text_atomic(out_dir / "review.md", render_review(review), root=out_dir)
    write_json_atomic(out_dir / "status.json", review_status, root=out_dir)
    return review_status


def mutate_release_for_fixture(release_dir: Path, kind: str) -> None:
    path = release_dir / "release-status.json"
    data = json.loads(path.read_text())
    if kind == "stale-release":
        data["gate_hash"] = "0" * 64
    elif kind == "blocked-release":
        data["status"] = "blocked"
    elif kind == "missing-gate":
        data["gates"].pop("security", None)
    write_json_atomic(path, data, root=release_dir)


def write_fixture_release_status(release_dir: Path) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    gates = {
        "compatibility": {"status": "accepted", "policy": "docs/v20-compatibility-matrix.md"},
        "security": {"status": "accepted", "policy": "docs/v20-compatibility-matrix.md"},
        "migration": {"status": "accepted", "policy": "docs/v20-migration-rollback.md"},
        "release_corpus": {"status": "accepted", "required_path_count": 6, "commands": []},
    }
    status = {
        "tool": "dwm_release.py",
        "schema_version": SCHEMA_VERSION,
        "release_version": "20.0.0",
        "release_id": release_dir.name,
        "status": "accepted",
        "decision": "release-candidate",
        "gates": gates,
        "gate_hash": canonical_hash(gates),
    }
    write_json_atomic(release_dir / "release-status.json", status, root=release_dir)


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        release_dir = RELEASE_ROOT / f"v20.5-{suite_dir.name}-{fixture_id}"
        if release_dir.exists():
            shutil.rmtree(release_dir)
        write_fixture_release_status(release_dir)
        kind = fixture["kind"]
        if kind in {"stale-release", "blocked-release", "missing-gate"}:
            mutate_release_for_fixture(release_dir, kind)
        out_dir = suite_dir / fixture_id
        try:
            status = review_release(release_dir, out_dir)
        except ReviewGateError as exc:
            if fixture.get("expected_error") != exc.code:
                raise
            status = {"status": "blocked", "error": exc.to_record()}
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise ReviewGateError("ERR_REVIEW_GATE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise ReviewGateError("ERR_REVIEW_GATE_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise ReviewGateError("ERR_REVIEW_GATE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except ReviewGateError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_review_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("review_id") != suite_id:
            raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", "existing review suite is not review-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "review_gate_version": REVIEW_GATE_VERSION,
            "review_id": suite_id,
            "source_path": rel(manifest_path),
            "created_at": now_utc(),
        },
        root=suite_dir,
    )
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [run_fixture(fixture, suite_dir) for fixture in fixtures]
    passed = sum(1 for item in results if item["status"] == "pass")
    failures = [item["error"] for item in results if item["status"] == "fail"]
    required_passed = sum(1 for item in results if item["id"] in required_ids and item["status"] == "pass")
    required_failed = [item for item in results if item["id"] in required_ids and item["status"] == "fail"]
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": len(required_ids),
        "required_passed": required_passed,
        "passed": passed,
        "failed": len(failures),
        "skipped": 0,
        "decision": "keep" if not required_failed and required_ids <= {item["id"] for item in results} else "kill",
        "failures": failures,
        "fixtures": results,
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise ReviewGateError("ERR_REVIEW_GATE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-review-gate-self-test-", dir=REVIEW_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v20.5" / "manifest.json", Path(tmp) / "review-gate-self-test")
    if summary["decision"] != "keep":
        raise ReviewGateError("ERR_REVIEW_GATE_FIXTURE_FAILED", "review gate self-test manifest did not keep")
    print("dwm_review_gate self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["review"])
    parser.add_argument("--release")
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "review":
            if not args.release or not args.out:
                raise ReviewGateError("ERR_REVIEW_GATE_PATH_UNSAFE", "review requires --release and --out")
            print(canonical_json_text(review_release(Path(args.release), Path(args.out))))
        else:
            parser.error("expected --self-test, --manifest, or review")
    except ReviewGateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
