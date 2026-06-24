#!/usr/bin/env python3
"""Read-only evidence oracle for DWM artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_evidence_oracle.py"
ORACLE_VERSION = "92.0.0"
ORACLE_ROOT = ROOT / "out" / "evidence-oracles"
SENTINEL = ".dwm_evidence_oracle-owned.json"


class EvidenceOracleError(ValueError):
    """Structured V92 evidence oracle failure."""

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
        raise EvidenceOracleError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceOracleError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_EVIDENCE_ORACLE_PATH_UNSAFE", message="oracle output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ORACLE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_PATH_UNSAFE", f"oracle output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_PATH_UNSAFE", "oracle output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_EVIDENCE_ORACLE_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_EVIDENCE_ORACLE_INPUT_UNSAFE", message="oracle input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_INPUT_UNSAFE", "oracle input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_EVIDENCE_ORACLE_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_INPUT_MISSING", "oracle input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, oracle_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_PATH_SYMLINK", "oracle output is a symlink", path=path)
        if not path.is_dir():
            raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_PATH_UNSAFE", "oracle output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("oracle_id") != oracle_id:
            raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_PATH_UNSAFE", "existing oracle output is not oracle-owned", path=path)
        shutil.rmtree(path)
    ORACLE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "oracle_version": ORACLE_VERSION,
            "oracle_id": oracle_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".txt", ".svg"}:
        return "text"
    return "text"


def load_artifacts(artifact_specs: Any, *, fixture_id: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(artifact_specs, dict):
        return {}, [{"code": "ERR_EVIDENCE_ORACLE_ARTIFACTS_INVALID", "message": "artifacts must be an object", "fixture_id": fixture_id}]

    artifacts: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    for name, spec in sorted(artifact_specs.items()):
        artifact_name = str(name)
        if not isinstance(spec, dict):
            blockers.append({"code": "ERR_EVIDENCE_ORACLE_ARTIFACT_INVALID", "message": "artifact spec must be an object", "artifact": artifact_name})
            continue
        try:
            if "path" in spec:
                path = resolve_input(str(spec["path"]))
                if artifact_kind(path) == "json":
                    value = read_json(path)
                    kind = "json"
                else:
                    value = path.read_text()
                    kind = "text"
                artifacts[artifact_name] = {"kind": kind, "value": value, "source_path": rel(path), "source_hash": canonical_hash(value)}
            elif "data" in spec:
                artifacts[artifact_name] = {"kind": "json", "value": spec["data"], "source_path": None, "source_hash": canonical_hash(spec["data"])}
            elif "text" in spec:
                text = str(spec["text"])
                artifacts[artifact_name] = {"kind": "text", "value": text, "source_path": None, "source_hash": canonical_hash({"text": text})}
            else:
                blockers.append({"code": "ERR_EVIDENCE_ORACLE_ARTIFACT_SOURCE_MISSING", "message": "artifact needs path, data, or text", "artifact": artifact_name})
        except EvidenceOracleError as exc:
            record = exc.to_record()
            record["artifact"] = artifact_name
            blockers.append(record)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            blockers.append({"code": "ERR_EVIDENCE_ORACLE_ARTIFACT_READ_FAILED", "message": str(exc), "artifact": artifact_name})
    return artifacts, blockers


def get_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    if path == "":
        return True, current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False, None
            if 0 <= index < len(current):
                current = current[index]
                continue
        return False, None
    return True, current


def assertion_blocker(assertion: dict[str, Any], code: str, message: str, *, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": code,
        "message": message,
        "assertion": assertion.get("id") or assertion.get("type"),
        "artifact": assertion.get("artifact"),
        "path": assertion.get("path"),
    }
    if expected is not None:
        record["expected"] = expected
    if actual is not None:
        record["actual"] = actual
    return record


def evaluate_assertion(assertion: Any, artifacts: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(assertion, dict):
        return {"code": "ERR_EVIDENCE_ORACLE_ASSERTION_INVALID", "message": "assertion must be an object"}
    assertion_type = assertion.get("type")
    artifact_name = str(assertion.get("artifact", ""))
    artifact = artifacts.get(artifact_name)
    if artifact is None:
        return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_ARTIFACT_UNKNOWN", "assertion references an unknown artifact")

    if assertion_type == "text_contains":
        if artifact["kind"] != "text":
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_ARTIFACT_KIND", "text_contains requires a text artifact")
        needle = str(assertion.get("contains", ""))
        if needle not in str(artifact["value"]):
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_TEXT_MISSING", "required text is missing", expected=needle)
        return None

    if artifact["kind"] != "json":
        return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_ARTIFACT_KIND", "json assertion requires a json artifact")

    path = str(assertion.get("path", ""))
    exists, actual = get_path(artifact["value"], path)
    if assertion_type == "json_field_exists":
        if not exists:
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_JSON_PATH_MISSING", "json path is missing")
        return None
    if not exists:
        return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_JSON_PATH_MISSING", "json path is missing")

    if assertion_type == "json_equals":
        expected = assertion.get("equals")
        if actual != expected:
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_JSON_MISMATCH", "json value mismatch", actual=actual, expected=expected)
        return None
    if assertion_type == "json_empty":
        if actual not in ({}, [], "", None):
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_JSON_NOT_EMPTY", "json value is not empty", actual=actual)
        return None
    if assertion_type == "json_contains":
        expected = assertion.get("contains")
        if not isinstance(actual, list) or expected not in actual:
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_JSON_LIST_MISSING", "json list does not contain expected value", actual=actual, expected=expected)
        return None
    if assertion_type == "json_hash_equals":
        other_name = str(assertion.get("equals_hash_of", ""))
        other = artifacts.get(other_name)
        if other is None:
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_ARTIFACT_UNKNOWN", "hash assertion references an unknown artifact", expected=other_name)
        expected_hash = canonical_hash(other["value"])
        if actual != expected_hash:
            return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_HASH_MISMATCH", "json hash does not match referenced artifact", actual=actual, expected=expected_hash)
        return None
    return assertion_blocker(assertion, "ERR_EVIDENCE_ORACLE_ASSERTION_TYPE_UNKNOWN", "unknown assertion type")


def verify_claims(claims: dict[str, Any], *, oracle_id: str) -> dict[str, Any]:
    artifacts, blockers = load_artifacts(claims.get("artifacts"), fixture_id=oracle_id)
    blocked_artifacts = {str(blocker.get("artifact")) for blocker in blockers if blocker.get("artifact")}
    assertions = claims.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        blockers.append({"code": "ERR_EVIDENCE_ORACLE_ASSERTIONS_INVALID", "message": "assertions must be a non-empty list"})
        assertions = []
    for assertion in assertions:
        if isinstance(assertion, dict) and str(assertion.get("artifact", "")) in blocked_artifacts:
            continue
        blocker = evaluate_assertion(assertion, artifacts)
        if blocker is not None:
            blockers.append(blocker)

    artifact_records = [
        {
            "name": name,
            "kind": artifact["kind"],
            "source_path": artifact["source_path"],
            "source_hash": artifact["source_hash"],
        }
        for name, artifact in sorted(artifacts.items())
    ]
    return {
        "schema_version": ORACLE_VERSION,
        "tool": TOOL,
        "oracle_id": oracle_id,
        "decision": "evidence_verified" if not blockers else "blocked",
        "blocked_by": blockers,
        "assertion_count": len(assertions),
        "artifact_count": len(artifact_records),
        "artifacts": artifact_records,
        "execution_policy": {
            "executes_commands": False,
            "creates_worktrees": False,
            "uses_network": False,
            "reads_repo_artifacts_only": True,
        },
        "source_hashes": {
            "claims": canonical_hash(claims),
            "artifacts": canonical_hash({name: artifact["source_hash"] for name, artifact in sorted(artifacts.items())}),
        },
    }


def render_markdown(oracle: dict[str, Any]) -> str:
    lines = [
        "# Evidence Oracle",
        "",
        f"- Decision: `{oracle['decision']}`",
        f"- Assertions: `{oracle['assertion_count']}`",
        f"- Artifacts: `{oracle['artifact_count']}`",
        f"- Executes commands: `{oracle['execution_policy']['executes_commands']}`",
        "",
        "## Artifacts",
        "",
    ]
    for artifact in oracle["artifacts"]:
        source = artifact.get("source_path") or "inline"
        lines.append(f"- `{artifact['name']}` from `{source}`")
    lines.extend(["", "## Blockers", ""])
    if oracle["blocked_by"]:
        for blocker in oracle["blocked_by"]:
            lines.append(f"- `{blocker.get('code')}` `{blocker.get('artifact', '')}` `{blocker.get('path', '')}`")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_oracle(out_dir: Path, oracle: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "evidence-oracle.json", oracle, root=out_dir)
    write_json_atomic(out_dir / "status.json", oracle, root=out_dir)
    write_text_atomic(out_dir / "evidence-oracle.md", render_markdown(oracle), root=out_dir)


def verify_file(claims_path: Path, out_dir: Path) -> dict[str, Any]:
    claims_path = resolve_input(claims_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=claims_path)
    claims = read_json(claims_path)
    if not isinstance(claims, dict):
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_CLAIMS_INVALID", "claims file must be a JSON object", path=claims_path)
    oracle = verify_claims(claims, oracle_id=out_dir.name)
    oracle["source_paths"] = {"claims": rel(claims_path)}
    write_oracle(out_dir, oracle)
    if oracle["decision"] != "evidence_verified":
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_BLOCKED", "evidence oracle blocked", path=claims_path)
    return oracle


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest_path = resolve_input(manifest_path)
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures") if isinstance(manifest, dict) else None
    if not isinstance(fixtures, list):
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v92-evidence-oracle"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        oracle = verify_claims(fixture, oracle_id=fixture_id)
        write_oracle(fixture_out, oracle)
        expected_decision = fixture.get("expected_decision")
        expected_codes = fixture.get("expected_blocked_codes")
        errors: list[str] = []
        if expected_decision is not None and expected_decision != oracle["decision"]:
            errors.append(f"expected {expected_decision}, got {oracle['decision']}")
        if expected_codes is not None:
            actual_codes = [str(blocker.get("code")) for blocker in oracle["blocked_by"]]
            if list(expected_codes) != actual_codes:
                errors.append(f"expected blockers {expected_codes}, got {actual_codes}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": oracle["decision"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": ORACLE_VERSION,
        "tool": TOOL,
        "suite_id": suite_id,
        "fixture_count": len(records),
        "required_fixture_count": sum(1 for record in records if record["required"]),
        "required_passed": sum(1 for record in records if record["required"] and record["status"] == "pass"),
        "passed": sum(1 for record in records if record["status"] == "pass"),
        "failed": sum(1 for record in records if record["status"] != "pass"),
        "decision": "keep" if not failed_required else "kill",
        "fixtures": records,
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(out_dir / "summary.json", summary, root=out_dir)
    if failed_required:
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_FIXTURE_FAILED", "required evidence oracle fixture failed", path=manifest_path)
    return summary


def self_test() -> None:
    claims = {
        "artifacts": {
            "roadmap": {"data": {"decision": "roadmap_reconciled", "blocked_by": [], "policy": {"latest_version": "V92"}}},
            "activation": {"data": {"decision": "ready_for_next_workflow_design", "source_hashes": {"roadmap_reconciliation": canonical_hash({"decision": "roadmap_reconciled", "blocked_by": [], "policy": {"latest_version": "V92"}})}}},
            "note": {"text": "Decision: `ready_for_next_workflow_design`"},
        },
        "assertions": [
            {"type": "json_equals", "artifact": "roadmap", "path": "policy.latest_version", "equals": "V92"},
            {"type": "json_empty", "artifact": "roadmap", "path": "blocked_by"},
            {"type": "json_hash_equals", "artifact": "activation", "path": "source_hashes.roadmap_reconciliation", "equals_hash_of": "roadmap"},
            {"type": "text_contains", "artifact": "note", "contains": "Decision:"},
        ],
    }
    oracle = verify_claims(claims, oracle_id="self-test")
    if oracle["decision"] != "evidence_verified":
        raise ValueError("valid evidence claims should verify")
    failed = verify_claims(
        {
            "artifacts": {"roadmap": {"data": {"decision": "blocked"}}},
            "assertions": [{"type": "json_equals", "artifact": "roadmap", "path": "decision", "equals": "roadmap_reconciled"}],
        },
        oracle_id="self-test-failed",
    )
    if failed["decision"] != "blocked" or failed["blocked_by"][0]["code"] != "ERR_EVIDENCE_ORACLE_JSON_MISMATCH":
        raise ValueError("mismatched evidence claims should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--claims", type=Path, required=True)
    verify.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("evidence oracle self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "verify":
            oracle = verify_file(args.claims, args.out)
            print(json.dumps({"decision": oracle["decision"], "blocked_by": oracle["blocked_by"], "oracle_id": oracle["oracle_id"]}, sort_keys=True))
            return
        raise EvidenceOracleError("ERR_EVIDENCE_ORACLE_COMMAND_REQUIRED", "use --self-test, --manifest, or verify")
    except EvidenceOracleError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
