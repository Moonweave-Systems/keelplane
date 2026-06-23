#!/usr/bin/env python3
"""V100 promotion evidence ledger from wave receipt and readiness evidence."""

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


TOOL = "dwm_promotion_evidence.py"
EVIDENCE_VERSION = "100.0.0"
EVIDENCE_ROOT = ROOT / "out" / "promotion-evidence"
SENTINEL = ".dwm_promotion_evidence-owned.json"
DEFAULT_RECEIPT = ROOT / "out" / "wave-receipts" / "v99-canonical" / "wave-receipt.json"
DEFAULT_READINESS = ROOT / "out" / "benchmark-readiness" / "v97-canonical" / "benchmark-readiness.json"


class PromotionEvidenceError(ValueError):
    """Structured V100 promotion evidence failure."""

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
        raise PromotionEvidenceError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PromotionEvidenceError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_PROMOTION_EVIDENCE_PATH_UNSAFE", message="promotion evidence output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = EVIDENCE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_PATH_UNSAFE", f"promotion evidence output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_PATH_UNSAFE", "promotion evidence output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_PROMOTION_EVIDENCE_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_PROMOTION_EVIDENCE_INPUT_UNSAFE", message="promotion evidence input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_INPUT_UNSAFE", "promotion evidence input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_PROMOTION_EVIDENCE_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_INPUT_MISSING", "promotion evidence input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, evidence_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_PATH_SYMLINK", "promotion evidence output is a symlink", path=path)
        if not path.is_dir():
            raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_PATH_UNSAFE", "promotion evidence output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("evidence_id") != evidence_id:
            raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_PATH_UNSAFE", "existing promotion evidence output is not evidence-owned", path=path)
        shutil.rmtree(path)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {"tool": TOOL, "evidence_version": EVIDENCE_VERSION, "evidence_id": evidence_id, "source_path": str(source), "created_at": now_utc()},
        root=path,
    )


def make_evidence(evidence_id: str, receipt: dict[str, Any], readiness: dict[str, Any], *, source_paths: dict[str, str] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if receipt.get("tool") != "dwm_wave_receipt.py":
        blockers.append({"code": "ERR_PROMOTION_EVIDENCE_RECEIPT_TOOL_INVALID", "message": "receipt input was not produced by V99"})
    if receipt.get("decision") != "wave_receipt_ready":
        blockers.append({"code": "ERR_PROMOTION_EVIDENCE_RECEIPT_NOT_READY", "message": "wave receipt is not ready", "decision": receipt.get("decision")})
    if receipt.get("selected_wave") != "dogfood-evidence-wave":
        blockers.append({"code": "ERR_PROMOTION_EVIDENCE_WAVE_MISMATCH", "message": "receipt does not describe the dogfood evidence wave", "selected_wave": receipt.get("selected_wave")})
    receipt_policy = receipt.get("claim_policy") if isinstance(receipt.get("claim_policy"), dict) else {}
    if receipt_policy.get("wave_receipt_is_public_benchmark") is not False:
        blockers.append({"code": "ERR_PROMOTION_EVIDENCE_RECEIPT_OVERCLAIM", "message": "wave receipt must not be treated as a public benchmark"})
    if readiness.get("tool") != "dwm_benchmark_readiness.py":
        blockers.append({"code": "ERR_PROMOTION_EVIDENCE_READINESS_TOOL_INVALID", "message": "readiness input was not produced by V97"})
    if readiness.get("decision") != "benchmark_readiness_recorded":
        blockers.append({"code": "ERR_PROMOTION_EVIDENCE_READINESS_NOT_RECORDED", "message": "benchmark readiness is not recorded", "decision": readiness.get("decision")})

    readiness_axes = readiness.get("readiness_axes") if isinstance(readiness.get("readiness_axes"), dict) else {}
    public_axis_ready = readiness_axes.get("public_benchmark") is True
    readiness_public_allowed = readiness.get("public_benchmark_publish_allowed") is True
    promotion_ready = not blockers and public_axis_ready and readiness_public_allowed
    public_publish_allowed = False
    if not promotion_ready:
        blockers.append(
            {
                "code": "ERR_PROMOTION_EVIDENCE_PUBLIC_GRAPH_NOT_PROMOTABLE",
                "message": "public benchmark graph still lacks promotion evidence or human review",
                "public_axis_ready": public_axis_ready,
                "readiness_public_allowed": readiness_public_allowed,
            }
        )
    return {
        "schema_version": EVIDENCE_VERSION,
        "tool": TOOL,
        "evidence_id": evidence_id,
        "decision": "promotion_evidence_recorded" if not blockers or all(blocker["code"] == "ERR_PROMOTION_EVIDENCE_PUBLIC_GRAPH_NOT_PROMOTABLE" for blocker in blockers) else "blocked",
        "promotion_ready_for_human_review": promotion_ready,
        "public_benchmark_publish_allowed": public_publish_allowed,
        "selected_wave": receipt.get("selected_wave"),
        "readiness_score": readiness.get("readiness_score"),
        "readiness_axes": readiness_axes,
        "blocked_by": blockers,
        "next_step": "human review before README benchmark publication" if promotion_ready else "continue dogfood evidence acquisition before public graph promotion",
        "claim_policy": {
            "promotion_evidence_is_public_benchmark": False,
            "requires_human_review_for_readme_publication": True,
            "allows_readme_public_graph_without_review": False,
        },
        "execution_policy": {"executes_commands": False, "creates_worktrees": False, "uses_network": False, "publishes_assets": False},
        "source_paths": source_paths or {},
        "source_hashes": {"wave_receipt": canonical_hash(receipt), "benchmark_readiness": canonical_hash(readiness)},
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Promotion Evidence",
            "",
            f"- Decision: `{evidence['decision']}`",
            f"- Selected wave: `{evidence['selected_wave']}`",
            f"- Readiness score: `{evidence['readiness_score']}`",
            f"- Promotion ready for human review: `{evidence['promotion_ready_for_human_review']}`",
            f"- Public benchmark publish allowed: `{evidence['public_benchmark_publish_allowed']}`",
            f"- Next step: `{evidence['next_step']}`",
            "",
            "This ledger is source-only. It does not execute commands, publish assets, or create public benchmark claims.",
            "README graph publication remains blocked until promotion evidence passes and a human approves publication.",
            "",
        ]
    )


