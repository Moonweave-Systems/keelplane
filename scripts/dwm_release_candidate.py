#!/usr/bin/env python3
"""V50 release candidate cut."""

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
from dwm_adapters import ADAPTER_ROOT, check_adapter_action, write_parity_matrix  # noqa: E402
from dwm_daily_operator import OPERATOR_ROOT, collect_operator_state, make_ready_corpus, write_operator_report  # noqa: E402


TOOL = "dwm_release_candidate.py"
SCHEMA_VERSION = "1.0"
RELEASE_CANDIDATE_VERSION = "50.0.0"
RELEASE_CANDIDATE_ROOT = ROOT / "out" / "release-candidates"
SENTINEL = ".dwm_release_candidate-owned.json"
FORBIDDEN_RELEASE_CLAIMS = [
    "beats codex",
    "beats claude",
    "external benchmark",
    "fully autonomous",
    "model superiority",
    "state of the art",
    "sota",
]


class ReleaseCandidateError(ValueError):
    """Structured V50 release candidate failure."""

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
        raise ReleaseCandidateError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseCandidateError(code, "path contains a symlink", path=current)


def resolve_release_candidate_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_RELEASE_CANDIDATE_PATH_UNSAFE", message="release candidate output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = RELEASE_CANDIDATE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", f"release candidate output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", "release candidate output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_RELEASE_CANDIDATE_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, candidate_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_SYMLINK", "release candidate output is a symlink", path=path)
        if not path.is_dir():
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", "release candidate output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("candidate_id") != candidate_id:
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", "existing release candidate output is not candidate-owned", path=path)
        shutil.rmtree(path)
    RELEASE_CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "release_candidate_version": RELEASE_CANDIDATE_VERSION,
            "candidate_id": candidate_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def require_json(path: Path, *, code: str, message: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReleaseCandidateError(code, message, path=path)
    data = read_json(path)
    if not isinstance(data, dict):
        raise ReleaseCandidateError(code, f"{path.name} is not an object", path=path)
    return data


def load_parity(parity_dir: Path) -> dict[str, Any]:
    matrix = require_json(parity_dir / "adapter-parity.json", code="ERR_RELEASE_CANDIDATE_PARITY_MISSING", message="adapter-parity.json is missing")
    status = require_json(parity_dir / "status.json", code="ERR_RELEASE_CANDIDATE_PARITY_MISSING", message="parity status.json is missing")
    if status.get("decision") != "parity_recorded" or matrix.get("decision") != "parity_recorded":
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PARITY_STALE", "adapter parity is not recorded", path=parity_dir)
    if status.get("parity_hash") != canonical_hash(matrix):
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PARITY_STALE", "adapter parity hash does not match status", path=parity_dir)
    for adapter in matrix.get("adapters", []):
        if adapter.get("support_level") == "planned" and adapter.get("execution_readiness") != "blocked-before-live-contract":
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PARITY_STALE", "planned adapter is not blocked before live contract", path=parity_dir)
    return matrix


def load_operator(operator_dir: Path) -> dict[str, Any]:
    report = require_json(operator_dir / "operator-loop.json", code="ERR_RELEASE_CANDIDATE_OPERATOR_MISSING", message="operator-loop.json is missing")
    status = require_json(operator_dir / "status.json", code="ERR_RELEASE_CANDIDATE_OPERATOR_MISSING", message="operator status.json is missing")
    if report != status:
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_OPERATOR_STALE", "operator status and report do not match", path=operator_dir)
    if report.get("status") != "operator-loop-recorded":
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_OPERATOR_STALE", "operator loop is not recorded", path=operator_dir)
    recommendation = report.get("recommendation")
    if not isinstance(recommendation, dict) or recommendation.get("status") not in {"ready", "blocked", "complete"}:
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_OPERATOR_STALE", "operator recommendation is invalid", path=operator_dir)
    return report


def detect_forbidden_claims(text: str) -> list[str]:
    normalized = " ".join(text.lower().split())
    return [term for term in FORBIDDEN_RELEASE_CLAIMS if term in normalized]


def render_release_notes(candidate: dict[str, Any]) -> str:
    lines = [
        "# DWM V50 Release Candidate Notes",
        "",
        f"Decision: `{candidate['decision']}`",
        "",
        "## Implemented",
        "",
    ]
    lines.extend(f"- {item}" for item in candidate["implemented"])
    lines.extend(["", "## Experimental", ""])
    lines.extend(f"- {item}" for item in candidate["experimental"])
    lines.extend(["", "## Deferred", ""])
    lines.extend(f"- {item}" for item in candidate["deferred"])
    lines.extend(["", "## Safety", "", "- No live adapter execution is claimed by this release candidate."])
    lines.append("")
    return "\n".join(lines)


def cut_release_candidate(parity_dir: Path, operator_dir: Path, out_dir: Path, *, candidate_id: str, proposed_notes: str = "") -> dict[str, Any]:
    parity = load_parity(parity_dir)
    operator = load_operator(operator_dir)
    forbidden = detect_forbidden_claims(proposed_notes)
    if forbidden:
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_OVERCLAIM", f"release notes contain unsupported claims: {', '.join(forbidden)}")
    try:
        check_adapter_action("codex", "run")
    except Exception as exc:
        codex_run_block = str(exc).split(":", 1)[0]
    else:
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PARITY_STALE", "codex run unexpectedly allowed before live contract")
    prepare_out_dir(out_dir, candidate_id, source=ROOT / "fixtures" / "v50" / "manifest.json")
    candidate = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "release_candidate_version": RELEASE_CANDIDATE_VERSION,
        "candidate_id": candidate_id,
        "status": "candidate-ready",
        "decision": "release-candidate",
        "parity_path": rel(parity_dir),
        "operator_path": rel(operator_dir),
        "operator_recommendation": operator["recommendation"],
        "codex_run_gate": codex_run_block,
        "implemented": [
            "artifact-first workflow control-plane",
            "first-slice compiler and bounded execution evidence",
            "long-run queue and daily operator loop",
            "adapter parity matrix with planned-only live adapter blocking",
        ],
        "experimental": [
            "benchmark graph promotion pipeline",
            "local dogfood comparison placeholders",
            "optional external adapter smoke surfaces",
        ],
        "deferred": [
            "public external benchmark superiority claims",
            "equivalent live Codex, Claude, and shell adapter parity",
            "unrestricted autonomous multi-slice execution",
        ],
        "source_hashes": {
            "parity": canonical_hash(parity),
            "operator": canonical_hash(operator),
        },
    }
    write_json_atomic(out_dir / "release-candidate.json", candidate, root=out_dir)
    write_json_atomic(out_dir / "status.json", candidate, root=out_dir)
    write_text_atomic(out_dir / "release-notes.md", render_release_notes(candidate), root=out_dir)
    write_text_atomic(
        out_dir / "release-checklist.md",
        "\n".join(
            [
                "# V50 Release Candidate Checklist",
                "",
                "- full contract passes before publication",
                "- README reflects implemented surfaces only",
                "- benchmark graphs require V44-V45 approval",
                "- release notes separate implemented, experimental, and deferred capabilities",
                "",
            ]
        ),
        root=out_dir,
    )
    return candidate


