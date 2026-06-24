#!/usr/bin/env python3
"""V88 roadmap reconciliation audit for Depone."""

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


TOOL = "dwm_roadmap_reconciliation.py"
AUDIT_VERSION = "88.0.0"
AUDIT_ROOT = ROOT / "out" / "roadmap-reconciliations"
SENTINEL = ".dwm_roadmap_reconciliation-owned.json"
DEFAULT_SURFACES = {
    "docs/spec.md": ROOT / "docs" / "spec.md",
    "docs/automation-roadmap.md": ROOT / "docs" / "automation-roadmap.md",
    "docs/release-history.md": ROOT / "docs" / "release-history.md",
}


class RoadmapReconciliationError(ValueError):
    """Structured V88 roadmap reconciliation failure."""

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


def reject_traversal(path: Path, *, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise RoadmapReconciliationError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RoadmapReconciliationError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", message="reconciliation output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = AUDIT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", f"reconciliation output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", "reconciliation output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_ROADMAP_RECONCILIATION_PATH_SYMLINK")
    return resolved


def prepare_out_dir(path: Path, audit_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_SYMLINK", "reconciliation output is a symlink", path=path)
        if not path.is_dir():
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", "reconciliation output is not a directory", path=path)
        sentinel = path / SENTINEL
        if not sentinel.is_file() or sentinel.is_symlink():
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", "existing reconciliation output is not owned", path=path)
        try:
            data = json.loads(sentinel.read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", "reconciliation sentinel is invalid", path=sentinel) from exc
        if data.get("audit_id") != audit_id:
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_PATH_UNSAFE", "reconciliation sentinel belongs to a different id", path=sentinel)
        shutil.rmtree(path)
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "audit_version": AUDIT_VERSION,
            "audit_id": audit_id,
            "source_path": str(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def require_term(blockers: list[dict[str, Any]], surfaces: dict[str, str], path: str, term: str, *, code: str = "ERR_ROADMAP_RECONCILIATION_TERM_MISSING") -> None:
    if term.lower() not in surfaces.get(path, "").lower():
        blockers.append({"code": code, "path": path, "term": term, "message": "required roadmap reconciliation term is missing"})


def forbid_term(blockers: list[dict[str, Any]], surfaces: dict[str, str], path: str, term: str, *, code: str = "ERR_ROADMAP_RECONCILIATION_STALE_TERM") -> None:
    if term.lower() in surfaces.get(path, "").lower():
        blockers.append({"code": code, "path": path, "term": term, "message": "stale roadmap term is still present"})


def audit_surfaces(surfaces: dict[str, str]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    surface_records = [{"path": path, "content_hash": canonical_hash({"text": text})} for path, text in sorted(surfaces.items())]

    if first_line(surfaces.get("docs/spec.md", "")).lower() != "# depone / dwm core spec":
        blockers.append({"code": "ERR_ROADMAP_RECONCILIATION_SPEC_HEADING_STALE", "path": "docs/spec.md", "term": "# Depone / DWM Core Spec", "message": "spec heading does not reflect current product and engine boundary"})
    require_term(blockers, surfaces, "docs/spec.md", "Last updated: 2026-06-24")
    require_term(blockers, surfaces, "docs/spec.md", "V87 brand boundary audit implemented")
    require_term(blockers, surfaces, "docs/spec.md", "V88 roadmap reconciliation")
    require_term(blockers, surfaces, "docs/spec.md", "V89 command safety")
    require_term(blockers, surfaces, "docs/spec.md", "V90 activation v2")
    require_term(blockers, surfaces, "docs/spec.md", "V91 contract tiering")
    require_term(blockers, surfaces, "docs/spec.md", "V92 evidence oracle")
    require_term(blockers, surfaces, "docs/spec.md", "V93 workflow narrative")
    require_term(blockers, surfaces, "docs/spec.md", "V94 control deck score")
    require_term(blockers, surfaces, "docs/spec.md", "V95 score history")
    require_term(blockers, surfaces, "docs/spec.md", "V96 metric ladder, V97 benchmark readiness, V98 wave operator, V99 wave receipt, V100 promotion evidence, V101 promotion route, V102 deterministic live-proof recorder, V103 live-proof comparison schema, V104 product direction, V105 verify wedge, V106 multi-wave validation, V107 Agent Fabric compiler, V108 reference adapter fixture, V109 capture bridge, V110 report assurance, V111 operator view, V112 lifecycle smoke, V116 Agent Fabric smoke CLI, V117 Agent Fabric harness snapshot")

    if first_line(surfaces.get("docs/automation-roadmap.md", "")).lower() != "# depone automation roadmap":
        blockers.append({"code": "ERR_ROADMAP_RECONCILIATION_ROADMAP_HEADING_STALE", "path": "docs/automation-roadmap.md", "term": "# Depone Automation Roadmap", "message": "roadmap heading does not reflect current product brand"})
    forbid_term(blockers, surfaces, "docs/automation-roadmap.md", "Status: planned; not implemented")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V12-V20: Implemented Product Roadmap")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V52-V117: Product Evidence, Control Deck, And Agent Fabric Guardrails")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V88 roadmap reconciliation audit")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V89 command safety gate")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V90 activation v2")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V91 contract tiering")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V92 evidence oracle")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V93 workflow narrative")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V94 control deck score")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V95 score history")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V96 metric ladder")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V97 benchmark readiness")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V98 wave operator")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V99 wave receipt")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V100 promotion evidence")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V101 promotion route")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V102 deterministic live-proof recorder")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V103 live-proof comparison schema")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V104 product direction")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V105 verify wedge")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V106 multi-wave validation")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V107 Agent Fabric contracts and compiler")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V108 Agent Fabric reference adapter fixture")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V109 Agent Fabric capture bridge")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V110 Agent Fabric report assurance")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V111 Agent Fabric operator view")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V112 Agent Fabric lifecycle smoke")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V116 Agent Fabric smoke CLI")
    require_term(blockers, surfaces, "docs/automation-roadmap.md", "V117 Agent Fabric harness snapshot")

    if first_line(surfaces.get("docs/release-history.md", "")).lower() != "# depone release history":
        blockers.append({"code": "ERR_ROADMAP_RECONCILIATION_RELEASE_HEADING_STALE", "path": "docs/release-history.md", "term": "# Depone Release History", "message": "release history heading is stale"})
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v87-brand-boundary-audit-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v88-roadmap-reconciliation-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v89-command-safety-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v90-workflow-activation-v2-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v91-contract-tiering-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v92-evidence-oracle-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v93-workflow-narrative-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v94-control-deck-score-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v95-control-deck-score-history-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v96-metric-ladder-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v97-benchmark-readiness-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v98-wave-operator-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v99-wave-receipt-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v100-promotion-evidence-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v101-promotion-route-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v102-live-proof-1-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v103-live-proof-2-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v104-product-direction-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v105-verify-wedge-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v106-multi-wave-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v107-agent-fabric-control-plane-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v108-agent-fabric-reference-adapter-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v109-agent-fabric-capture-bridge-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v110-agent-fabric-report-assurance-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v111-agent-fabric-operator-view-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v112-agent-fabric-lifecycle-smoke-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v116-agent-fabric-smoke-cli-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "docs/v117-agent-fabric-harness-snapshot-spec.md")
    require_term(blockers, surfaces, "docs/release-history.md", "Roadmap reconciliation audits keep spec, roadmap, and release history aligned")

    return {
        "schema_version": AUDIT_VERSION,
        "tool": TOOL,
        "decision": "roadmap_reconciled" if not blockers else "blocked",
        "blocked_by": blockers,
        "surfaces": surface_records,
        "policy": {
            "public_product_brand": "Depone",
            "internal_engine_name": "DWM Core",
            "latest_version": "V117",
            "executes_commands": False,
        },
        "source_hashes": {"surfaces": canonical_hash(surfaces)},
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Roadmap Reconciliation Audit",
        "",
        f"- Decision: `{audit['decision']}`",
        "- Latest version: `V117`",
        "- Public product brand: `Depone`",
        "- Internal engine name: `DWM Core`",
        f"- Executes commands: `{audit['policy']['executes_commands']}`",
        "",
        "## Surfaces",
        "",
    ]
    for surface in audit["surfaces"]:
        lines.append(f"- `{surface['path']}`")
    lines.extend(["", "## Blockers", ""])
    if audit["blocked_by"]:
        for blocker in audit["blocked_by"]:
            lines.append(f"- `{blocker['code']}` `{blocker.get('path')}`: {blocker.get('term', '')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_audit(out_dir: Path, audit: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "roadmap-reconciliation.json", audit, root=out_dir)
    write_json_atomic(out_dir / "status.json", audit, root=out_dir)
    write_text_atomic(out_dir / "roadmap-reconciliation.md", render_markdown(audit), root=out_dir)


def repo_surfaces() -> dict[str, str]:
    surfaces: dict[str, str] = {}
    for label, path in DEFAULT_SURFACES.items():
        if not path.is_file() or path.is_symlink():
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_SURFACE_MISSING", "roadmap surface is missing or unsafe", path=path)
        surfaces[label] = path.read_text()
    return surfaces


def run_audit(out_dir: Path) -> dict[str, Any]:
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=ROOT)
    audit = audit_surfaces(repo_surfaces())
    audit["audit_id"] = out_dir.name
    write_audit(out_dir, audit)
    return audit


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v88-roadmap-reconciliation"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        surfaces = fixture.get("surfaces")
        if not isinstance(surfaces, dict):
            raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_MANIFEST_INVALID", "fixture surfaces must be an object", path=manifest_path, fixture_id=fixture_id)
        audit = audit_surfaces({str(key): str(value) for key, value in surfaces.items()})
        audit["audit_id"] = fixture_id
        write_audit(fixture_out, audit)
        expected_decision = fixture.get("expected_decision")
        status = "pass" if expected_decision in (None, audit["decision"]) else "fail"
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": status, "decision": audit["decision"], "error": None if status == "pass" else f"expected {expected_decision}, got {audit['decision']}"})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": AUDIT_VERSION,
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
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_FIXTURE_FAILED", "required roadmap reconciliation fixture failed", path=manifest_path)
    return summary