def write_evidence(out_dir: Path, evidence: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "promotion-evidence.json", evidence, root=out_dir)
    write_json_atomic(out_dir / "status.json", evidence, root=out_dir)
    write_text_atomic(out_dir / "promotion-evidence.md", render_markdown(evidence), root=out_dir)


def evidence_from_files(receipt_path: Path, readiness_path: Path, out_dir: Path) -> dict[str, Any]:
    receipt_resolved = resolve_input(receipt_path)
    readiness_resolved = resolve_input(readiness_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=receipt_resolved)
    evidence = make_evidence(
        out_dir.name,
        read_json(receipt_resolved),
        read_json(readiness_resolved),
        source_paths={"wave_receipt": rel(receipt_resolved), "benchmark_readiness": rel(readiness_resolved)},
    )
    write_evidence(out_dir, evidence)
    if evidence["decision"] == "blocked":
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_BLOCKED", "promotion evidence is blocked", path=out_dir)
    return evidence


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        evidence = make_evidence(
            fixture_id,
            fixture.get("receipt") if isinstance(fixture.get("receipt"), dict) else {},
            fixture.get("readiness") if isinstance(fixture.get("readiness"), dict) else {},
        )
        write_evidence(fixture_out, evidence)
        errors: list[str] = []
        if fixture.get("expected_decision") is not None and fixture["expected_decision"] != evidence["decision"]:
            errors.append(f"expected {fixture['expected_decision']}, got {evidence['decision']}")
        if fixture.get("expected_promotion_ready") is not None and fixture["expected_promotion_ready"] != evidence["promotion_ready_for_human_review"]:
            errors.append(f"expected promotion_ready {fixture['expected_promotion_ready']}, got {evidence['promotion_ready_for_human_review']}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": evidence["decision"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": EVIDENCE_VERSION,
        "tool": TOOL,
        "suite_id": str(manifest.get("suite_id", "v100-promotion-evidence")),
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
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_FIXTURE_FAILED", "required promotion evidence fixture failed", path=manifest_path)
    return summary


def sample_receipt(*, decision: str = "wave_receipt_ready", public_claim: bool = False) -> dict[str, Any]:
    return {
        "tool": "dwm_wave_receipt.py",
        "decision": decision,
        "selected_wave": "dogfood-evidence-wave",
        "claim_policy": {"wave_receipt_is_public_benchmark": public_claim},
    }


def sample_readiness(*, decision: str = "benchmark_readiness_recorded", public_ready: bool = False) -> dict[str, Any]:
    return {
        "tool": "dwm_benchmark_readiness.py",
        "decision": decision,
        "readiness_score": 70 if not public_ready else 100,
        "readiness_axes": {"process_progress": True, "operator_readiness": True, "public_benchmark": public_ready},
        "public_benchmark_publish_allowed": public_ready,
    }


def self_test() -> None:
    recorded = make_evidence("self-test", sample_receipt(), sample_readiness())
    if recorded["decision"] != "promotion_evidence_recorded" or recorded["promotion_ready_for_human_review"]:
        raise ValueError("non-public readiness should record evidence without promotion readiness")
    ready = make_evidence("self-test-ready", sample_receipt(), sample_readiness(public_ready=True))
    if ready["decision"] != "promotion_evidence_recorded" or not ready["promotion_ready_for_human_review"]:
        raise ValueError("public-ready evidence should be ready for human review")
    blocked = make_evidence("self-test-blocked", sample_receipt(decision="blocked"), sample_readiness())
    if blocked["decision"] != "blocked":
        raise ValueError("blocked receipt should block promotion evidence")
    overclaim = make_evidence("self-test-overclaim", sample_receipt(public_claim=True), sample_readiness(public_ready=True))
    if overclaim["decision"] != "blocked":
        raise ValueError("overclaim receipt should block promotion evidence")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    record = subparsers.add_parser("record")
    record.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    record.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    record.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("promotion evidence self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_OUT_REQUIRED", "--out is required with --manifest")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "record":
            evidence = evidence_from_files(args.receipt, args.readiness, args.out)
            print(json.dumps({"decision": evidence["decision"], "evidence_id": evidence["evidence_id"], "promotion_ready_for_human_review": evidence["promotion_ready_for_human_review"]}, sort_keys=True))
            return
        raise PromotionEvidenceError("ERR_PROMOTION_EVIDENCE_COMMAND_REQUIRED", "use --self-test, --manifest, or record")
    except PromotionEvidenceError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
