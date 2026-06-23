#!/usr/bin/env python3
"""V51/V53 canonical DWM demo and inspection surface."""

from __future__ import annotations

import argparse
import json
import os
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


TOOL = "dwm_demo.py"
SCHEMA_VERSION = "1.0"
DEMO_VERSION = "53.0.0"
DEMO_ROOT = ROOT / "out" / "demo"
SENTINEL = ".dwm_demo-owned.json"


class DemoError(ValueError):
    """Structured V51 demo failure."""

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
        raise DemoError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DemoError(code, "path contains a symlink", path=current)


def resolve_demo_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DEMO_PATH_UNSAFE", message="demo output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = DEMO_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DemoError("ERR_DEMO_PATH_UNSAFE", f"demo output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DemoError("ERR_DEMO_PATH_UNSAFE", "demo output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DEMO_PATH_SYMLINK")
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


def remove_owned_dir(path: Path) -> None:
    for index in range(100):
        tombstone = path.with_name(f".{path.name}.deleting-{os.getpid()}-{index}")
        if tombstone.exists():
            continue
        path.rename(tombstone)
        try:
            shutil.rmtree(tombstone)
        except OSError:
            pass
        return
    raise DemoError("ERR_DEMO_PATH_UNSAFE", "could not allocate demo tombstone path", path=path)


def prepare_out_dir(path: Path, demo_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DemoError("ERR_DEMO_PATH_SYMLINK", "demo output is a symlink", path=path)
        if not path.is_dir():
            raise DemoError("ERR_DEMO_PATH_UNSAFE", "demo output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("demo_id") != demo_id:
            raise DemoError("ERR_DEMO_PATH_UNSAFE", "existing demo output is not demo-owned", path=path)
        remove_owned_dir(path)
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "demo_version": DEMO_VERSION,
            "demo_id": demo_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def demo_commands(demo_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "product-plan",
            "description": "Record a product-shell plan request.",
            "command": [sys.executable, "scripts/dwm.py", "plan", "Demo failing test fix", "--out", f"out/v21/{demo_id}-plan", "--json"],
            "artifacts": [f"out/v21/{demo_id}-plan/workflow-request.json"],
        },
        {
            "id": "first-slice-compile",
            "description": "Compile deterministic first-slice packet fixtures.",
            "command": [sys.executable, "scripts/compile_workflow.py", "--manifest", "fixtures/v1/manifest.json", "--out", f"out/v1/{demo_id}-compile"],
            "artifacts": [f"out/v1/{demo_id}-compile/summary.json"],
        },
        {
            "id": "packet-review",
            "description": "Run one-packet execution and review/repair fixture evidence.",
            "command": [sys.executable, "scripts/execute_packet.py", "--manifest", "fixtures/v2.5/manifest.json", "--out", f"out/v2.5/{demo_id}-review"],
            "artifacts": [f"out/v2.5/{demo_id}-review/summary.json"],
        },
        {
            "id": "adapter-parity",
            "description": "Record adapter support without live adapter execution.",
            "command": [sys.executable, "scripts/dwm_adapters.py", "parity", "--out", f"out/adapters/{demo_id}-parity"],
            "artifacts": [f"out/adapters/{demo_id}-parity/adapter-parity.json"],
        },
        {
            "id": "dogfood-corpus",
            "description": "Record local dogfood tasks with comparison placeholders.",
            "command": [sys.executable, "scripts/dwm_dogfood_corpus.py", "record", "--out", f"out/dogfood-corpus/{demo_id}-corpus"],
            "artifacts": [f"out/dogfood-corpus/{demo_id}-corpus/dogfood-corpus.json"],
        },
        {
            "id": "daily-operator",
            "description": "Summarize the next safe operator action.",
            "command": [
                sys.executable,
                "scripts/dwm_daily_operator.py",
                "today",
                "--corpus",
                f"out/dogfood-corpus/{demo_id}-corpus",
                "--out",
                f"out/daily-operator/{demo_id}-operator",
            ],
            "artifacts": [f"out/daily-operator/{demo_id}-operator/today.md"],
        },
        {
            "id": "release-candidate",
            "description": "Cut a release candidate from parity and operator evidence.",
            "command": [
                sys.executable,
                "scripts/dwm_release_candidate.py",
                "cut",
                "--parity",
                f"out/adapters/{demo_id}-parity",
                "--operator",
                f"out/daily-operator/{demo_id}-operator",
                "--out",
                f"out/release-candidates/{demo_id}-rc",
            ],
            "artifacts": [f"out/release-candidates/{demo_id}-rc/release-candidate.json"],
        },
    ]


def run_command(record: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(record["command"], cwd=ROOT, check=False, text=True, capture_output=True)
    result = {
        "id": record["id"],
        "description": record["description"],
        "command": record["command"],
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "artifacts": record["artifacts"],
    }
    if completed.returncode != 0:
        raise DemoError("ERR_DEMO_COMMAND_FAILED", f"demo command failed: {record['id']}", path=record["command"][1])
    return result


def read_json_obj(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DemoError("ERR_DEMO_ARTIFACT_MISSING", f"{label} is missing or symlinked", path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise DemoError("ERR_DEMO_ARTIFACT_MISSING", f"{label} must be a JSON object", path=path)
    return data


def expected_command_hash(demo_id: str) -> str:
    commands = demo_commands(demo_id)
    return canonical_hash([{"id": item["id"], "command": item["command"]} for item in commands])


def render_demo_readme(demo: dict[str, Any]) -> str:
    lines = [
        "# DWM Canonical Demo",
        "",
        f"Decision: `{demo['decision']}`",
        "",
        "This demo uses deterministic local artifacts only. It does not execute live adapters or mutate source files.",
        "",
        "## Commands",
        "",
    ]
    for result in demo["results"]:
        command_text = " ".join(result["command"])
        lines.extend(
            [
                f"### {result['id']}",
                "",
                result["description"],
                "",
                "```bash",
                command_text,
                "```",
                "",
                f"Return code: `{result['returncode']}`",
                "",
            ]
        )
    lines.extend(["## Next Read", "", f"- `{demo['next_read']}`", ""])
    return "\n".join(lines)


def render_inspect_summary(inspect: dict[str, Any]) -> str:
    lines = [
        "# DWM Demo Inspect Summary",
        "",
        f"Decision: `{inspect['decision']}`",
        f"Demo: `{inspect['demo_id']}`",
        "",
        "This inspection reads existing demo artifacts. It does not rerun demo commands, execute live adapters, or mutate source files.",
        "",
        "## Evidence",
        "",
        f"- Commands recorded: `{inspect['command_count']}`",
        f"- Declared artifacts checked: `{inspect['declared_artifact_count']}`",
        f"- Missing declared artifacts: `{len(inspect['missing_declared_artifacts'])}`",
        f"- Next read: `{inspect['next_read']}`",
        "",
        "## Commands",
        "",
    ]
    for command in inspect["commands"]:
        lines.extend(
            [
                f"- `{command['id']}` -> `{command['returncode']}`",
            ]
        )
    lines.extend(["", "## Generated Files", ""])
    for path in inspect["generated_files"]:
        lines.append(f"- `{path}`")
    lines.append("")
    return "\n".join(lines)


def run_demo(out_dir: Path) -> dict[str, Any]:
    out_dir = resolve_demo_out(out_dir)
    demo_id = out_dir.name
    prepare_out_dir(out_dir, demo_id, source=ROOT / "fixtures" / "v51" / "manifest.json")
    results = [run_command(record) for record in demo_commands(demo_id)]
    demo = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "demo_version": DEMO_VERSION,
        "demo_id": demo_id,
        "status": "demo-recorded",
        "decision": "demo-ready",
        "results": results,
        "artifact_count": sum(len(result["artifacts"]) for result in results),
        "source_hashes": {
            "commands": canonical_hash([{"id": item["id"], "command": item["command"]} for item in results]),
        },
        "safe_default": "inspect generated artifacts before any live adapter execution",
        "next_read": f"out/release-candidates/{demo_id}-rc/release-notes.md",
    }
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            out_dir / SENTINEL,
            {
                "tool": TOOL,
                "schema_version": SCHEMA_VERSION,
                "demo_version": DEMO_VERSION,
                "demo_id": demo_id,
                "source_path": rel(ROOT / "fixtures" / "v51" / "manifest.json"),
                "created_at": now_utc(),
            },
            root=out_dir,
        )
    sentinel = read_sentinel(out_dir)
    if sentinel is None or sentinel.get("demo_id") != demo_id:
        raise DemoError("ERR_DEMO_PATH_UNSAFE", "demo output ownership was lost during run", path=out_dir)
    write_json_atomic(out_dir / "demo.json", demo, root=out_dir)
    write_json_atomic(out_dir / "status.json", demo, root=out_dir)
    write_text_atomic(out_dir / "README.md", render_demo_readme(demo), root=out_dir)
    return demo


def inspect_demo(demo_dir: Path) -> dict[str, Any]:
    demo_dir = resolve_demo_out(demo_dir)
    demo_id = demo_dir.name
    sentinel = read_sentinel(demo_dir)
    if sentinel is None or sentinel.get("demo_id") != demo_id:
        raise DemoError("ERR_DEMO_ARTIFACT_MISSING", "demo ownership sentinel is missing or stale", path=demo_dir)
    demo = read_json_obj(demo_dir / "demo.json", label="demo.json")
    status = read_json_obj(demo_dir / "status.json", label="status.json")
    if demo.get("demo_id") != demo_id or status.get("demo_id") != demo_id:
        raise DemoError("ERR_DEMO_STALE_HASH", "demo id does not match inspected directory", path=demo_dir)
    if canonical_hash(demo) != canonical_hash(status):
        raise DemoError("ERR_DEMO_STALE_HASH", "demo.json and status.json no longer match", path=demo_dir)
    if demo.get("source_hashes", {}).get("commands") != expected_command_hash(demo_id):
        raise DemoError("ERR_DEMO_STALE_HASH", "demo command hash does not match current command plan", path=demo_dir / "demo.json")
    results = demo.get("results")
    if not isinstance(results, list) or not results:
        raise DemoError("ERR_DEMO_ARTIFACT_MISSING", "demo results are missing", path=demo_dir / "demo.json")
    commands: list[dict[str, Any]] = []
    declared_artifacts: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            raise DemoError("ERR_DEMO_ARTIFACT_MISSING", "demo result must be an object", path=demo_dir / "demo.json")
        result_id = str(result.get("id", ""))
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            raise DemoError("ERR_DEMO_ARTIFACT_MISSING", f"demo result artifacts missing: {result_id}", path=demo_dir / "demo.json")
        declared_artifacts.extend(str(path) for path in artifacts)
        commands.append({"id": result_id, "returncode": result.get("returncode"), "artifact_count": len(artifacts)})
    missing_declared = [path for path in declared_artifacts if not (ROOT / path).is_file()]
    if missing_declared:
        raise DemoError("ERR_DEMO_ARTIFACT_MISSING", "declared demo artifacts are missing", path=missing_declared[0])
    inspect = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "demo_version": DEMO_VERSION,
        "demo_id": demo_id,
        "status": "inspect-recorded",
        "decision": "inspect-ready",
        "command_count": len(commands),
        "declared_artifact_count": len(declared_artifacts),
        "missing_declared_artifacts": missing_declared,
        "commands": commands,
        "next_read": demo.get("next_read"),
        "source_hashes": {
            "demo": canonical_hash(demo),
            "status": canonical_hash(status),
            "commands": demo["source_hashes"]["commands"],
        },
        "generated_files": [
            rel(demo_dir / "demo-inspect.json"),
            rel(demo_dir / "demo-summary.md"),
        ],
        "safe_default": "read demo-summary.md before using any live adapter or public benchmark claim",
    }
    write_json_atomic(demo_dir / "demo-inspect.json", inspect, root=demo_dir)
    write_text_atomic(demo_dir / "demo-summary.md", render_inspect_summary(inspect), root=demo_dir)
    return inspect


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    cleanup_target: Path | None = None
    try:
        if kind == "unsafe-out":
            run_demo(ROOT / "out" / "not-demo" / suite_dir.name)
        elif kind == "non-owned":
            target = DEMO_ROOT / f"{suite_dir.name}-non-owned"
            cleanup_target = target
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)
            (target / "placeholder.txt").write_text("not owned\n")
            run_demo(target)
        elif kind == "inspect-missing-demo":
            target = DEMO_ROOT / f"{suite_dir.name}-inspect-missing"
            cleanup_target = target
            if target.exists():
                shutil.rmtree(target)
            prepare_out_dir(target, target.name, source=ROOT / "fixtures" / "v53" / "manifest.json")
            inspect_demo(target)
        elif kind == "inspect-stale-hash":
            target = DEMO_ROOT / f"{suite_dir.name}-inspect-stale"
            cleanup_target = target
            if target.exists():
                shutil.rmtree(target)
            run_demo(target)
            demo_path = target / "demo.json"
            demo = read_json_obj(demo_path, label="demo.json")
            demo["source_hashes"]["commands"] = "stale"
            write_json_atomic(demo_path, demo, root=target)
            write_json_atomic(target / "status.json", demo, root=target)
            inspect_demo(target)
        else:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DemoError as exc:
        if cleanup_target is not None and cleanup_target.exists():
            shutil.rmtree(cleanup_target)
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DemoError("ERR_DEMO_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "canonical-demo":
            status = run_demo(suite_dir / f"{suite_dir.name}-{fixture_id}")
        elif kind == "canonical-demo-inspect":
            target = suite_dir / f"{suite_dir.name}-{fixture_id}"
            run_demo(target)
            status = inspect_demo(target)
        elif kind in {"unsafe-out", "non-owned"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        elif kind in {"inspect-missing-demo", "inspect-stale-hash"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DemoError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_demo_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("demo_id") != suite_id:
            raise DemoError("ERR_DEMO_PATH_UNSAFE", "existing demo suite is not demo-owned", path=suite_dir)
        remove_owned_dir(suite_dir)
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
        raise DemoError("ERR_DEMO_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-demo-self-test-", dir=DEMO_ROOT) as tmp:
        suite_dir = Path(tmp) / "demo-self-test"
        target = suite_dir / "demo-self-test-canonical"
        demo = run_demo(target)
        if demo.get("status") != "demo-recorded":
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", "demo self-test did not record a canonical demo")
        inspect = inspect_demo(target)
        if inspect.get("status") != "inspect-recorded":
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", "demo self-test did not inspect the canonical demo")
        blocked_fixture_status("unsafe-out", {"expected_error": "ERR_DEMO_PATH_UNSAFE"}, suite_dir)
        blocked_fixture_status("non-owned", {"expected_error": "ERR_DEMO_PATH_UNSAFE"}, suite_dir)
        blocked_fixture_status("inspect-missing-demo", {"expected_error": "ERR_DEMO_ARTIFACT_MISSING"}, suite_dir)
        demo_path = target / "demo.json"
        status_path = target / "status.json"
        stale_demo = read_json_obj(demo_path, label="demo.json")
        stale_demo["source_hashes"]["commands"] = "stale"
        write_json_atomic(demo_path, stale_demo, root=target)
        write_json_atomic(status_path, stale_demo, root=target)
        try:
            inspect_demo(target)
        except DemoError as exc:
            if exc.code != "ERR_DEMO_STALE_HASH":
                raise
        else:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", "stale demo inspect unexpectedly passed")
        flaky_target = suite_dir / "demo-self-test-flaky-delete"
        prepare_out_dir(
            flaky_target,
            flaky_target.name,
            source=ROOT / "fixtures" / "v53" / "manifest.json",
        )
        write_json_atomic(flaky_target / "summary.json", {"stale": True}, root=flaky_target)
        original_rmtree = shutil.rmtree
        state = {"failed": False}

        def flaky_rmtree(path: Path | str, *args: Any, **kwargs: Any) -> None:
            target_path = Path(path)
            if "flaky-delete" in target_path.name and not state["failed"]:
                state["failed"] = True
                sentinel = target_path / SENTINEL
                if sentinel.exists():
                    sentinel.unlink()
                raise OSError("simulated partial rmtree")
            original_rmtree(path, *args, **kwargs)

        shutil.rmtree = flaky_rmtree
        try:
            prepare_out_dir(
                flaky_target,
                flaky_target.name,
                source=ROOT / "fixtures" / "v53" / "manifest.json",
            )
        finally:
            shutil.rmtree = original_rmtree
        if not state["failed"]:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", "flaky rmtree did not run")
        sentinel = read_sentinel(flaky_target)
        if sentinel is None or sentinel.get("demo_id") != flaky_target.name:
            raise DemoError("ERR_DEMO_FIXTURE_FAILED", "flaky delete recovery did not keep owned target")
    print("dwm_demo self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["run", "inspect"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--demo")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DemoError("ERR_DEMO_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "run":
            if not args.out:
                raise DemoError("ERR_DEMO_PATH_UNSAFE", "run requires --out")
            print(canonical_json_text(run_demo(Path(args.out))))
        elif args.command == "inspect":
            if not args.demo:
                raise DemoError("ERR_DEMO_ARTIFACT_MISSING", "inspect requires --demo")
            print(canonical_json_text(inspect_demo(Path(args.demo))))
        else:
            parser.error("expected --self-test, --manifest, run, or inspect")
    except DemoError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
