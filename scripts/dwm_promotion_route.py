#!/usr/bin/env python3
"""V101 route promotion evidence to dogfood acquisition or human review."""

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


TOOL = "dwm_promotion_route.py"
ROUTE_VERSION = "101.0.0"
ROUTE_ROOT = ROOT / "out" / "promotion-routes"
SENTINEL = ".dwm_promotion_route-owned.json"
DEFAULT_EVIDENCE = ROOT / "out" / "promotion-evidence" / "v100-canonical" / "promotion-evidence.json"
DEFAULT_TASK_ID = "failing-test-fix"


class PromotionRouteError(ValueError):
    """Structured V101 promotion route failure."""

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
        raise PromotionRouteError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PromotionRouteError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_PROMOTION_ROUTE_PATH_UNSAFE", message="promotion route output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ROUTE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_PATH_UNSAFE", f"promotion route output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_PATH_UNSAFE", "promotion route output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_PROMOTION_ROUTE_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_PROMOTION_ROUTE_INPUT_UNSAFE", message="promotion route input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_INPUT_UNSAFE", "promotion route input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_PROMOTION_ROUTE_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_INPUT_MISSING", "promotion route input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, route_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise PromotionRouteError("ERR_PROMOTION_ROUTE_PATH_SYMLINK", "promotion route output is a symlink", path=path)
        if not path.is_dir():
            raise PromotionRouteError("ERR_PROMOTION_ROUTE_PATH_UNSAFE", "promotion route output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("route_id") != route_id:
            raise PromotionRouteError("ERR_PROMOTION_ROUTE_PATH_UNSAFE", "existing promotion route output is not route-owned", path=path)
        shutil.rmtree(path)
    ROUTE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(path / SENTINEL, {"tool": TOOL, "route_version": ROUTE_VERSION, "route_id": route_id, "source_path": str(source), "created_at": now_utc()}, root=path)


def acquisition_command(route_id: str, task_id: str) -> str:
    return f"python scripts/dwm_dogfood_acquire.py acquire --task-id {task_id} --out out/dogfood-acquisitions/{route_id}-{task_id}"


def make_route(route_id: str, evidence: dict[str, Any], *, task_id: str = DEFAULT_TASK_ID, source_paths: dict[str, str] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if evidence.get("tool") != "dwm_promotion_evidence.py":
        blockers.append({"code": "ERR_PROMOTION_ROUTE_EVIDENCE_TOOL_INVALID", "message": "input was not produced by V100"})
    if evidence.get("decision") != "promotion_evidence_recorded":
        blockers.append({"code": "ERR_PROMOTION_ROUTE_EVIDENCE_NOT_RECORDED", "message": "promotion evidence is not recorded", "decision": evidence.get("decision")})
    policy = evidence.get("claim_policy") if isinstance(evidence.get("claim_policy"), dict) else {}
    if policy.get("promotion_evidence_is_public_benchmark") is not False:
        blockers.append({"code": "ERR_PROMOTION_ROUTE_OVERCLAIM", "message": "promotion evidence must not be public benchmark evidence"})
    if policy.get("allows_readme_public_graph_without_review") is not False:
        blockers.append({"code": "ERR_PROMOTION_ROUTE_REVIEW_POLICY_MISSING", "message": "README graph publication must require human review"})

    promotion_ready = evidence.get("promotion_ready_for_human_review") is True
    if blockers:
        decision = "blocked"
        route_status = "blocked"
        command = ""
        human_gate: dict[str, Any] | None = None
        next_step = "repair promotion evidence before routing"
    elif promotion_ready:
        decision = "human_gate_required"
        route_status = "readme-publication-review-required"
        command = ""
        human_gate = {
            "gate_id": "readme-benchmark-publication-review",
            "safe_default": "do not publish README benchmark graph",
            "required_review": ["promotion-evidence.json", "benchmark-readiness.json", "wave-receipt.json"],
        }
        next_step = "human review before README benchmark publication"
    else:
        decision = "route_ready"
        route_status = "continue-dogfood-evidence"
        command = acquisition_command(route_id, task_id)
        human_gate = None
        next_step = "run the planned dogfood acquisition command only after operator approval"

    return {
        "schema_version": ROUTE_VERSION,
        "tool": TOOL,
        "route_id": route_id,
        "decision": decision,
        "route_status": route_status,
        "selected_task_id": task_id if decision == "route_ready" else "",
        "command": command,
        "human_gate": human_gate,
        "blocked_by": blockers,
        "next_step": next_step,
        "public_benchmark_publish_allowed": False,
        "claim_policy": {
            "route_is_public_benchmark": False,
            "requires_human_review_for_readme_publication": True,
            "allows_execution": False,
        },
        "execution_policy": {"executes_commands": False, "creates_worktrees": False, "uses_network": False, "publishes_assets": False},
        "source_paths": source_paths or {},
        "source_hashes": {"promotion_evidence": canonical_hash(evidence)},
    }


def render_markdown(route: dict[str, Any]) -> str:
    lines = [
        "# Promotion Route",
        "",
        f"- Decision: `{route['decision']}`",
        f"- Route status: `{route['route_status']}`",
        f"- Public benchmark publish allowed: `{route['public_benchmark_publish_allowed']}`",
        f"- Next step: `{route['next_step']}`",
    ]
    if route.get("selected_task_id"):
        lines.append(f"- Selected task: `{route['selected_task_id']}`")
    if route.get("command"):
        lines.append(f"- Planned command: `{route['command']}`")
    if route.get("human_gate"):
        lines.append(f"- Human gate: `{route['human_gate']['gate_id']}`")
    lines.extend(["", "This route is source-only. It does not execute commands, publish assets, or approve README graph publication.", ""])
    return "\n".join(lines)


def write_route(out_dir: Path, route: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "promotion-route.json", route, root=out_dir)
    write_json_atomic(out_dir / "status.json", route, root=out_dir)
    write_text_atomic(out_dir / "promotion-route.md", render_markdown(route), root=out_dir)


def route_from_file(evidence_path: Path, out_dir: Path, *, task_id: str) -> dict[str, Any]:
    evidence_resolved = resolve_input(evidence_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=evidence_resolved)
    route = make_route(out_dir.name, read_json(evidence_resolved), task_id=task_id, source_paths={"promotion_evidence": rel(evidence_resolved)})
    write_route(out_dir, route)
    if route["decision"] == "blocked":
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_BLOCKED", "promotion route is blocked", path=out_dir)
    return route


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        route = make_route(
            fixture_id,
            fixture.get("evidence") if isinstance(fixture.get("evidence"), dict) else {},
            task_id=str(fixture.get("task_id", DEFAULT_TASK_ID)),
        )
        write_route(fixture_out, route)
        errors: list[str] = []
        if fixture.get("expected_decision") is not None and fixture["expected_decision"] != route["decision"]:
            errors.append(f"expected {fixture['expected_decision']}, got {route['decision']}")
        if fixture.get("expected_command_present") is not None and bool(route["command"]) != fixture["expected_command_present"]:
            errors.append(f"expected command present {fixture['expected_command_present']}, got {bool(route['command'])}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": route["decision"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": ROUTE_VERSION,
        "tool": TOOL,
        "suite_id": str(manifest.get("suite_id", "v101-promotion-route")),
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
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_FIXTURE_FAILED", "required promotion route fixture failed", path=manifest_path)
    return summary


def sample_evidence(*, decision: str = "promotion_evidence_recorded", promotion_ready: bool = False, overclaim: bool = False) -> dict[str, Any]:
    return {
        "tool": "dwm_promotion_evidence.py",
        "decision": decision,
        "promotion_ready_for_human_review": promotion_ready,
        "claim_policy": {
            "promotion_evidence_is_public_benchmark": overclaim,
            "allows_readme_public_graph_without_review": False,
        },
    }


def self_test() -> None:
    route = make_route("self-test", sample_evidence())
    if route["decision"] != "route_ready" or not route["command"]:
        raise ValueError("not-ready promotion evidence should route to dogfood acquisition")
    gate = make_route("self-test-gate", sample_evidence(promotion_ready=True))
    if gate["decision"] != "human_gate_required" or gate["command"]:
        raise ValueError("promotion-ready evidence should stop at a human gate")
    blocked = make_route("self-test-blocked", sample_evidence(decision="blocked"))
    if blocked["decision"] != "blocked":
        raise ValueError("blocked promotion evidence should block route")
    overclaim = make_route("self-test-overclaim", sample_evidence(overclaim=True))
    if overclaim["decision"] != "blocked":
        raise ValueError("overclaim evidence should block route")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    route = subparsers.add_parser("route")
    route.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    route.add_argument("--task-id", default=DEFAULT_TASK_ID)
    route.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("promotion route self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise PromotionRouteError("ERR_PROMOTION_ROUTE_OUT_REQUIRED", "--out is required with --manifest")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "route":
            route = route_from_file(args.evidence, args.out, task_id=args.task_id)
            print(json.dumps({"decision": route["decision"], "route_id": route["route_id"], "route_status": route["route_status"]}, sort_keys=True))
            return
        raise PromotionRouteError("ERR_PROMOTION_ROUTE_COMMAND_REQUIRED", "use --self-test, --manifest, or route")
    except PromotionRouteError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
