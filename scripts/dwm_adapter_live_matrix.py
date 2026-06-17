#!/usr/bin/env python3
"""V55 live adapter availability and auth-assumption matrix."""

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
from dwm_adapters import REGISTRY_PATH, load_registry  # noqa: E402


TOOL = "dwm_adapter_live_matrix.py"
SCHEMA_VERSION = "1.0"
LIVE_MATRIX_VERSION = "55.0.0"
LIVE_ROOT = ROOT / "out" / "adapter-live-matrix"
SENTINEL = ".dwm_adapter_live_matrix-owned.json"
DEFAULT_TARGETS = [
    {"id": "codex", "command": "codex", "version_args": ["--version"]},
    {"id": "claude", "command": "claude", "version_args": ["--version"]},
    {"id": "opencode", "command": "opencode", "version_args": ["--version"], "registry_status": "candidate-not-registered"},
]


class AdapterLiveMatrixError(ValueError):
    """Structured V55 adapter live matrix failure."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None, fixture_id: str | None = None) -> None:
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
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def reject_traversal(path: Path, *, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise AdapterLiveMatrixError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AdapterLiveMatrixError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", message="adapter live matrix output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = LIVE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", f"adapter live matrix output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", "adapter live matrix output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_ADAPTER_LIVE_MATRIX_PATH_SYMLINK")
    return resolved


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, matrix_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_SYMLINK", "adapter live matrix output is a symlink", path=path)
        if not path.is_dir():
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", "adapter live matrix output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("matrix_id") != matrix_id:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", "existing adapter live matrix output is not matrix-owned", path=path)
        shutil.rmtree(path)
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "live_matrix_version": LIVE_MATRIX_VERSION,
            "matrix_id": matrix_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def validate_command(value: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value) or "/" in value or "\\" in value:
        raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_UNSAFE_COMMAND", "adapter command must be a bare executable name", path=str(value))
    return value


def validate_targets(raw_targets: Any) -> list[dict[str, Any]]:
    if raw_targets is None:
        return [dict(target) for target in DEFAULT_TARGETS]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_TARGET_INVALID", "targets must be a non-empty list")
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in raw_targets:
        if not isinstance(target, dict):
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_TARGET_INVALID", "target must be an object")
        adapter_id = target.get("id")
        if not isinstance(adapter_id, str) or not adapter_id:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_TARGET_INVALID", "target id is missing")
        if adapter_id in seen:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_TARGET_INVALID", "target ids must be unique")
        seen.add(adapter_id)
        command = validate_command(str(target.get("command", adapter_id)))
        version_args = target.get("version_args", ["--version"])
        if not isinstance(version_args, list) or not all(isinstance(item, str) and item for item in version_args):
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_TARGET_INVALID", f"{adapter_id} version_args are invalid")
        targets.append(
            {
                "id": adapter_id,
                "command": command,
                "version_args": version_args,
                "registry_status": target.get("registry_status", "registry-expected"),
            }
        )
    return targets


def probe_target(target: dict[str, Any], adapters_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    adapter_id = target["id"]
    adapter = adapters_by_id.get(adapter_id)
    command = target["command"]
    executable = shutil.which(command)
    row: dict[str, Any] = {
        "id": adapter_id,
        "command": command,
        "registry_status": "registered" if adapter is not None else target.get("registry_status", "not-registered"),
        "support_level": adapter.get("support_level") if adapter else "not-registered",
        "auth_assumption": adapter.get("auth_assumption") if adapter else "not registered; requires future adapter spec",
        "isolation": adapter.get("isolation") if adapter else "not registered; no live execution allowed",
        "task_execution": "not-executed",
        "auth_probe": "not-executed-safe-default",
        "available": executable is not None,
        "executable": executable,
    }
    if executable is None:
        row.update(
            {
                "version_status": "unavailable",
                "decision": "blocked",
                "blocked_by": ["ERR_ADAPTER_LIVE_MATRIX_COMMAND_MISSING"],
            }
        )
        return row
    version_command = [command, *target["version_args"]]
    completed = subprocess.run(version_command, cwd=ROOT, check=False, capture_output=True, text=True, timeout=10)
    row.update(
        {
            "version_command": version_command,
            "returncode": completed.returncode,
            "version_output_hash": canonical_hash({"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}),
            "version_status": "captured" if completed.returncode == 0 else "failed",
            "decision": "available-for-gated-preflight" if completed.returncode == 0 and adapter is not None else "blocked",
            "blocked_by": [] if completed.returncode == 0 and adapter is not None else ["ERR_ADAPTER_LIVE_MATRIX_VERSION_FAILED" if completed.returncode != 0 else "ERR_ADAPTER_LIVE_MATRIX_NOT_REGISTERED"],
        }
    )
    return row


def render_matrix_doc(matrix: dict[str, Any]) -> str:
    lines = [
        "# DWM Adapter Live Matrix",
        "",
        f"- matrix: `{matrix['matrix_id']}`",
        f"- decision: `{matrix['decision']}`",
        "- live task execution: `false`",
        "- auth probe: version-only; token or secret checks are not executed",
        "",
        "| Adapter | Registered | Available | Version | Decision |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in matrix["adapters"]:
        lines.append(
            f"| `{row['id']}` | `{row['registry_status']}` | `{row['available']}` | `{row['version_status']}` | `{row['decision']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def build_matrix(out_dir: Path, *, targets: list[dict[str, Any]] | None = None, source: Path = REGISTRY_PATH) -> dict[str, Any]:
    out_dir = resolve_out(out_dir)
    matrix_id = out_dir.name
    registry = load_registry()
    adapters_by_id = {adapter["id"]: adapter for adapter in registry["adapters"]}
    normalized_targets = validate_targets(targets)
    prepare_out_dir(out_dir, matrix_id, source=source)
    rows = [probe_target(target, adapters_by_id) for target in normalized_targets]
    available_registered = [row for row in rows if row["decision"] == "available-for-gated-preflight"]
    matrix = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "live_matrix_version": LIVE_MATRIX_VERSION,
        "matrix_id": matrix_id,
        "status": "adapter-live-matrix-recorded",
        "decision": "ready-for-gated-preflight" if available_registered else "blocked",
        "adapter_count": len(rows),
        "available_registered_count": len(available_registered),
        "adapters": rows,
        "live_task_execution": False,
        "auth_secret_access": False,
        "safe_default": "do not run live adapter tasks until a human approves a gated preflight",
        "source_hashes": {
            "registry": canonical_hash(registry),
            "targets": canonical_hash(normalized_targets),
        },
    }
    write_json_atomic(out_dir / "adapter-live-matrix.json", matrix, root=out_dir)
    write_text_atomic(out_dir / "adapter-live-matrix.md", render_matrix_doc(matrix), root=out_dir)
    write_json_atomic(out_dir / "status.json", matrix, root=out_dir)
    return matrix


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "unsafe-command":
            build_matrix(suite_dir / f"{kind}-blocked", targets=[{"id": "codex", "command": "../codex"}], source=Path("fixture"))
        elif kind == "missing-command":
            target = {"id": "codex", "command": "__dwm_missing_adapter__"}
            status = build_matrix(suite_dir / f"{kind}-blocked", targets=[target], source=Path("fixture"))
            error = status["adapters"][0]["blocked_by"][0]
            if fixture.get("expected_error") != error:
                raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"expected {fixture.get('expected_error')}, got {error}")
            return {"status": "blocked", "error": {"code": error}}
        elif kind == "not-registered":
            status = build_matrix(suite_dir / f"{kind}-blocked", targets=[{"id": "opencode", "command": "python"}], source=Path("fixture"))
            error = status["adapters"][0]["blocked_by"][0]
            if fixture.get("expected_error") != error:
                raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"expected {fixture.get('expected_error')}, got {error}")
            return {"status": "blocked", "error": {"code": error}}
        else:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except AdapterLiveMatrixError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "live-matrix":
            status = build_matrix(
                suite_dir / fixture_id,
                targets=[{"id": "codex", "command": "python", "version_args": ["--version"]}],
                source=Path("fixture"),
            )
        elif kind in {"unsafe-command", "missing-command", "not-registered"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except AdapterLiveMatrixError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("matrix_id") != suite_id:
            raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", "existing adapter live matrix suite is not matrix-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    prepare_out_dir(suite_dir, suite_id, source=manifest_path)
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
        "source_hashes": {"manifest": canonical_hash(manifest), "registry": canonical_hash(load_registry())},
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-adapter-live-matrix-self-test-", dir=LIVE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v55" / "manifest.json", Path(tmp) / "adapter-live-matrix-self-test")
    if summary["decision"] != "keep":
        raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_FIXTURE_FAILED", "adapter live matrix self-test manifest did not keep")
    print("dwm_adapter_live_matrix self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["matrix"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--targets")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "matrix":
            if not args.out:
                raise AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_PATH_UNSAFE", "matrix requires --out")
            targets = read_json(Path(args.targets)).get("targets") if args.targets else None
            print(canonical_json_text(build_matrix(Path(args.out), targets=targets, source=Path(args.targets) if args.targets else REGISTRY_PATH)))
        else:
            parser.error("expected --self-test, --manifest, or matrix")
    except (AdapterLiveMatrixError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            error = AdapterLiveMatrixError("ERR_ADAPTER_LIVE_MATRIX_VERSION_FAILED", "adapter version command timed out")
            print(canonical_json_text(error.to_record()), file=sys.stderr)
        else:
            print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
