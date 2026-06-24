#!/usr/bin/env python3
"""V47 real dogfood task corpus recorder."""

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

from compile_workflow import canonical_hash, canonical_json_text, read_json, write_json_atomic  # noqa: E402
from dwm_workflow_queue import QUEUE_ROOT, build_queue  # noqa: E402


TOOL = "dwm_dogfood_corpus.py"
SCHEMA_VERSION = "1.0"
DOGFOOD_VERSION = "47.0.0"
DOGFOOD_ROOT = ROOT / "out" / "dogfood-corpus"
SENTINEL = ".dwm_dogfood_corpus-owned.json"
REQUIRED_MODES = ["direct-codex", "dwm-controlled"]
REQUIRED_TASK_IDS = [
    "v44-candidate-review-gate",
    "v45-readme-asset-promotion",
    "v46-workflow-queue",
    "release-contract-count-sync",
]
UNSAFE_RISK_CODES = {
    "write",
    "delete",
    "network",
    "deploy",
    "secret",
    "dependency",
    "database",
    "history-rewrite",
    "external-message",
}


class DogfoodCorpusError(ValueError):
    """Structured V47 dogfood corpus failure."""

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
        raise DogfoodCorpusError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodCorpusError(code, "path contains a symlink", path=current)


def resolve_dogfood_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_CORPUS_PATH_UNSAFE", message="dogfood corpus output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = DOGFOOD_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", f"dogfood corpus output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", "dogfood corpus output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_CORPUS_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, corpus_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_SYMLINK", "dogfood corpus output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", "dogfood corpus output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("corpus_id") != corpus_id:
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", "existing dogfood corpus output is not corpus-owned", path=path)
        shutil.rmtree(path)
    DOGFOOD_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "dogfood_version": DOGFOOD_VERSION,
            "corpus_id": corpus_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def default_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "v44-candidate-review-gate",
            "title": "Implement or verify the benchmark candidate review gate",
            "objective": "Keep README benchmark promotion blocked until candidate, promotion, series, and history hashes are reviewed.",
            "repo_paths": ["scripts/dwm_benchmark_candidate_review.py", "fixtures/v44/manifest.json", "docs/v44-candidate-review-gate-spec.md"],
            "risk_codes": [],
            "evidence_requirements": ["self-test output", "manifest summary", "contract smoke"],
            "verification_commands": ["python scripts/dwm_benchmark_candidate_review.py --self-test"],
        },
        {
            "id": "v45-readme-asset-promotion",
            "title": "Create a reviewed README asset promotion bundle",
            "objective": "Produce an asset promotion bundle without editing tracked README assets directly.",
            "repo_paths": ["scripts/dwm_readme_asset_promotion.py", "fixtures/v45/manifest.json", "docs/v45-readme-asset-promotion-spec.md"],
            "risk_codes": [],
            "evidence_requirements": ["asset-promotion.json", "asset-diff.md", "manifest summary"],
            "verification_commands": ["python scripts/dwm_readme_asset_promotion.py --self-test"],
        },
        {
            "id": "v46-workflow-queue",
            "title": "Record a long-run queue and next safe action",
            "objective": "Reduce repeated user nudges by turning ordered roadmap packets into a queue artifact.",
            "repo_paths": ["scripts/dwm_workflow_queue.py", "fixtures/v46/manifest.json", "docs/v46-long-run-workflow-queue-spec.md"],
            "risk_codes": [],
            "evidence_requirements": ["queue.json", "next-action.md", "manifest summary"],
            "verification_commands": ["python scripts/dwm_workflow_queue.py --self-test"],
        },
        {
            "id": "release-contract-count-sync",
            "title": "Keep release command count and contract docs synchronized",
            "objective": "Prevent roadmap and release text from drifting ahead of executable commands.",
            "repo_paths": ["scripts/dwm.py", "scripts/check_contract.py", "docs/v10-decision.md"],
            "risk_codes": [],
            "evidence_requirements": ["release command count", "contract self-test", "full contract smoke"],
            "verification_commands": ["python scripts/check_contract.py --self-test"],
        },
    ]


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", "task id is missing")
    for key in ["title", "objective"]:
        if not isinstance(task.get(key), str) or not task[key].strip():
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", f"{task_id} {key} is missing")
    repo_paths = task.get("repo_paths")
    evidence = task.get("evidence_requirements")
    commands = task.get("verification_commands")
    risk_codes = task.get("risk_codes", [])
    if not isinstance(repo_paths, list) or not repo_paths or not all(isinstance(item, str) and item for item in repo_paths):
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", f"{task_id} repo_paths are invalid")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_EVIDENCE_MISSING", f"{task_id} evidence requirements are missing")
    if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item for item in commands):
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", f"{task_id} verification commands are invalid")
    if not isinstance(risk_codes, list) or not all(isinstance(item, str) for item in risk_codes):
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", f"{task_id} risk_codes are invalid")
    unsafe = sorted(set(risk_codes) & UNSAFE_RISK_CODES)
    if unsafe:
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_UNSAFE_TASK", f"{task_id} contains unsafe risk codes: {', '.join(unsafe)}")
    if task.get("public_claim") is True:
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PUBLIC_CLAIM", f"{task_id} attempts to make a public benchmark claim")
    return {
        "id": task_id,
        "title": task["title"],
        "objective": task["objective"],
        "source_kind": "local-dogfood",
        "repo_paths": repo_paths,
        "risk_codes": risk_codes,
        "evidence_requirements": evidence,
        "verification_commands": commands,
        "comparisons": [
            {"mode": mode, "status": "not-run", "evidence_path": None, "metrics": {"elapsed_seconds": None, "interruptions": None, "verification_passed": None}}
            for mode in REQUIRED_MODES
        ],
    }


