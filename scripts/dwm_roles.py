#!/usr/bin/env python3
"""V22 role pack registry and contract checks."""

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

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402


TOOL = "dwm_roles.py"
SCHEMA_VERSION = "1.0"
ROLE_VERSION = "22.0.0"
ROLE_ROOT = ROOT / "out" / "roles"
REGISTRY_PATH = ROOT / "packaging" / "dwm-roles.json"
SENTINEL = ".dwm_roles-owned.json"
REQUIRED_ROLE_IDS = ["planner", "explorer", "worker", "reviewer", "verifier", "operator"]
REQUIRED_ROLE_KEYS = {
    "id",
    "purpose",
    "allowed_tools",
    "output_schema",
    "evidence_obligations",
    "trust_boundary",
}
RISKY_TOOLS = {"delete", "network", "secret", "production", "database", "dependency", "external_message", "history_rewrite"}


class RoleError(ValueError):
    """Structured V22 role-pack failure."""

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
        raise RoleError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RoleError(code, "path contains a symlink", path=current)


def resolve_role_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_ROLE_PATH_UNSAFE", message="role output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ROLE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RoleError("ERR_ROLE_PATH_UNSAFE", f"role output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise RoleError("ERR_ROLE_PATH_UNSAFE", "role output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_ROLE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, role_run_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise RoleError("ERR_ROLE_PATH_SYMLINK", "role output is a symlink", path=path)
        if not path.is_dir():
            raise RoleError("ERR_ROLE_PATH_UNSAFE", "role output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("role_run_id") != role_run_id:
            raise RoleError("ERR_ROLE_PATH_UNSAFE", "existing role output is not role-owned", path=path)
        shutil.rmtree(path)
    ROLE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "role_version": ROLE_VERSION,
            "role_run_id": role_run_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def validate_role(role: dict[str, Any]) -> None:
    if set(role) != REQUIRED_ROLE_KEYS:
        raise RoleError("ERR_ROLE_OUTPUT_SCHEMA_MISSING", "role contract keys are incomplete")
    role_id = role.get("id")
    if not isinstance(role_id, str) or role_id not in REQUIRED_ROLE_IDS:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", "unknown role id")
    if not isinstance(role.get("purpose"), str) or not role["purpose"]:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", f"role {role_id} purpose is required")
    allowed_tools = role.get("allowed_tools")
    if not isinstance(allowed_tools, list) or not allowed_tools or not all(isinstance(item, str) and item for item in allowed_tools):
        raise RoleError("ERR_ROLE_PERMISSION_ESCALATION", f"role {role_id} allowed_tools are invalid")
    if RISKY_TOOLS & set(allowed_tools):
        raise RoleError("ERR_ROLE_PERMISSION_ESCALATION", f"role {role_id} declares risky tools without a gate")
    if not isinstance(role.get("output_schema"), str) or not role["output_schema"].endswith("-v1"):
        raise RoleError("ERR_ROLE_OUTPUT_SCHEMA_MISSING", f"role {role_id} output schema is missing or unstable")
    obligations = role.get("evidence_obligations")
    if not isinstance(obligations, list) or len(obligations) < 3 or not all(isinstance(item, str) and item for item in obligations):
        raise RoleError("ERR_ROLE_OUTPUT_SCHEMA_MISSING", f"role {role_id} evidence obligations are incomplete")
    trust_boundary = role.get("trust_boundary")
    if not isinstance(trust_boundary, str) or not trust_boundary:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", f"role {role_id} trust boundary is required")
    if role_id == "reviewer" and ("repair" in allowed_tools or "repair its own findings" not in trust_boundary):
        raise RoleError("ERR_ROLE_REVIEWER_SELF_REPAIR", "reviewer must not repair its own findings")
    if role_id == "operator" and "bypass gates" not in trust_boundary:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", "operator trust boundary must prevent bypassing gates")


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = read_json(path)
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", "unsupported role registry schema", path=path)
    roles = registry.get("roles")
    if not isinstance(roles, list) or not roles:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", "registry roles must be a non-empty list", path=path)
    seen: list[str] = []
    for role in roles:
        if not isinstance(role, dict):
            raise RoleError("ERR_ROLE_REGISTRY_INVALID", "role entry must be an object", path=path)
        validate_role(role)
        seen.append(role["id"])
    if seen != REQUIRED_ROLE_IDS:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", "role ids must match the required order", path=path)
    return registry


def registry_summary() -> dict[str, Any]:
    registry = load_registry()
    roles = registry["roles"]
    return {
        "status": "valid",
        "schema_version": registry["schema_version"],
        "role_count": len(roles),
        "role_ids": [role["id"] for role in roles],
        "registry_hash": canonical_hash(registry),
    }


def role_contract(role_id: str) -> dict[str, Any]:
    registry = load_registry()
    roles = {role["id"]: role for role in registry["roles"]}
    role = roles.get(role_id)
    if role is None:
        raise RoleError("ERR_ROLE_REGISTRY_INVALID", f"unknown role: {role_id}")
    validate_role(role)
    return {
        "status": "valid",
        "role": role_id,
        "allowed_tools": role["allowed_tools"],
        "output_schema": role["output_schema"],
        "evidence_obligations": role["evidence_obligations"],
        "trust_boundary": role["trust_boundary"],
        "role_hash": canonical_hash(role),
    }


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "registry":
            status = registry_summary()
        elif kind == "role-contract":
            status = role_contract(fixture["role"])
        elif kind == "permission-escalation":
            broken = {
                "id": "worker",
                "purpose": "bad worker",
                "allowed_tools": ["read", "network"],
                "output_schema": "worker-result-v1",
                "evidence_obligations": ["files_touched", "commands_run", "verification_output"],
                "trust_boundary": "result is untrusted until reviewed and verified",
            }
            status = blocked_fixture_status(broken, fixture)
        elif kind == "missing-output-schema":
            broken = {
                "id": "planner",
                "purpose": "bad planner",
                "allowed_tools": ["read", "search"],
                "evidence_obligations": ["phase_plan", "risk_gate_map", "verification_plan"],
                "trust_boundary": "cannot mark execution complete",
            }
            status = blocked_fixture_status(broken, fixture)
        elif kind == "reviewer-self-repair":
            broken = {
                "id": "reviewer",
                "purpose": "bad reviewer",
                "allowed_tools": ["read", "search", "test", "repair"],
                "output_schema": "review-findings-v1",
                "evidence_obligations": ["findings", "regression_risks", "missing_tests"],
                "trust_boundary": "can repair its own findings",
            }
            status = blocked_fixture_status(broken, fixture)
        else:
            raise RoleError("ERR_ROLE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise RoleError("ERR_ROLE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_role_count = fixture.get("expected_role_count")
        if expected_role_count is not None and status.get("role_count") != expected_role_count:
            raise RoleError("ERR_ROLE_FIXTURE_FAILED", f"expected role_count {expected_role_count}, got {status.get('role_count')}")
        expected_role = fixture.get("expected_role")
        if expected_role is not None and status.get("role") != expected_role:
            raise RoleError("ERR_ROLE_FIXTURE_FAILED", f"expected role {expected_role}, got {status.get('role')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise RoleError("ERR_ROLE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except RoleError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def blocked_fixture_status(role: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_role(role)
    except RoleError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise RoleError("ERR_ROLE_FIXTURE_FAILED", "broken role unexpectedly validated")


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_role_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("role_run_id") != suite_id:
            raise RoleError("ERR_ROLE_PATH_UNSAFE", "existing role suite is not role-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "role_version": ROLE_VERSION,
            "role_run_id": suite_id,
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
        raise RoleError("ERR_ROLE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    ROLE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-role-self-test-", dir=ROLE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v22" / "manifest.json", Path(tmp) / "role-self-test")
    if summary["decision"] != "keep":
        raise RoleError("ERR_ROLE_FIXTURE_FAILED", "role self-test manifest did not keep")
    print("dwm_roles self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["registry", "role"])
    parser.add_argument("--role")
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise RoleError("ERR_ROLE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "registry":
            print(canonical_json_text(registry_summary()))
        elif args.command == "role":
            if not args.role:
                raise RoleError("ERR_ROLE_REGISTRY_INVALID", "role command requires --role")
            print(canonical_json_text(role_contract(args.role)))
        else:
            parser.error("expected --self-test, --manifest, registry, or role")
    except RoleError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
