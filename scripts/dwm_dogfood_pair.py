#!/usr/bin/env python3
"""V57 gated dogfood comparison pair."""

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
from dwm_dogfood_attempts import FORBIDDEN_CLAIM_TERMS, validate_metrics  # noqa: E402
from dwm_dogfood_measure import MEASURE_ROOT, measure  # noqa: E402


TOOL = "dwm_dogfood_pair.py"
SCHEMA_VERSION = "1.0"
PAIR_VERSION = "57.0.0"
PAIR_ROOT = ROOT / "out" / "dogfood-pairs"
SENTINEL = ".dwm_dogfood_pair-owned.json"


class DogfoodPairError(ValueError):
    """Structured V57 dogfood comparison pair failure."""

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
        raise DogfoodPairError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodPairError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PAIR_PATH_UNSAFE", message="dogfood pair output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PAIR_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_UNSAFE", f"dogfood pair output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_UNSAFE", "dogfood pair output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PAIR_PATH_SYMLINK")
    return resolved


def resolve_measure(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PAIR_MEASURE_INVALID", message="measurement path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = MEASURE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_MEASURE_INVALID", f"measurement must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_PAIR_PATH_SYMLINK")
    return resolved


def safe_repo_file(value: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_PAIR_EVIDENCE_MISSING", message="evidence path must not contain parent traversal")
    if raw.is_absolute():
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_EVIDENCE_MISSING", "evidence path must be repo-relative", path=value)
    path = ROOT / raw
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_EVIDENCE_MISSING", "evidence path must stay in repo", path=value) from exc
    check_components_not_symlink(path, code="ERR_DOGFOOD_PAIR_PATH_SYMLINK")
    if not path.is_file():
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_EVIDENCE_MISSING", "evidence file is missing", path=value)
    return path


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, pair_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_SYMLINK", "dogfood pair output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_UNSAFE", "dogfood pair output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("pair_id") != pair_id:
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_UNSAFE", "existing dogfood pair output is not pair-owned", path=path)
        shutil.rmtree(path)
    PAIR_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "pair_version": PAIR_VERSION,
            "pair_id": pair_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_measurement(path: Path) -> dict[str, Any]:
    data_path = path / "measurement.json"
    if not data_path.is_file() or data_path.is_symlink():
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_MEASURE_INVALID", "measurement.json is missing", path=path)
    data = read_json(data_path)
    if data.get("status") != "dogfood-measurement-recorded" or data.get("mode") != "dwm-controlled":
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_MEASURE_INVALID", "measurement must be a DWM-controlled recorded sample", path=data_path)
    return data


def validate_gate(gate: Any) -> dict[str, Any]:
    if not isinstance(gate, dict) or gate.get("approved") is not True:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_GATE_MISSING", "direct-codex receipt requires human approval gate")
    for key in ["approver", "approved_at", "scope"]:
        if not isinstance(gate.get(key), str) or not gate[key].strip():
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_GATE_MISSING", f"human approval gate is missing {key}")
    if "direct-codex" not in gate["scope"]:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_GATE_MISSING", "human approval scope must include direct-codex")
    return {"approver": gate["approver"], "approved_at": gate["approved_at"], "scope": gate["scope"]}


def validate_direct_receipt(receipt: dict[str, Any], measurement: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_RECEIPT_INVALID", "direct receipt must be an object")
    if receipt.get("mode") != "direct-codex":
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_RECEIPT_INVALID", "direct receipt mode must be direct-codex")
    if receipt.get("task_id") != measurement.get("task_id"):
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_TASK_MISMATCH", "direct receipt task id must match DWM measurement")
    claim_text = " ".join(str(receipt.get(key, "")) for key in ["summary", "claim", "notes"]).lower()
    if receipt.get("public_claim") is True or any(term in claim_text for term in FORBIDDEN_CLAIM_TERMS):
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_OVERCLAIM", "direct receipt includes unsupported public claim")
    evidence_path = receipt.get("evidence_path")
    if not isinstance(evidence_path, str) or not evidence_path:
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_EVIDENCE_MISSING", "direct receipt evidence_path is missing")
    evidence_file = safe_repo_file(evidence_path)
    return {
        "task_id": receipt["task_id"],
        "mode": "direct-codex",
        "status": "human-gated-measured",
        "metrics": validate_metrics(receipt.get("metrics"), attempt_id=f"{receipt['task_id']}/direct-codex"),
        "evidence_path": evidence_path,
        "evidence_hash": canonical_hash(evidence_file.read_text()),
        "summary": str(receipt.get("summary", "")),
        "human_gate": validate_gate(receipt.get("human_gate")),
    }


def render_pair_doc(pair: dict[str, Any]) -> str:
    direct = pair["direct_codex"]["metrics"]
    dwm = pair["dwm_controlled"]["metrics"]
    lines = [
        "# DWM Dogfood Comparison Pair",
        "",
        f"- pair: `{pair['pair_id']}`",
        f"- task: `{pair['task_id']}`",
        f"- decision: `{pair['decision']}`",
        "- claim policy: local pair evidence only; not a public benchmark trend",
        "",
        "| Mode | Verification | Elapsed seconds | Interruptions |",
        "| --- | --- | --- | --- |",
        f"| `dwm-controlled` | `{dwm['verification_passed']}` | `{dwm['elapsed_seconds']}` | `{dwm['interruptions']}` |",
        f"| `direct-codex` | `{direct['verification_passed']}` | `{direct['elapsed_seconds']}` | `{direct['interruptions']}` |",
        "",
    ]
    return "\n".join(lines)


def make_pair(measure_dir: Path, receipt_path: Path, out_dir: Path) -> dict[str, Any]:
    measure_dir = resolve_measure(measure_dir)
    out_dir = resolve_out(out_dir)
    pair_id = out_dir.name
    measurement = load_measurement(measure_dir)
    receipt = read_json(receipt_path)
    direct = validate_direct_receipt(receipt, measurement)
    prepare_out_dir(out_dir, pair_id, source=receipt_path)
    dwm = {
        "task_id": measurement["task_id"],
        "mode": "dwm-controlled",
        "status": "measured",
        "metrics": {
            "elapsed_seconds": measurement["elapsed_seconds"],
            "interruptions": 0,
            "verification_passed": measurement["verification_passed"],
            "command_count": 1,
        },
        "evidence_path": measurement["evidence_path"],
        "evidence_hash": measurement["source_hashes"]["evidence"],
    }
    pair = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "pair_version": PAIR_VERSION,
        "status": "dogfood-comparison-pair-recorded",
        "decision": "pair-ready-local-evidence",
        "pair_id": pair_id,
        "task_id": measurement["task_id"],
        "dwm_controlled": dwm,
        "direct_codex": direct,
        "public_graph_ready": False,
        "external_claim_policy": "local pair evidence only; not an external benchmark authority",
        "source_hashes": {
            "measurement": canonical_hash(measurement),
            "direct_receipt": canonical_hash(receipt),
            "dwm_evidence": dwm["evidence_hash"],
            "direct_evidence": direct["evidence_hash"],
        },
    }
    write_json_atomic(out_dir / "comparison-pair.json", pair, root=out_dir)
    write_json_atomic(out_dir / "pair-status.json", pair, root=out_dir)
    write_text_atomic(out_dir / "comparison-pair.md", render_pair_doc(pair), root=out_dir)
    return pair


def fixture_receipt(evidence_path: str, *, task_id: str = "release-contract-count-sync") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "mode": "direct-codex",
        "evidence_path": evidence_path,
        "metrics": {
            "elapsed_seconds": 58.0,
            "interruptions": 1,
            "verification_passed": True,
            "command_count": 4,
        },
        "summary": "human-gated direct Codex receipt fixture",
        "human_gate": {
            "approved": True,
            "approver": "fixture",
            "approved_at": "2026-06-17T00:00:00Z",
            "scope": "direct-codex receipt for local dogfood pair",
        },
    }


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        measure_dir = MEASURE_ROOT / f"{suite_dir.name}-{kind}-measure"
        measure(measure_dir)
        evidence = suite_dir / f"{kind}-direct-evidence.md"
        evidence.write_text("direct receipt fixture evidence\n")
        receipt = fixture_receipt(rel(evidence))
        if kind == "missing-gate":
            receipt.pop("human_gate")
        elif kind == "task-mismatch":
            receipt["task_id"] = "v44-candidate-review-gate"
        elif kind == "missing-evidence":
            receipt["evidence_path"] = "out/dogfood-pairs/missing-direct-evidence.md"
        elif kind == "overclaim":
            receipt["summary"] = "DWM is better than Codex on an external benchmark."
        else:
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
        receipt_path = suite_dir / f"{kind}-receipt.json"
        write_json_atomic(receipt_path, receipt, root=suite_dir)
        make_pair(measure_dir, receipt_path, suite_dir / kind)
    except DogfoodPairError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "comparison-pair":
            measure_dir = MEASURE_ROOT / f"{suite_dir.name}-{fixture_id}-measure"
            measure(measure_dir)
            evidence = suite_dir / "direct-evidence.md"
            evidence.write_text("direct receipt fixture evidence\n")
            receipt_path = suite_dir / "direct-receipt.json"
            write_json_atomic(receipt_path, fixture_receipt(rel(evidence)), root=suite_dir)
            status = make_pair(measure_dir, receipt_path, suite_dir / fixture_id)
        elif kind in {"missing-gate", "task-mismatch", "missing-evidence", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodPairError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("pair_id") != suite_id:
            raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_UNSAFE", "existing dogfood pair suite is not pair-owned", path=suite_dir)
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
        "source_hashes": {"manifest": canonical_hash(manifest)},
    }
    write_json_atomic(suite_dir / "summary.json", summary, root=suite_dir)
    if summary["decision"] != "keep":
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    PAIR_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-pair-self-test-", dir=PAIR_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v57" / "manifest.json", Path(tmp) / "dogfood-pair-self-test")
    if summary["decision"] != "keep":
        raise DogfoodPairError("ERR_DOGFOOD_PAIR_FIXTURE_FAILED", "dogfood pair self-test manifest did not keep")
    print("dwm_dogfood_pair self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["pair"])
    parser.add_argument("--direct-receipt")
    parser.add_argument("--dwm-measure")
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodPairError("ERR_DOGFOOD_PAIR_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "pair":
            if not args.out or not args.dwm_measure or not args.direct_receipt:
                raise DogfoodPairError("ERR_DOGFOOD_PAIR_RECEIPT_INVALID", "pair requires --dwm-measure, --direct-receipt, and --out")
            print(canonical_json_text(make_pair(Path(args.dwm_measure), Path(args.direct_receipt), Path(args.out))))
        else:
            parser.error("expected --self-test, --manifest, or pair")
    except DogfoodPairError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