def validate_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(tasks, list):
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", "tasks must be a list")
    normalized = [normalize_task(task) for task in tasks]
    ids = [task["id"] for task in normalized]
    if len(ids) != len(set(ids)):
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_TASK_INVALID", "task ids must be unique")
    missing = [task_id for task_id in REQUIRED_TASK_IDS if task_id not in ids]
    if missing:
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_REQUIRED_TASK_MISSING", f"missing required dogfood tasks: {', '.join(missing)}")
    return normalized


def queue_packets(tasks: list[dict[str, Any]], evidence_path: str) -> list[dict[str, Any]]:
    return [
        {
            "id": task["id"],
            "title": task["title"],
            "command": f"python scripts/dwm.py plan \"{task['objective']}\" --out out/v21/{task['id']}",
            "evidence_paths": [evidence_path],
            "verification_status": "pass",
            "risk_codes": task["risk_codes"],
            "requires_human": False,
        }
        for task in tasks
    ]


def build_corpus(tasks: list[dict[str, Any]], out_dir: Path, *, corpus_id: str, source: Path) -> dict[str, Any]:
    normalized = validate_tasks(tasks)
    prepare_out_dir(out_dir, corpus_id, source=source)
    corpus = {
        "status": "dogfood-corpus-recorded",
        "corpus_id": corpus_id,
        "source_kind": "local-dogfood",
        "external_claim_policy": "local dogfood evidence only; not an external benchmark authority",
        "task_count": len(normalized),
        "comparison_modes": REQUIRED_MODES,
        "tasks": normalized,
        "source_hashes": {"tasks": canonical_hash(normalized)},
    }
    write_json_atomic(out_dir / "dogfood-corpus.json", corpus, root=out_dir)
    packets = queue_packets(normalized, rel(out_dir / "dogfood-corpus.json"))
    write_json_atomic(out_dir / "queue-packets.json", packets, root=out_dir)
    queue_dir = QUEUE_ROOT / f"{corpus_id}-queue"
    queue = build_queue(packets, queue_dir, queue_id=queue_dir.name, source=out_dir / "queue-packets.json")
    corpus["queue_path"] = rel(queue_dir)
    corpus["source_hashes"]["queue"] = canonical_hash(queue)
    write_json_atomic(out_dir / "dogfood-corpus.json", corpus, root=out_dir)
    write_json_atomic(out_dir / "status.json", corpus, root=out_dir)
    (out_dir / "README.md").write_text(render_readme(corpus))
    return corpus


def render_readme(corpus: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Corpus",
        "",
        f"- corpus: `{corpus['corpus_id']}`",
        f"- task count: {corpus['task_count']}",
        f"- queue: `{corpus['queue_path']}`",
        "- claim policy: local dogfood evidence only; not an external benchmark authority",
        "",
        "## Tasks",
        "",
    ]
    for task in corpus["tasks"]:
        lines.append(f"- `{task['id']}`: {task['title']}")
    lines.append("")
    return "\n".join(lines)


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    tasks = default_tasks()
    try:
        if kind == "missing-required":
            build_corpus(tasks[:-1], DOGFOOD_ROOT / f"{suite_id}-missing-required", corpus_id=f"{suite_id}-missing-required", source=Path("fixture"))
        elif kind == "unsafe-task":
            unsafe = [dict(task) for task in tasks]
            unsafe[0]["risk_codes"] = ["network"]
            build_corpus(unsafe, DOGFOOD_ROOT / f"{suite_id}-unsafe", corpus_id=f"{suite_id}-unsafe", source=Path("fixture"))
        elif kind == "public-claim":
            claimed = [dict(task) for task in tasks]
            claimed[0]["public_claim"] = True
            build_corpus(claimed, DOGFOOD_ROOT / f"{suite_id}-public-claim", corpus_id=f"{suite_id}-public-claim", source=Path("fixture"))
        elif kind == "missing-evidence-requirement":
            broken = [dict(task) for task in tasks]
            broken[0]["evidence_requirements"] = []
            build_corpus(broken, DOGFOOD_ROOT / f"{suite_id}-missing-evidence", corpus_id=f"{suite_id}-missing-evidence", source=Path("fixture"))
        else:
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodCorpusError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "corpus-recorded":
            status = build_corpus(default_tasks(), suite_dir / fixture_id, corpus_id=fixture_id, source=Path("fixture"))
        elif kind in {"missing-required", "unsafe-task", "public-claim", "missing-evidence-requirement"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except DogfoodCorpusError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_dogfood_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("corpus_id") != suite_id:
            raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", "existing dogfood corpus suite is not corpus-owned", path=suite_dir)
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
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    DOGFOOD_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-corpus-self-test-", dir=DOGFOOD_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v47" / "manifest.json", Path(tmp) / "dogfood-corpus-self-test")
    if summary["decision"] != "keep":
        raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_FIXTURE_FAILED", "dogfood corpus self-test manifest did not keep")
    print("dwm_dogfood_corpus self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["record"])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--tasks")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "record":
            if not args.out:
                raise DogfoodCorpusError("ERR_DOGFOOD_CORPUS_PATH_UNSAFE", "record requires --out")
            tasks = read_json(Path(args.tasks)) if args.tasks else default_tasks()
            status = build_corpus(tasks, resolve_dogfood_out(args.out), corpus_id=Path(args.out).name, source=Path(args.tasks) if args.tasks else Path("default-dogfood-tasks"))
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or record")
    except DogfoodCorpusError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
