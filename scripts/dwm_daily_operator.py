#!/usr/bin/env python3
"""V48 daily operator loop."""

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
from dwm_dogfood_corpus import DOGFOOD_ROOT, build_corpus, default_tasks  # noqa: E402
from dwm_workflow_queue import QUEUE_ROOT, build_queue, load_queue  # noqa: E402


TOOL = "dwm_daily_operator.py"
SCHEMA_VERSION = "1.0"
OPERATOR_VERSION = "48.0.0"
OPERATOR_ROOT = ROOT / "out" / "daily-operator"
SENTINEL = ".dwm_daily_operator-owned.json"


class DailyOperatorError(ValueError):
    """Structured V48 daily operator failure."""

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
        raise DailyOperatorError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DailyOperatorError(code, "path contains a symlink", path=current)


def resolve_operator_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DAILY_OPERATOR_PATH_UNSAFE", message="operator output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = OPERATOR_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", f"operator output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", "operator output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DAILY_OPERATOR_PATH_SYMLINK")
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


def prepare_out_dir(path: Path, operator_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_SYMLINK", "operator output is a symlink", path=path)
        if not path.is_dir():
            raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", "operator output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("operator_id") != operator_id:
            raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", "existing operator output is not operator-owned", path=path)
        shutil.rmtree(path)
    OPERATOR_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "operator_version": OPERATOR_VERSION,
            "operator_id": operator_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def load_corpus(corpus_dir: Path) -> dict[str, Any]:
    corpus_path = corpus_dir / "dogfood-corpus.json"
    status_path = corpus_dir / "status.json"
    if not corpus_path.is_file() or corpus_path.is_symlink() or not status_path.is_file() or status_path.is_symlink():
        raise DailyOperatorError("ERR_DAILY_OPERATOR_CORPUS_MISSING", "dogfood corpus artifacts are missing", path=corpus_dir)
    corpus = read_json(corpus_path)
    status = read_json(status_path)
    if corpus != status:
        raise DailyOperatorError("ERR_DAILY_OPERATOR_STALE_CORPUS", "dogfood corpus status and artifact do not match", path=corpus_dir)
    if corpus.get("status") != "dogfood-corpus-recorded":
        raise DailyOperatorError("ERR_DAILY_OPERATOR_STALE_CORPUS", "dogfood corpus is not recorded", path=corpus_dir)
    queue_path = corpus.get("queue_path")
    if not isinstance(queue_path, str) or not queue_path:
        raise DailyOperatorError("ERR_DAILY_OPERATOR_QUEUE_MISSING", "dogfood corpus queue_path is missing", path=corpus_dir)
    return corpus


def summarize_queue(queue_dir: Path) -> dict[str, Any]:
    try:
        queue = load_queue(queue_dir)
    except Exception as exc:  # keep V46 errors wrapped in V48 vocabulary
        raise DailyOperatorError("ERR_DAILY_OPERATOR_STALE_QUEUE", f"queue cannot be loaded: {exc}", path=queue_dir) from exc
    next_action = queue.get("next_action", {})
    if not isinstance(next_action, dict):
        raise DailyOperatorError("ERR_DAILY_OPERATOR_STALE_QUEUE", "queue next_action is invalid", path=queue_dir)
    return {
        "queue_path": rel(queue_dir),
        "queue_id": queue.get("queue_id"),
        "status": queue.get("status"),
        "next_action": next_action,
        "summary": queue.get("summary", {}),
        "source_hash": canonical_hash(queue),
    }


def collect_operator_state(corpus_dirs: list[Path], queue_dirs: list[Path]) -> dict[str, Any]:
    corpora = []
    queue_paths: list[Path] = []
    for corpus_dir in corpus_dirs:
        corpus = load_corpus(corpus_dir)
        corpora.append(
            {
                "corpus_path": rel(corpus_dir),
                "corpus_id": corpus.get("corpus_id"),
                "task_count": corpus.get("task_count"),
                "comparison_modes": corpus.get("comparison_modes", []),
                "queue_path": corpus["queue_path"],
                "comparison_statuses": sorted({comparison.get("status") for task in corpus.get("tasks", []) for comparison in task.get("comparisons", [])}),
                "source_hash": canonical_hash(corpus),
            }
        )
        queue_paths.append(ROOT / corpus["queue_path"])
    queue_paths.extend(queue_dirs)
    seen: set[str] = set()
    queues = []
    for queue_dir in queue_paths:
        key = rel(queue_dir)
        if key in seen:
            continue
        seen.add(key)
        queues.append(summarize_queue(queue_dir))
    if not queues:
        raise DailyOperatorError("ERR_DAILY_OPERATOR_QUEUE_MISSING", "no queues were provided")
    ready = [queue for queue in queues if queue["next_action"].get("status") == "ready"]
    blocked = [queue for queue in queues if queue["next_action"].get("status") == "blocked"]
    complete = [queue for queue in queues if queue["next_action"].get("status") == "complete"]
    if ready:
        recommendation = {
            "status": "ready",
            "queue_path": ready[0]["queue_path"],
            "packet_id": ready[0]["next_action"].get("packet_id"),
            "command": ready[0]["next_action"].get("command"),
        }
    elif blocked:
        recommendation = {
            "status": "blocked",
            "queue_path": blocked[0]["queue_path"],
            "packet_id": blocked[0]["next_action"].get("packet_id"),
            "blocked_by": blocked[0]["next_action"].get("blocked_by", []),
        }
    else:
        recommendation = {"status": "complete", "queue_count": len(complete)}
    return {
        "operator_status": "operator-loop-recorded",
        "generated_at": now_utc(),
        "corpora": corpora,
        "queues": queues,
        "recommendation": recommendation,
        "freshness": {
            "corpus_count": len(corpora),
            "queue_count": len(queues),
            "ready_count": len(ready),
            "blocked_count": len(blocked),
            "complete_count": len(complete),
        },
        "source_hashes": {
            "corpora": canonical_hash(corpora),
            "queues": canonical_hash(queues),
        },
    }


def render_today(report: dict[str, Any]) -> str:
    rec = report["recommendation"]
    lines = ["# DWM Daily Operator Loop", ""]
    lines.append(f"- status: `{rec['status']}`")
    if rec.get("queue_path"):
        lines.append(f"- queue: `{rec['queue_path']}`")
    if rec.get("packet_id"):
        lines.append(f"- packet: `{rec['packet_id']}`")
    if rec.get("command"):
        lines.append(f"- command: `{rec['command']}`")
    for block in rec.get("blocked_by", []) or []:
        lines.append(f"- blocked: `{block.get('code')}` {block.get('message')}")
    lines.append("")
    lines.append("## Freshness")
    for key, value in sorted(report["freshness"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def write_operator_report(state: dict[str, Any], out_dir: Path, *, operator_id: str, source: Path) -> dict[str, Any]:
    prepare_out_dir(out_dir, operator_id, source=source)
    report = {"status": "operator-loop-recorded", "operator_id": operator_id, **state}
    write_json_atomic(out_dir / "operator-loop.json", report, root=out_dir)
    write_json_atomic(out_dir / "status.json", report, root=out_dir)
    (out_dir / "today.md").write_text(render_today(report))
    return report


def make_ready_corpus(base_name: str) -> Path:
    corpus_dir = DOGFOOD_ROOT / f"{base_name}-corpus"
    build_corpus(default_tasks(), corpus_dir, corpus_id=corpus_dir.name, source=Path("fixture"))
    return corpus_dir


def make_blocked_queue(base_name: str) -> Path:
    evidence = OPERATOR_ROOT / "fixture-evidence" / f"{base_name}.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("evidence\n")
    queue_dir = QUEUE_ROOT / f"{base_name}-blocked-queue"
    build_queue(
        [
            {
                "id": "blocked-packet",
                "title": "blocked packet",
                "command": "python scripts/dwm.py plan blocked",
                "evidence_paths": [rel(evidence)],
                "verification_status": "pass",
                "risk_codes": ["network"],
                "requires_human": False,
            }
        ],
        queue_dir,
        queue_id=queue_dir.name,
        source=Path("fixture"),
    )
    return queue_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_id: str) -> dict[str, Any]:
    try:
        if kind == "stale-queue":
            queue_dir = make_blocked_queue(f"{suite_id}-stale")
            status = read_json(queue_dir / "status.json")
            status["next_action"]["status"] = "ready"
            write_json_atomic(queue_dir / "status.json", status, root=queue_dir)
            collect_operator_state([], [queue_dir])
        elif kind == "missing-corpus":
            collect_operator_state([DOGFOOD_ROOT / f"{suite_id}-missing-corpus"], [])
        elif kind == "missing-queue":
            corpus_dir = make_ready_corpus(f"{suite_id}-missing-queue")
            corpus = read_json(corpus_dir / "dogfood-corpus.json")
            corpus["queue_path"] = "out/workflow-queues/not-present"
            write_json_atomic(corpus_dir / "dogfood-corpus.json", corpus, root=corpus_dir)
            write_json_atomic(corpus_dir / "status.json", corpus, root=corpus_dir)
            collect_operator_state([corpus_dir], [])
        else:
            raise DailyOperatorError("ERR_DAILY_OPERATOR_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DailyOperatorError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DailyOperatorError("ERR_DAILY_OPERATOR_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        if kind == "operator-ready":
            state = collect_operator_state([make_ready_corpus(f"{suite_dir.name}-{fixture_id}")], [])
            status = write_operator_report(state, suite_dir / fixture_id, operator_id=fixture_id, source=Path("fixture"))
        elif kind == "operator-blocked":
            state = collect_operator_state([], [make_blocked_queue(f"{suite_dir.name}-{fixture_id}")])
            status = write_operator_report(state, suite_dir / fixture_id, operator_id=fixture_id, source=Path("fixture"))
        elif kind in {"stale-queue", "missing-corpus", "missing-queue"}:
            status = blocked_fixture_status(kind, fixture, suite_dir.name)
        else:
            raise DailyOperatorError("ERR_DAILY_OPERATOR_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        observed_status = status.get("recommendation", {}).get("status", status.get("status"))
        if expected_status is not None and observed_status != expected_status:
            raise DailyOperatorError("ERR_DAILY_OPERATOR_FIXTURE_FAILED", f"expected status {expected_status}, got {observed_status}")
        return {"id": fixture_id, "status": "pass", "observed_status": observed_status, "required": fixture.get("required", True)}
    except DailyOperatorError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_operator_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("operator_id") != suite_id:
            raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", "existing operator suite is not operator-owned", path=suite_dir)
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
        raise DailyOperatorError("ERR_DAILY_OPERATOR_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    OPERATOR_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-daily-operator-self-test-", dir=OPERATOR_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v48" / "manifest.json", Path(tmp) / "daily-operator-self-test")
    if summary["decision"] != "keep":
        raise DailyOperatorError("ERR_DAILY_OPERATOR_FIXTURE_FAILED", "daily operator self-test manifest did not keep")
    print("dwm_daily_operator self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["today"])
    parser.add_argument("--corpus", action="append", default=[])
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--queue", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "today":
            if not args.out:
                raise DailyOperatorError("ERR_DAILY_OPERATOR_PATH_UNSAFE", "today requires --out")
            state = collect_operator_state([Path(value) for value in args.corpus], [Path(value) for value in args.queue])
            status = write_operator_report(state, resolve_operator_out(args.out), operator_id=Path(args.out).name, source=Path("operator-inputs"))
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or today")
    except DailyOperatorError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
