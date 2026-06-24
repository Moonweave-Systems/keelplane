#!/usr/bin/env python3
"""V84 installed surface audit for DWM."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_workflow import canonical_hash, read_json, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_installed_surface_audit.py"
AUDIT_VERSION = "84.0.0"
AUDIT_ROOT = ROOT / "out" / "installed-surface-audits"
SENTINEL = ".dwm_installed_surface_audit-owned.json"
DEFAULT_ACTIVE_SKILL = ROOT / "SKILL.md"
DEFAULT_INSTALL_CANDIDATES = [
    Path.home() / ".codex" / "skills" / "depone" / "SKILL.md",
    Path.home() / ".agents" / "skills" / "depone" / "SKILL.md",
]


class InstalledSurfaceAuditError(ValueError):
    """Structured V84 installed surface audit failure."""

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_git_value(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    value = completed.stdout.strip()
    return value or None


def reject_traversal(path: Path, *, code: str, message: str) -> None:
    if any(part == ".." for part in path.parts):
        raise InstalledSurfaceAuditError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise InstalledSurfaceAuditError(code, "path contains a symlink", path=current)


def path_has_symlink_component(path: Path) -> bool:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", message="audit output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    audit_root = AUDIT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(audit_root)
    except ValueError as exc:
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", f"audit output must resolve under {audit_root}", path=value) from exc
    if resolved == audit_root:
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", "audit output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_INSTALLED_SURFACE_AUDIT_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    reject_traversal(raw, code="ERR_INSTALLED_SURFACE_AUDIT_INPUT_UNSAFE", message="audit input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    return candidate.resolve(strict=False)


def prepare_out_dir(path: Path, audit_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_SYMLINK", "audit output is a symlink", path=path)
        if not path.is_dir():
            raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", "audit output is not a directory", path=path)
        sentinel = path / SENTINEL
        if not sentinel.is_file() or sentinel.is_symlink():
            raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", "existing audit output is not audit-owned", path=path)
        try:
            data = json.loads(sentinel.read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", "audit sentinel is invalid", path=sentinel) from exc
        if data.get("audit_id") != audit_id:
            raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_PATH_UNSAFE", "audit sentinel belongs to a different id", path=sentinel)
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


def file_surface(path: Path, label: str) -> dict[str, Any]:
    raw = Path(path).expanduser()
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = resolve_input(path)
    exists = resolved.is_file()
    return {
        "label": label,
        "path": str(candidate),
        "resolved_path": rel(resolved),
        "exists": exists,
        "content_hash": sha256_file(resolved) if exists else None,
        "is_repo_skill": resolved == DEFAULT_ACTIVE_SKILL.resolve(strict=False),
        "uses_symlink": path_has_symlink_component(candidate),
    }


def repo_metadata() -> dict[str, Any]:
    return {
        "head": safe_git_value(["git", "rev-parse", "HEAD"]),
        "branch": safe_git_value(["git", "branch", "--show-current"]),
        "upstream": safe_git_value(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]),
    }


def source_hashes(active: dict[str, Any], installs: list[dict[str, Any]]) -> dict[str, Any]:
    hashes: dict[str, Any] = {
        "active_skill": active.get("content_hash"),
        "repo_skill": sha256_file(DEFAULT_ACTIVE_SKILL) if DEFAULT_ACTIVE_SKILL.is_file() else None,
    }
    for relative in ("README.md", "scripts/dwm.py"):
        path = ROOT / relative
        hashes[relative] = sha256_file(path) if path.is_file() else None
    hashes["installed_surfaces"] = {surface["path"]: surface.get("content_hash") for surface in installs}
    hashes["repo_metadata"] = repo_metadata()
    return hashes


def decide(active: dict[str, Any], installs: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    repo_skill_hash = sha256_file(DEFAULT_ACTIVE_SKILL) if DEFAULT_ACTIVE_SKILL.is_file() else None
    active_hash = active.get("content_hash")
    existing_installs = [surface for surface in installs if surface.get("exists")]

    if not active.get("exists"):
        blockers.append({"code": "ERR_INSTALLED_SURFACE_ACTIVE_MISSING", "message": "active skill path is missing or unsafe"})
    if active_hash is not None and repo_skill_hash is not None and active_hash != repo_skill_hash:
        blockers.append({"code": "ERR_INSTALLED_SURFACE_ACTIVE_DRIFT", "message": "active skill hash does not match the repo SKILL.md"})
    for surface in existing_installs:
        if surface.get("content_hash") != repo_skill_hash:
            blockers.append(
                {
                    "code": "ERR_INSTALLED_SURFACE_COPY_STALE",
                    "message": "copied installed skill does not match the repo SKILL.md",
                    "path": surface.get("path"),
                }
            )

    if blockers:
        decision = "blocked"
    elif existing_installs:
        decision = "installed_copy_synced"
    elif active.get("is_repo_skill"):
        decision = "repo_backed_active_surface"
    else:
        decision = "repo_backed_active_surface" if active_hash == repo_skill_hash else "blocked"

    note = "active session reads the repo SKILL.md directly" if active.get("is_repo_skill") else "active session uses a non-default skill path"
    if not existing_installs:
        note += "; no copied install candidate was detected"
    return {"decision": decision, "blocked_by": blockers, "note": note}


def make_audit(audit_id: str, active: dict[str, Any], installs: list[dict[str, Any]]) -> dict[str, Any]:
    decision = decide(active, installs)
    return {
        "schema_version": AUDIT_VERSION,
        "tool": TOOL,
        "audit_id": audit_id,
        "decision": decision["decision"],
        "note": decision["note"],
        "active_surface": active,
        "installed_surfaces": installs,
        "blocked_by": decision["blocked_by"],
        "source_hashes": source_hashes(active, installs),
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        f"# Installed Surface Audit {audit['audit_id']}",
        "",
        f"- Decision: `{audit['decision']}`",
        f"- Active skill: `{audit['active_surface']['path']}`",
        f"- Active exists: `{audit['active_surface']['exists']}`",
        f"- Note: {audit['note']}",
        "",
        "## Installed Copies",
        "",
    ]
    existing = [surface for surface in audit["installed_surfaces"] if surface.get("exists")]
    if existing:
        for surface in existing:
            lines.append(f"- `{surface['path']}` hash `{surface.get('content_hash')}`")
    else:
        lines.append("- none detected in the checked install roots")
    lines.extend(["", "## Blockers", ""])
    if audit["blocked_by"]:
        for blocker in audit["blocked_by"]:
            lines.append(f"- `{blocker['code']}`: {blocker.get('message', '')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_audit(out_dir: Path, audit: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "installed-surface-audit.json", audit, root=out_dir)
    write_json_atomic(out_dir / "status.json", audit, root=out_dir)
    write_text_atomic(out_dir / "installed-surface-audit.md", render_markdown(audit), root=out_dir)


def run_audit(active_skill: Path, out_dir: Path, install_candidates: list[Path] | None = None) -> dict[str, Any]:
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=active_skill)
    active = file_surface(active_skill, "active")
    candidates = install_candidates if install_candidates is not None else DEFAULT_INSTALL_CANDIDATES
    installs = [file_surface(candidate, "installed-copy") for candidate in candidates]
    audit = make_audit(out_dir.name, active, installs)
    write_audit(out_dir, audit)
    return audit


def surface_from_fixture(surface: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(surface.get("label", "fixture")),
        "path": str(surface.get("path", "fixture/SKILL.md")),
        "exists": bool(surface.get("exists", True)),
        "content_hash": surface.get("content_hash"),
        "is_repo_skill": bool(surface.get("is_repo_skill", False)),
    }


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v84-installed-surface-audit"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_MANIFEST_INVALID", "fixture must be an object", path=manifest_path)
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        active_raw = fixture.get("active_surface")
        install_raw = fixture.get("installed_surfaces")
        active = surface_from_fixture(active_raw if isinstance(active_raw, dict) else {})
        installs = [surface_from_fixture(item) for item in install_raw] if isinstance(install_raw, list) else []
        audit = make_audit(fixture_id, active, installs)
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
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_FIXTURE_FAILED", "required installed surface audit fixture failed", path=manifest_path)
    return summary


def self_test() -> None:
    repo_hash = sha256_file(DEFAULT_ACTIVE_SKILL)
    ready = make_audit(
        "self-test-ready",
        {"label": "active", "path": "SKILL.md", "exists": True, "content_hash": repo_hash, "is_repo_skill": True},
        [],
    )
    if ready["decision"] != "repo_backed_active_surface":
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_SELF_TEST_FAILED", "repo-backed active surface should be ready")
    synced = make_audit(
        "self-test-synced",
        {"label": "active", "path": "SKILL.md", "exists": True, "content_hash": repo_hash, "is_repo_skill": True},
        [{"label": "installed-copy", "path": "~/.codex/skills/depone/SKILL.md", "exists": True, "content_hash": repo_hash, "is_repo_skill": False}],
    )
    if synced["decision"] != "installed_copy_synced":
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_SELF_TEST_FAILED", "matching installed copy should be synced")
    stale = make_audit(
        "self-test-stale",
        {"label": "active", "path": "SKILL.md", "exists": True, "content_hash": repo_hash, "is_repo_skill": True},
        [{"label": "installed-copy", "path": "~/.codex/skills/depone/SKILL.md", "exists": True, "content_hash": "stale", "is_repo_skill": False}],
    )
    if stale["decision"] != "blocked":
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_SELF_TEST_FAILED", "stale installed copy should block")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--active-skill", type=Path, default=DEFAULT_ACTIVE_SKILL)
    audit_parser.add_argument("--install-candidate", action="append", type=Path, default=[])
    audit_parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("installed surface audit self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_ARGS_INVALID", "--manifest requires --out")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "audit":
            candidates = args.install_candidate if args.install_candidate else None
            audit = run_audit(args.active_skill, args.out, install_candidates=candidates)
            print(json.dumps({"decision": audit["decision"], "audit_id": audit["audit_id"], "blocked_by": audit["blocked_by"]}, sort_keys=True))
            return
        raise InstalledSurfaceAuditError("ERR_INSTALLED_SURFACE_AUDIT_ARGS_INVALID", "choose --self-test, --manifest, or audit")
    except InstalledSurfaceAuditError as exc:
        print(json.dumps({"status": "error", "error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
