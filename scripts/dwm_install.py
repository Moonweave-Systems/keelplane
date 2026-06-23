#!/usr/bin/env python3
"""V18 repo-local DWM install packaging checks."""

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

from compile_workflow import canonical_hash, canonical_json_text, read_json, sha256_text, write_json_atomic, write_text_atomic  # noqa: E402


TOOL = "dwm_install.py"
SCHEMA_VERSION = "1.0"
INSTALL_VERSION = "18.0.0"
INSTALL_ROOT = ROOT / "out" / "install"
PACKAGE_MANIFEST = ROOT / "packaging" / "dwm-package.json"
SENTINEL = ".dwm_install-owned.json"
SUPPORTED_SCHEMA_VERSION = "1.0"


class InstallError(ValueError):
    """Structured V18 install failure."""

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
        raise InstallError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise InstallError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_INSTALL_PATH_UNSAFE", message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise InstallError("ERR_INSTALL_PATH_UNSAFE", f"{label} path must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise InstallError("ERR_INSTALL_PATH_UNSAFE", f"{label} path must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_INSTALL_PATH_SYMLINK")
    return resolved


def resolve_install_out(value: str | Path) -> Path:
    return resolve_under(value, INSTALL_ROOT, label="install output")


def ensure_contained(root: Path, path: Path) -> None:
    target = path if path.is_absolute() else root / path
    reject_traversal(path, code="ERR_INSTALL_PATH_UNSAFE", message="artifact path escapes output directory")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise InstallError("ERR_INSTALL_PATH_UNSAFE", "artifact path escapes output directory", path=target) from exc


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, install_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise InstallError("ERR_INSTALL_PATH_SYMLINK", "install output is a symlink", path=path)
        if not path.is_dir():
            raise InstallError("ERR_INSTALL_PATH_UNSAFE", "install output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("install_id") != install_id:
            raise InstallError("ERR_INSTALL_PATH_UNSAFE", "existing install output is not install-owned", path=path)
        shutil.rmtree(path)
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "install_version": INSTALL_VERSION,
            "install_id": install_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def package_manifest() -> dict[str, Any]:
    manifest = read_json(PACKAGE_MANIFEST)
    if manifest.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise InstallError("ERR_INSTALL_SCHEMA_INCOMPATIBLE", "package schema version is not supported", path=PACKAGE_MANIFEST)
    adapters = manifest.get("adapter_surfaces")
    if not isinstance(adapters, list) or "claude" not in adapters or "codex" not in adapters:
        raise InstallError("ERR_INSTALL_PACKAGE_INVALID", "package must declare codex and claude adapter surfaces", path=PACKAGE_MANIFEST)
    return manifest


def validate_repo(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = package_manifest() if manifest is None else manifest
    if manifest.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise InstallError("ERR_INSTALL_SCHEMA_INCOMPATIBLE", "package schema version is not supported")
    core_artifacts = manifest.get("core_artifacts")
    if not isinstance(core_artifacts, list) or not core_artifacts:
        raise InstallError("ERR_INSTALL_PACKAGE_INVALID", "package core_artifacts must be a non-empty list")
    hashes: dict[str, str] = {}
    for item in core_artifacts:
        if not isinstance(item, str) or not item:
            raise InstallError("ERR_INSTALL_PACKAGE_INVALID", "core artifact path must be a string")
        path = ROOT / item
        reject_traversal(Path(item), code="ERR_INSTALL_PATH_UNSAFE", message="core artifact path must not traverse")
        if not path.is_file() or path.is_symlink():
            raise InstallError("ERR_INSTALL_PACKAGE_INVALID", "core artifact is missing or symlinked", path=path)
        hashes[item] = sha256_text(path.read_text())
    return {
        "status": "valid",
        "package": manifest["name"],
        "contract_version": manifest["contract_version"],
        "adapter_surfaces": manifest["adapter_surfaces"],
        "portable_cli": manifest["portable_cli"],
        "artifact_hashes": hashes,
    }


def launcher_text(repo_root: Path) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "set -eu",
            f"cd {json.dumps(str(repo_root))}",
            'exec "${PYTHON:-python}" scripts/dwm.py "$@"',
            "",
        ]
    )