def good_surfaces() -> dict[str, str]:
    return {
        "docs/spec.md": "# Depone / DWM Core Spec\n\nStatus: V87 brand boundary audit implemented, V88 roadmap reconciliation, V89 command safety, V90 activation v2, V91 contract tiering, V92 evidence oracle, V93 workflow narrative, V94 control deck score, V95 score history, V96 metric ladder, V97 benchmark readiness, V98 wave operator, V99 wave receipt, V100 promotion evidence, V101 promotion route, V102 deterministic live-proof recorder, V103 live-proof comparison schema, V104 product direction, V105 verify wedge, V106 multi-wave validation, V107 Agent Fabric compiler, V108 reference adapter fixture, V109 capture bridge, V110 report assurance, V111 operator view, V112 lifecycle smoke, V116 Agent Fabric smoke CLI, V117 Agent Fabric harness snapshot, Last updated: 2026-06-24\n",
        "docs/automation-roadmap.md": "# Depone Automation Roadmap\n\nStatus: V88 roadmap reconciliation audit implemented. V89 command safety gate implemented. V90 activation v2 implemented. V91 contract tiering implemented. V92 evidence oracle implemented. V93 workflow narrative implemented. V94 control deck score implemented; V95 score history implemented; V96 metric ladder implemented; V97 benchmark readiness implemented; V98 wave operator implemented; V99 wave receipt implemented; V100 promotion evidence implemented; V101 promotion route implemented; V102 deterministic live-proof recorder implemented; V103 live-proof comparison schema implemented; V104 product direction implemented; V105 verify wedge implemented; V106 multi-wave validation implemented; V107 Agent Fabric contracts and compiler implemented; V108 Agent Fabric reference adapter fixture implemented; V109 Agent Fabric capture bridge implemented; V110 Agent Fabric report assurance implemented; V111 Agent Fabric operator view implemented; V112 Agent Fabric lifecycle smoke implemented; V116 Agent Fabric smoke CLI implemented; V117 Agent Fabric harness snapshot implemented.\n\n### V12-V20: Implemented Product Roadmap\n\n### V52-V117: Product Evidence, Control Deck, And Agent Fabric Guardrails\n",
        "docs/release-history.md": "# Depone Release History\n\n- V87: docs/v87-brand-boundary-audit-spec.md\n- V88: docs/v88-roadmap-reconciliation-spec.md\n- V89: docs/v89-command-safety-spec.md\n- V90: docs/v90-workflow-activation-v2-spec.md\n- V91: docs/v91-contract-tiering-spec.md\n- V92: docs/v92-evidence-oracle-spec.md\n- V93: docs/v93-workflow-narrative-spec.md\n- V94: docs/v94-control-deck-score-spec.md\n- V95: docs/v95-control-deck-score-history-spec.md\n- V96: docs/v96-metric-ladder-spec.md\n- V97: docs/v97-benchmark-readiness-spec.md\n- V98: docs/v98-wave-operator-spec.md\n- V99: docs/v99-wave-receipt-spec.md\n- V100: docs/v100-promotion-evidence-spec.md\n- V101: docs/v101-promotion-route-spec.md\n- V102: docs/v102-live-proof-1-spec.md\n- V103: docs/v103-live-proof-2-spec.md\n- V104: docs/v104-product-direction-spec.md\n- V105: docs/v105-verify-wedge-spec.md\n- V106: docs/v106-multi-wave-spec.md\n- V107: docs/v107-agent-fabric-control-plane-spec.md\n- V108: docs/v108-agent-fabric-reference-adapter-spec.md\n- V109: docs/v109-agent-fabric-capture-bridge-spec.md\n- V110: docs/v110-agent-fabric-report-assurance-spec.md\n- V111: docs/v111-agent-fabric-operator-view-spec.md\n- V112: docs/v112-agent-fabric-lifecycle-smoke-spec.md\n- V116: docs/v116-agent-fabric-smoke-cli-spec.md\n- V117: docs/v117-agent-fabric-harness-snapshot-spec.md\n\nRoadmap reconciliation audits keep spec, roadmap, and release history aligned.\n",
    }


def self_test() -> None:
    ready = audit_surfaces(good_surfaces())
    if ready["decision"] != "roadmap_reconciled":
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_SELF_TEST_FAILED", "ready surfaces should pass")
    stale = good_surfaces()
    stale["docs/automation-roadmap.md"] += "\nStatus: planned; not implemented.\n"
    if audit_surfaces(stale)["decision"] != "blocked":
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_SELF_TEST_FAILED", "stale roadmap status should block")
    missing_release = good_surfaces()
    missing_release["docs/release-history.md"] = "# Depone Release History\n\n- V87: docs/v87-brand-boundary-audit-spec.md\n"
    if audit_surfaces(missing_release)["decision"] != "blocked":
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_SELF_TEST_FAILED", "missing latest release entry should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("roadmap reconciliation self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "audit":
            audit = run_audit(args.out)
            print(json.dumps({"audit_id": audit["audit_id"], "decision": audit["decision"], "blocked_by": audit["blocked_by"]}, sort_keys=True))
            return
        raise RoadmapReconciliationError("ERR_ROADMAP_RECONCILIATION_ARGS_INVALID", "choose --self-test, --manifest, or audit")
    except RoadmapReconciliationError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