def make_parity_dir(base_name: str, *, stale: bool = False) -> Path:
    parity_dir = ADAPTER_ROOT / f"{base_name}-parity"
    write_parity_matrix(parity_dir)
    if stale:
        status = read_json(parity_dir / "status.json")
        status["decision"] = "stale"
        write_json_atomic(parity_dir / "status.json", status, root=parity_dir)
    return parity_dir


def make_operator_dir(base_name: str, *, stale: bool = False) -> Path:
    operator_dir = OPERATOR_ROOT / f"{base_name}-operator"
    state = collect_operator_state([make_ready_corpus(base_name)], [])
    write_operator_report(state, operator_dir, operator_id=operator_dir.name, source=Path("fixture"))
    if stale:
        status = read_json(operator_dir / "status.json")
        status["recommendation"]["status"] = "stale"
        write_json_atomic(operator_dir / "status.json", status, root=operator_dir)
    return operator_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "missing-parity":
            cut_release_candidate(suite_dir / "missing-parity", make_operator_dir(f"{suite_dir.name}-{kind}"), suite_dir / kind, candidate_id=kind)
        elif kind == "stale-parity":
            cut_release_candidate(make_parity_dir(f"{suite_dir.name}-{kind}", stale=True), make_operator_dir(f"{suite_dir.name}-{kind}"), suite_dir / kind, candidate_id=kind)
        elif kind == "stale-operator":
            cut_release_candidate(make_parity_dir(f"{suite_dir.name}-{kind}"), make_operator_dir(f"{suite_dir.name}-{kind}", stale=True), suite_dir / kind, candidate_id=kind)
        elif kind == "overclaim":
            cut_release_candidate(
                make_parity_dir(f"{suite_dir.name}-{kind}"),
                make_operator_dir(f"{suite_dir.name}-{kind}"),
                suite_dir / kind,
                candidate_id=kind,
                proposed_notes="DWM beats Codex on an external benchmark.",
            )
        else:
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except ReleaseCandidateError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "release-candidate-ready":
            status = cut_release_candidate(
                make_parity_dir(f"{suite_dir.name}-{fixture_id}"),
                make_operator_dir(f"{suite_dir.name}-{fixture_id}"),
                suite_dir / fixture_id,
                candidate_id=fixture_id,
            )
        elif kind in {"missing-parity", "stale-parity", "stale-operator", "overclaim"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except ReleaseCandidateError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_release_candidate_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("candidate_id") != suite_id:
            raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", "existing release candidate suite is not candidate-owned", path=suite_dir)
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
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    RELEASE_CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-release-candidate-self-test-", dir=RELEASE_CANDIDATE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v50" / "manifest.json", Path(tmp) / "release-candidate-self-test")
    if summary["decision"] != "keep":
        raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_FIXTURE_FAILED", "release candidate self-test manifest did not keep")
    print("dwm_release_candidate self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["cut"])
    parser.add_argument("--manifest")
    parser.add_argument("--operator")
    parser.add_argument("--out")
    parser.add_argument("--parity")
    parser.add_argument("--proposed-notes", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "cut":
            if not args.out or not args.parity or not args.operator:
                raise ReleaseCandidateError("ERR_RELEASE_CANDIDATE_PATH_UNSAFE", "cut requires --parity, --operator, and --out")
            out_dir = resolve_release_candidate_out(args.out)
            status = cut_release_candidate(Path(args.parity), Path(args.operator), out_dir, candidate_id=out_dir.name, proposed_notes=args.proposed_notes)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or cut")
    except ReleaseCandidateError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