def install(temp_home: Path, out_dir: Path, *, approve_overwrite: bool = False) -> dict[str, Any]:
    out_dir = resolve_install_out(out_dir)
    install_id = out_dir.name
    prepare_out_dir(out_dir, install_id, source=temp_home)
    temp_home = temp_home.resolve(strict=False)
    if temp_home.is_symlink():
        raise InstallError("ERR_INSTALL_PATH_SYMLINK", "home path is a symlink", path=temp_home)
    temp_home.mkdir(parents=True, exist_ok=True)
    manifest = package_manifest()
    repo_validation = validate_repo(manifest)
    config_dir = temp_home / ".dwm"
    bin_dir = temp_home / "bin"
    config_path = config_dir / "config.json"
    if config_path.exists() and not approve_overwrite:
        raise InstallError("ERR_INSTALL_CONFIG_EXISTS", "config exists; overwrite requires approval", path=config_path)
    config_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "dwm"
    config = {
        "schema_version": SCHEMA_VERSION,
        "install_version": INSTALL_VERSION,
        "repo_root": str(ROOT),
        "package_manifest": rel(PACKAGE_MANIFEST),
        "adapter_surfaces": manifest["adapter_surfaces"],
        "portable_cli": True,
        "claude_compatible": "claude" in manifest["adapter_surfaces"],
    }
    write_json_atomic(config_path, config, root=temp_home)
    write_text_atomic(launcher, launcher_text(ROOT), root=temp_home)
    launcher.chmod(0o755)
    status = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "install_version": INSTALL_VERSION,
        "install_id": install_id,
        "status": "installed",
        "home_path": str(temp_home),
        "config_path": str(config_path),
        "launcher_path": str(launcher),
        "repo_validation": repo_validation,
    }
    write_json_atomic(out_dir / "install-status.json", status, root=out_dir)
    write_text_atomic(
        out_dir / "install.md",
        "\n".join(
            [
                "# V18 DWM Install",
                "",
                f"Status: `{status['status']}`",
                f"Launcher: `{status['launcher_path']}`",
                f"Claude compatible: `{config['claude_compatible']}`",
                "",
            ]
        ),
        root=out_dir,
    )
    return status


def run_fixture(fixture: dict[str, Any], suite_dir: Path, temp_root: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        out_dir = suite_dir / fixture_id
        kind = fixture["kind"]
        if kind == "validate":
            validation = validate_repo()
            status = {"status": validation["status"], "validation": validation}
        elif kind == "incompatible-schema":
            manifest = package_manifest()
            manifest["schema_version"] = "999.0"
            try:
                validate_repo(manifest)
            except InstallError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
            else:
                raise InstallError("ERR_INSTALL_FIXTURE_FAILED", "incompatible schema should block")
        else:
            home = temp_root / f"{fixture_id}-home"
            if kind == "config-overwrite":
                config_dir = home / ".dwm"
                config_dir.mkdir(parents=True)
                write_json_atomic(config_dir / "config.json", {"existing": True}, root=home)
            try:
                status = install(home, out_dir)
            except InstallError as exc:
                if fixture.get("expected_error") != exc.code:
                    raise
                status = {"status": "blocked", "error": exc.to_record()}
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise InstallError("ERR_INSTALL_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise InstallError("ERR_INSTALL_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "required": fixture.get("required", True)}
    except InstallError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_install_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("install_id") != suite_id:
            raise InstallError("ERR_INSTALL_PATH_UNSAFE", "existing install suite is not install-owned", path=suite_dir)
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True)
    write_json_atomic(
        suite_dir / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "install_version": INSTALL_VERSION,
            "install_id": suite_id,
            "source_path": rel(manifest_path),
            "created_at": now_utc(),
        },
        root=suite_dir,
    )
    temp_root = suite_dir / "_temp"
    temp_root.mkdir()
    fixtures = manifest["fixtures"]
    required_ids = set(manifest["required_fixture_ids"])
    results = [run_fixture(fixture, suite_dir, temp_root) for fixture in fixtures]
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
        raise InstallError("ERR_INSTALL_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-install-self-test-", dir=INSTALL_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v18" / "manifest.json", Path(tmp) / "install-self-test")
    if summary["decision"] != "keep":
        raise InstallError("ERR_INSTALL_FIXTURE_FAILED", "install self-test manifest did not keep")
    print("dwm_install self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["install", "validate"])
    parser.add_argument("--home")
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--approve-overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise InstallError("ERR_INSTALL_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "validate":
            print(canonical_json_text(validate_repo()))
        elif args.command == "install":
            if not args.home or not args.out:
                raise InstallError("ERR_INSTALL_PATH_UNSAFE", "install requires --home and --out")
            print(canonical_json_text(install(Path(args.home), Path(args.out), approve_overwrite=args.approve_overwrite)))
        else:
            parser.error("expected --self-test, --manifest, install, or validate")
    except InstallError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
