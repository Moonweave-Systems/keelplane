#!/usr/bin/env python3
"""V87 public brand boundary audit for Depone."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_brand_boundary_audit.py"
AUDIT_VERSION = "87.0.0"
AUDIT_ROOT = ROOT / "out" / "brand-boundary-audits"
SENTINEL = ".dwm_brand_boundary_audit-owned.json"
DEFAULT_SURFACES = {
    "SKILL.md": ROOT / "SKILL.md",
    "agents/openai.yaml": ROOT / "agents" / "openai.yaml",
    "README.md": ROOT / "README.md",
    "docs/dwm-branding.md": ROOT / "docs" / "dwm-branding.md",
    "docs/command-reference.md": ROOT / "docs" / "command-reference.md",
    "docs/release-history.md": ROOT / "docs" / "release-history.md",
    "assets/dwm-hero.svg": ROOT / "assets" / "dwm-hero.svg",
}


class BrandBoundaryAuditError(ValueError):
    """Structured V87 brand boundary audit failure."""

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
        raise BrandBoundaryAuditError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BrandBoundaryAuditError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_BRAND_BOUNDARY_PATH_UNSAFE", message="audit output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = AUDIT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_UNSAFE", f"audit output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_UNSAFE", "audit output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_BRAND_BOUNDARY_PATH_SYMLINK")
    return resolved


def prepare_out_dir(path: Path, audit_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_SYMLINK", "audit output is a symlink", path=path)
        if not path.is_dir():
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_UNSAFE", "audit output is not a directory", path=path)
        sentinel = path / SENTINEL
        if not sentinel.is_file() or sentinel.is_symlink():
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_UNSAFE", "existing audit output is not audit-owned", path=path)
        try:
            data = json.loads(sentinel.read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_UNSAFE", "audit sentinel is invalid", path=sentinel) from exc
        if data.get("audit_id") != audit_id:
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_PATH_UNSAFE", "audit sentinel belongs to a different id", path=sentinel)
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


def lower(text: str) -> str:
    return text.lower()


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def add_missing(blockers: list[dict[str, Any]], path: str, term: str, *, code: str = "ERR_BRAND_BOUNDARY_REQUIRED_TERM_MISSING") -> None:
    blockers.append({"code": code, "path": path, "term": term, "message": "required brand boundary term is missing"})


def add_forbidden(blockers: list[dict[str, Any]], path: str, term: str, *, code: str = "ERR_BRAND_BOUNDARY_FORBIDDEN_PUBLIC_TERM") -> None:
    blockers.append({"code": code, "path": path, "term": term, "message": "forbidden public brand wording was found"})


def audit_surfaces(surfaces: dict[str, str]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    surface_records: list[dict[str, Any]] = []

    for path, text in surfaces.items():
        text_lower = lower(text)
        surface_records.append({"path": path, "content_hash": canonical_hash({"text": text})})
        if re.search(r"(?im)^#\s+dwm\b", text):
            add_forbidden(blockers, path, "# DWM")
        if re.search(r"(?im)^#\s+dwm\s+branding\b", text):
            add_forbidden(blockers, path, "# DWM Branding")
        autonomy_safe_context = (
            "does not claim autonomous execution" in text_lower
            or "does not claim unrestricted autonomous execution" in text_lower
            or "do not claim autonomous execution" in text_lower
            or "without claiming" in text_lower
            or "without claiming autonomous execution" in text_lower
        )
        if "autonomous execution" in text_lower and not autonomy_safe_context:
            add_forbidden(blockers, path, "autonomous execution", code="ERR_BRAND_BOUNDARY_AUTONOMY_OVERCLAIM")
        if "executes live commands" in text_lower:
            add_forbidden(blockers, path, "executes live commands", code="ERR_BRAND_BOUNDARY_AUTONOMY_OVERCLAIM")

    readme = surfaces.get("README.md", "")
    if first_nonempty_line(readme).lower() != "# depone":
        add_missing(blockers, "README.md", "# Depone", code="ERR_BRAND_BOUNDARY_PUBLIC_HEADING_INVALID")
    for term in ("DWM Core", "skill is named `depone`"):
        if term.lower() not in lower(readme):
            add_missing(blockers, "README.md", term)

    skill = surfaces.get("SKILL.md", "")
    for term in ("name: depone", "Depone skill entrypoint", "dynamic workflows"):
        if term.lower() not in lower(skill):
            add_missing(blockers, "SKILL.md", term)

    agent_config = surfaces.get("agents/openai.yaml", "")
    for term in ('display_name: "Depone"', "$depone"):
        if term.lower() not in lower(agent_config):
            add_missing(blockers, "agents/openai.yaml", term)

    branding = surfaces.get("docs/dwm-branding.md", "")
    for term in (
        "Depone is the public product brand",
        "DWM Core stands for",
        "Codex skill name is `depone`",
        "repository slug remains `keelplane`",
        "Do not claim autonomous execution",
    ):
        if term.lower() not in lower(branding):
            add_missing(blockers, "docs/dwm-branding.md", term)

    command_reference = surfaces.get("docs/command-reference.md", "")
    if first_nonempty_line(command_reference).lower() != "# depone command reference":
        add_missing(blockers, "docs/command-reference.md", "# Depone Command Reference", code="ERR_BRAND_BOUNDARY_PUBLIC_HEADING_INVALID")

    release_history = surfaces.get("docs/release-history.md", "")
    if first_nonempty_line(release_history).lower() != "# depone release history":
        add_missing(blockers, "docs/release-history.md", "# Depone Release History", code="ERR_BRAND_BOUNDARY_PUBLIC_HEADING_INVALID")
    if "docs/v86-keelplane-brand-spec.md" not in lower(release_history):
        add_missing(blockers, "docs/release-history.md", "docs/v86-keelplane-brand-spec.md")

    hero = surfaces.get("assets/dwm-hero.svg", "")
    for term in ("Depone", "Powered by DWM Core"):
        if term.lower() not in lower(hero):
            add_missing(blockers, "assets/dwm-hero.svg", term)

    return {
        "schema_version": AUDIT_VERSION,
        "tool": TOOL,
        "decision": "brand_boundary_ready" if not blockers else "blocked",
        "blocked_by": blockers,
        "surfaces": surface_records,
        "policy": {
            "public_product_brand": "Depone",
            "internal_engine_name": "DWM Core",
            "skill_name": "depone",
            "repository_slug": "dwm",
            "executes_commands": False,
        },
        "source_hashes": {"surfaces": canonical_hash(surfaces)},
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Brand Boundary Audit",
        "",
        f"- Decision: `{audit['decision']}`",
        "- Public product brand: `Depone`",
        "- Internal engine name: `DWM Core`",
        "- Skill name: `depone`",
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
    write_json_atomic(out_dir / "brand-boundary-audit.json", audit, root=out_dir)
    write_json_atomic(out_dir / "status.json", audit, root=out_dir)
    write_text_atomic(out_dir / "brand-boundary-audit.md", render_markdown(audit), root=out_dir)


def repo_surfaces() -> dict[str, str]:
    surfaces: dict[str, str] = {}
    for label, path in DEFAULT_SURFACES.items():
        if not path.is_file() or path.is_symlink():
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_SURFACE_MISSING", "brand boundary surface is missing or unsafe", path=path)
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
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v87-brand-boundary-audit"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        surfaces = fixture.get("surfaces")
        if not isinstance(surfaces, dict):
            raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_MANIFEST_INVALID", "fixture surfaces must be an object", path=manifest_path, fixture_id=fixture_id)
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
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_FIXTURE_FAILED", "required brand boundary fixture failed", path=manifest_path)
    return summary


def good_surfaces() -> dict[str, str]:
    return {
        "SKILL.md": "---\nname: depone\ndescription: Depone skill entrypoint. Use when a user asks for dynamic workflows.\n---\n# Depone Skill Entrypoint\n",
        "agents/openai.yaml": 'interface:\n  display_name: "Depone"\n  default_prompt: "Use $depone to design a workflow."\n',
        "README.md": "# Depone\n\nDepone uses DWM Core and the skill is named `depone`.\n",
        "docs/dwm-branding.md": "# Depone Branding\n\nDepone is the public product brand.\nDWM Core stands for Deterministic Workflow Machine.\nThe Codex skill name is `depone`.\nThe repository slug remains `keelplane`.\nDo not claim autonomous execution.\n",
        "docs/command-reference.md": "# Depone Command Reference\n",
        "docs/release-history.md": "# Depone Release History\n\n- V86: docs/v86-keelplane-brand-spec.md\n",
        "assets/dwm-hero.svg": "<svg><title>Depone</title><text>Powered by DWM Core</text></svg>\n",
    }


def self_test() -> None:
    ready = audit_surfaces(good_surfaces())
    if ready["decision"] != "brand_boundary_ready":
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_SELF_TEST_FAILED", "ready surfaces should pass")
    stale = good_surfaces()
    stale["README.md"] = "# DWM\n\nOld public product heading.\n"
    blocked = audit_surfaces(stale)
    codes = {item["code"] for item in blocked["blocked_by"]}
    if blocked["decision"] != "blocked" or "ERR_BRAND_BOUNDARY_PUBLIC_HEADING_INVALID" not in codes:
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_SELF_TEST_FAILED", "stale DWM public heading should block")
    overclaim = good_surfaces()
    overclaim["README.md"] += "\nDepone executes live commands without review.\n"
    blocked_overclaim = audit_surfaces(overclaim)
    if blocked_overclaim["decision"] != "blocked":
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_SELF_TEST_FAILED", "live execution overclaim should block")


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
            print("brand boundary audit self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "audit":
            audit = run_audit(args.out)
            print(json.dumps({"audit_id": audit["audit_id"], "decision": audit["decision"], "blocked_by": audit["blocked_by"]}, sort_keys=True))
            return
        raise BrandBoundaryAuditError("ERR_BRAND_BOUNDARY_ARGS_INVALID", "choose --self-test, --manifest, or audit")
    except BrandBoundaryAuditError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
