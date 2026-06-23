#!/usr/bin/env python3
"""V20 1.0 release hardening gate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_release.py"
SCHEMA_VERSION = "1.0"
RELEASE_VERSION = "20.0.0"
RELEASE_ROOT = ROOT / "out" / "release"
SENTINEL = ".dwm_release-owned.json"


class ReleaseError(ValueError):
    """Structured V20 release-gate failure."""

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
        raise ReleaseError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RELEASE_PATH_UNSAFE", message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", f"{label} path must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", f"{label} path must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_RELEASE_PATH_SYMLINK")
    return resolved


def resolve_release_out(value: str | Path) -> Path:
    return resolve_under(value, RELEASE_ROOT, label="release output")


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, release_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReleaseError("ERR_RELEASE_PATH_SYMLINK", "release output is a symlink", path=path)
        if not path.is_dir():
            raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", "release output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("release_id") != release_id:
            raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", "existing release output is not release-owned", path=path)
        shutil.rmtree(path)
    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "release_version": RELEASE_VERSION,
            "release_id": release_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def require_terms(path: str, terms: list[str]) -> None:
    text = (ROOT / path).read_text().lower()
    missing = [term.lower() for term in terms if term.lower() not in text]
    if missing:
        raise ReleaseError("ERR_RELEASE_POLICY_MISSING", f"{path} missing required terms: {missing}", path=path)


def compatibility_gate() -> dict[str, Any]:
    require_terms(
        "docs/v20-compatibility-matrix.md",
        [
            "V1 compiled packet layout",
            "V12 adapter command planner artifacts",
            "V19 adapter registry",
            "schema version `1.0`",
            "OMX remains optional",
            "Claude, Codex, and shell surfaces are portable CLI or adapter surfaces",
        ],
    )
    return {"status": "accepted", "policy": "docs/v20-compatibility-matrix.md"}


def security_gate() -> dict[str, Any]:
    require_terms(
        "docs/v20-compatibility-matrix.md",
        [
            "stale evidence",
            "untracked approval",
            "silent worktree mutation",
            "hidden backend state",
            "unbounded retry",
            "unchecked external action",
            "secret access",
            "production deploy",
            "dependency installation",
            "database migration",
            "history rewrite",
        ],
    )
    return {"status": "accepted", "policy": "docs/v20-compatibility-matrix.md"}


def migration_gate() -> dict[str, Any]:
    require_terms(
        "docs/v20-migration-rollback.md",
        [
            "V11 operator guidance artifacts",
            "V12 adapter command artifacts",
            "generated outputs are evidence, not source truth",
            "do not mutate the original",
            "Rollback means",
            "force push",
            "hard reset",
            "structured blocked status",
        ],
    )
    return {"status": "accepted", "policy": "docs/v20-migration-rollback.md"}


def release_corpus_gate() -> dict[str, Any]:
    commands = [
        [sys.executable, "scripts/check_contract.py", "--self-test"],
        [sys.executable, "scripts/dwm_adapters.py", "--self-test"],
        [sys.executable, "scripts/dwm_install.py", "--self-test"],
        [sys.executable, "scripts/dwm_hud.py", "--self-test"],
        [sys.executable, "scripts/dwm_release_candidate.py", "--self-test"],
        [sys.executable, "scripts/dwm_demo.py", "--self-test"],
    ]
    outputs = []
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, check=False, text=True, capture_output=True)
        outputs.append({"command": command, "returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()})
        if completed.returncode != 0:
            raise ReleaseError("ERR_RELEASE_CORPUS_FAILED", f"release corpus command failed: {' '.join(command)}")
    required_paths = [
        "docs/v12-to-v20-final-roadmap.md",
        "docs/v20-compatibility-matrix.md",
        "docs/v20-migration-rollback.md",
        "docs/v20-1.0-release-hardening-spec.md",
        "docs/v49-adapter-parity-matrix-spec.md",
        "docs/v50-release-candidate-cut-spec.md",
        "docs/v51-canonical-demo-spec.md",
        "packaging/dwm-package.json",
        "packaging/dwm-adapters.json",
    ]
    for path in required_paths:
        target = ROOT / path
        if not target.is_file() or target.is_symlink():
            raise ReleaseError("ERR_RELEASE_POLICY_MISSING", "required release path missing or symlinked", path=path)
    return {"status": "accepted", "commands": outputs, "required_path_count": len(required_paths)}


def omx_required_negative() -> dict[str, Any]:
    raise ReleaseError("ERR_RELEASE_OMX_REQUIRED", "OMX must remain optional for 1.0 acceptance")


def release_status(out_dir: Path) -> dict[str, Any]:
    out_dir = resolve_release_out(out_dir)
    release_id = out_dir.name
    prepare_out_dir(out_dir, release_id, source=ROOT / "fixtures" / "v20" / "manifest.json")
    gates = {
        "compatibility": compatibility_gate(),
        "security": security_gate(),
        "migration": migration_gate(),
        "release_corpus": release_corpus_gate(),
    }
    status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "release_version": RELEASE_VERSION,
        "release_id": release_id,
        "status": "accepted",
        "decision": "release-candidate",
        "gates": gates,
        "gate_hash": canonical_hash(gates),
    }
    write_json_atomic(out_dir / "release-status.json", status, root=out_dir)
    write_text_atomic(
        out_dir / "release.md",
        "\n".join(
            [
                "# V20 Release Candidate",
                "",
                f"Status: `{status['status']}`",
                f"Decision: `{status['decision']}`",
                "",
                "This is a release-candidate hardening gate, not a hosted distribution claim.",
                "",
            ]
        ),
        root=out_dir,
    )
    return status


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "compatibility":
            status = compatibility_gate()
        elif kind == "security":
            status = security_gate()
        elif kind == "migration":
            status = migration_gate()
        elif kind == "release-corpus":
            status = release_corpus_gate()
        elif kind == "omx-required-negative":
            try:
                status = omx_required_negative()
            except ReleaseError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
        else:
            raise ReleaseError("ERR_RELEASE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise ReleaseError("ERR_RELEASE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise ReleaseError("ERR_RELEASE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        fixture_dir = suite_dir / fixture_id
        fixture_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(fixture_dir / "status.json", status, root=suite_dir)
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except ReleaseError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_release_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("release_id") != suite_id:
            raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", "existing release suite is not release-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "release_version": RELEASE_VERSION,
            "release_id": suite_id,
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
        raise ReleaseError("ERR_RELEASE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-release-self-test-", dir=RELEASE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v20" / "manifest.json", Path(tmp) / "release-self-test")
    if summary["decision"] != "keep":
        raise ReleaseError("ERR_RELEASE_FIXTURE_FAILED", "release self-test manifest did not keep")
    print("dwm_release self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["status"])
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "status":
            if not args.out:
                raise ReleaseError("ERR_RELEASE_PATH_UNSAFE", "status requires --out")
            print(canonical_json_text(release_status(Path(args.out))))
        else:
            parser.error("expected --self-test, --manifest, or status")
    except ReleaseError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
