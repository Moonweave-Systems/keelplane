#!/usr/bin/env python3
"""V62/V63 dogfood acquisition operator."""

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
from dwm_dogfood_acquire import ACQUIRE_ROOT  # noqa: E402
from dwm_dogfood_corpus import default_tasks  # noqa: E402
from dwm_dogfood_pair import PAIR_ROOT  # noqa: E402


TOOL = "dwm_dogfood_operator.py"
SCHEMA_VERSION = "1.0"
OPERATOR_VERSION = "63.0.0"
OPERATOR_ROOT = ROOT / "out" / "dogfood-operator"
SENTINEL = ".dwm_dogfood_operator-owned.json"


class DogfoodOperatorError(ValueError):
    """Structured V62 dogfood acquisition operator failure."""

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
        raise DogfoodOperatorError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodOperatorError(code, "path contains a symlink", path=current)


def resolve_under(value: str | Path, root: Path, *, code: str, label: str) -> Path:
    raw = Path(value)
    reject_traversal(raw, code=code, message=f"{label} path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodOperatorError(code, f"{label} must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_OPERATOR_PATH_SYMLINK")
    return resolved


def resolve_out(value: str | Path) -> Path:
    path = resolve_under(value, OPERATOR_ROOT, code="ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", label="operator output")
    if path == OPERATOR_ROOT.resolve(strict=False):
        raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", "operator output must name a directory", path=value)
    return path


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
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_SYMLINK", "operator output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", "operator output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("operator_id") != operator_id:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", "existing operator output is not operator-owned", path=path)
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


def scan_pairs(pair_root: Path) -> dict[str, Any]:
    pair_root = resolve_under(pair_root, PAIR_ROOT, code="ERR_DOGFOOD_OPERATOR_PAIR_ROOT_INVALID", label="pair root")
    pairs = []
    if pair_root.is_dir() and not pair_root.is_symlink():
        for pair_dir in sorted(path for path in pair_root.iterdir() if path.is_dir() and not path.is_symlink()):
            pair_path = pair_dir / "comparison-pair.json"
            if not pair_path.is_file():
                continue
            if pair_path.is_symlink():
                continue
            if any(part.startswith(".") for part in pair_path.relative_to(pair_root).parts):
                continue
            status_path = pair_dir / "pair-status.json"
            if not status_path.is_file() or status_path.is_symlink():
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_PAIR", "pair status is missing", path=pair_dir)
            pair = read_json(pair_path)
            status = read_json(status_path)
            if pair != status:
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_PAIR", "pair artifact and status differ", path=pair_dir)
            if pair.get("status") != "dogfood-comparison-pair-recorded":
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_PAIR", "pair is not recorded", path=pair_dir)
            task_id = pair.get("task_id")
            if isinstance(task_id, str) and task_id:
                pairs.append({"task_id": task_id, "pair_path": rel(pair_dir), "source_hash": canonical_hash(pair)})
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair["task_id"]] = counts.get(pair["task_id"], 0) + 1
    return {
        "root": rel(pair_root),
        "pairs": pairs,
        "task_ids": sorted(counts),
        "duplicate_task_ids": sorted(task_id for task_id, count in counts.items() if count > 1),
    }


def scan_acquisitions(acquisition_root: Path) -> dict[str, Any]:
    acquisition_root = resolve_under(acquisition_root, ACQUIRE_ROOT, code="ERR_DOGFOOD_OPERATOR_ACQUISITION_ROOT_INVALID", label="acquisition root")
    waiting = []
    recorded = []
    if acquisition_root.is_dir() and not acquisition_root.is_symlink():
        for acquisition_dir in sorted(path for path in acquisition_root.iterdir() if path.is_dir() and not path.is_symlink()):
            acquisition_path = acquisition_dir / "acquisition.json"
            if not acquisition_path.is_file():
                continue
            if acquisition_path.is_symlink():
                continue
            if any(part.startswith(".") for part in acquisition_path.relative_to(acquisition_root).parts):
                continue
            status_path = acquisition_dir / "status.json"
            if not status_path.is_file() or status_path.is_symlink():
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_ACQUISITION", "acquisition status is missing", path=acquisition_dir)
            acquisition = read_json(acquisition_path)
            status = read_json(status_path)
            if acquisition != status:
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_ACQUISITION", "acquisition artifact and status differ", path=acquisition_dir)
            task_id = acquisition.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_ACQUISITION", "acquisition task_id is missing", path=acquisition_dir)
            item = {
                "task_id": task_id,
                "acquisition_path": rel(acquisition_dir),
                "decision": acquisition.get("decision"),
                "status": acquisition.get("status"),
                "source_hash": canonical_hash(acquisition),
            }
            if acquisition.get("status") == "waiting-direct-receipt":
                template_path = acquisition.get("direct_receipt_template_path")
                if not isinstance(template_path, str) or not template_path:
                    raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_ACQUISITION", "waiting acquisition has no receipt template", path=acquisition_dir)
                item["direct_receipt_template_path"] = template_path
                waiting.append(item)
            elif acquisition.get("status") == "dogfood-acquisition-recorded":
                recorded.append(item)
            else:
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_STALE_ACQUISITION", "unknown acquisition status", path=acquisition_dir)
    return {
        "root": rel(acquisition_root),
        "waiting": waiting,
        "recorded": recorded,
        "waiting_task_ids": sorted({item["task_id"] for item in waiting}),
        "recorded_task_ids": sorted({item["task_id"] for item in recorded}),
    }


def acquisition_command(operator_id: str, task_id: str) -> str:
    return f"python scripts/dwm_dogfood_acquire.py acquire --task-id {task_id} --out out/dogfood-acquisitions/{operator_id}-{task_id}"


def decide_next(pair_state: dict[str, Any], acquisition_state: dict[str, Any], *, operator_id: str, min_pairs: int) -> dict[str, Any]:
    tasks = [task["id"] for task in default_tasks()]
    completed = set(pair_state["task_ids"])
    duplicate_task_ids = pair_state.get("duplicate_task_ids", [])
    waiting = acquisition_state["waiting"]
    if waiting:
        first = sorted(waiting, key=lambda item: (item["task_id"], item["acquisition_path"]))[0]
        return {
            "status": "waiting-direct-receipt",
            "decision": "fill-existing-direct-receipt",
            "task_id": first["task_id"],
            "command": "",
            "blocked_by": ["ERR_DOGFOOD_OPERATOR_DIRECT_RECEIPT_REQUIRED"],
            "direct_receipt_template_path": first["direct_receipt_template_path"],
            "acquisition_path": first["acquisition_path"],
            "safe_next_step": "fill the existing direct receipt template before starting another acquisition",
        }
    if len(completed) >= min_pairs and duplicate_task_ids:
        return {
            "status": "blocked-duplicate-pair-root",
            "decision": "resolve-duplicate-pair-root",
            "task_id": "",
            "command": "",
            "blocked_by": ["ERR_DOGFOOD_OPERATOR_DUPLICATE_TASK"],
            "duplicate_task_ids": duplicate_task_ids,
            "safe_next_step": "choose one pair per task or use a clean pair root before building graph-ready series",
        }
    if len(completed) >= min_pairs:
        return {
            "status": "graph-ready-local-review",
            "decision": "review-existing-series-before-more-acquisition",
            "task_id": "",
            "command": "",
            "blocked_by": [],
            "safe_next_step": "build or review the local pair series before collecting more pairs",
        }
    remaining = [task_id for task_id in tasks if task_id not in completed]
    if remaining:
        task_id = remaining[0]
        return {
            "status": "ready",
            "decision": "acquire-next-task",
            "task_id": task_id,
            "command": acquisition_command(operator_id, task_id),
            "blocked_by": [],
            "safe_next_step": "run the acquisition command; it will stop for a human-gated direct receipt",
        }
    return {
        "status": "complete",
        "decision": "all-corpus-tasks-have-pairs",
        "task_id": "",
        "command": "",
        "blocked_by": [],
        "safe_next_step": "review series and chart artifacts; do not claim public benchmark superiority",
    }


def render_operator(record: dict[str, Any]) -> str:
    recommendation = record["recommendation"]
    lines = [
        "# DWM Dogfood Operator",
        "",
        f"- operator: `{record['operator_id']}`",
        f"- status: `{recommendation['status']}`",
        f"- decision: `{recommendation['decision']}`",
        f"- completed pair tasks: `{record['summary']['completed_pair_count']}`",
        f"- waiting acquisitions: `{record['summary']['waiting_acquisition_count']}`",
    ]
    if recommendation.get("task_id"):
        lines.append(f"- task: `{recommendation['task_id']}`")
    if recommendation.get("command"):
        lines.append(f"- command: `{recommendation['command']}`")
    if recommendation.get("direct_receipt_template_path"):
        lines.append(f"- direct receipt template: `{recommendation['direct_receipt_template_path']}`")
    for block in recommendation.get("blocked_by", []):
        lines.append(f"- blocked by: `{block}`")
    lines.extend(["- claim policy: local dogfood operator only; no public benchmark promotion", ""])
    return "\n".join(lines)


def recommend(out_dir: Path, *, pair_root: Path, acquisition_root: Path, min_pairs: int) -> dict[str, Any]:
    if min_pairs < 1:
        raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_MIN_PAIRS_INVALID", "min_pairs must be positive")
    out_dir = resolve_out(out_dir)
    operator_id = out_dir.name
    pair_state = scan_pairs(pair_root)
    acquisition_state = scan_acquisitions(acquisition_root)
    recommendation = decide_next(pair_state, acquisition_state, operator_id=operator_id, min_pairs=min_pairs)
    prepare_out_dir(out_dir, operator_id, source=Path("dogfood-operator-inputs"))
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "operator_version": OPERATOR_VERSION,
        "status": "dogfood-operator-recorded",
        "operator_id": operator_id,
        "recommendation": recommendation,
        "summary": {
            "task_count": len(default_tasks()),
            "completed_pair_count": len(pair_state["task_ids"]),
            "waiting_acquisition_count": len(acquisition_state["waiting"]),
            "recorded_acquisition_count": len(acquisition_state["recorded"]),
            "duplicate_task_count": len(pair_state.get("duplicate_task_ids", [])),
            "min_pairs": min_pairs,
        },
        "pair_state": pair_state,
        "acquisition_state": acquisition_state,
        "source_hashes": {
            "pair_state": canonical_hash(pair_state),
            "acquisition_state": canonical_hash(acquisition_state),
        },
        "public_readme_ready": False,
    }
    write_json_atomic(out_dir / "dogfood-operator.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "dogfood-operator.md", render_operator(record), root=out_dir)
    return record


def make_pair_record(pair_root: Path, pair_id: str, task_id: str) -> Path:
    pair_dir = pair_root / pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    pair = {
        "status": "dogfood-comparison-pair-recorded",
        "pair_id": pair_id,
        "task_id": task_id,
        "public_graph_ready": False,
        "dwm_controlled": {"metrics": {"verification_passed": True, "elapsed_seconds": 1.0, "interruptions": 0}},
        "direct_codex": {"metrics": {"verification_passed": True, "elapsed_seconds": 2.0, "interruptions": 0}},
    }
    write_json_atomic(pair_dir / "comparison-pair.json", pair, root=pair_dir)
    write_json_atomic(pair_dir / "pair-status.json", pair, root=pair_dir)
    return pair_dir


def make_waiting_acquisition(acquisition_root: Path, acquisition_id: str, task_id: str) -> Path:
    acquisition_dir = acquisition_root / acquisition_id
    acquisition_dir.mkdir(parents=True, exist_ok=True)
    template = acquisition_dir / "direct-receipt-template.json"
    write_json_atomic(template, {"task_id": task_id, "mode": "direct-codex"}, root=acquisition_dir)
    acquisition = {
        "status": "waiting-direct-receipt",
        "decision": "blocked-needs-direct-receipt",
        "acquisition_id": acquisition_id,
        "task_id": task_id,
        "direct_receipt_template_path": rel(template),
        "blocked_by": ["ERR_DOGFOOD_ACQUIRE_DIRECT_RECEIPT_REQUIRED"],
    }
    write_json_atomic(acquisition_dir / "acquisition.json", acquisition, root=acquisition_dir)
    write_json_atomic(acquisition_dir / "status.json", acquisition, root=acquisition_dir)
    return acquisition_dir


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "stale-pair":
            pair_root = PAIR_ROOT / suite_dir.name / kind
            make_pair_record(pair_root, "stale-pair", "v44-candidate-review-gate")
            status = read_json(pair_root / "stale-pair" / "pair-status.json")
            status["pair_id"] = "different"
            write_json_atomic(pair_root / "stale-pair" / "pair-status.json", status, root=pair_root / "stale-pair")
            recommend(suite_dir / kind, pair_root=pair_root, acquisition_root=ACQUIRE_ROOT / suite_dir.name / kind, min_pairs=3)
        elif kind == "stale-acquisition":
            acquisition_root = ACQUIRE_ROOT / suite_dir.name / kind
            make_waiting_acquisition(acquisition_root, "stale-acquisition", "v44-candidate-review-gate")
            status_path = acquisition_root / "stale-acquisition" / "status.json"
            status = read_json(status_path)
            status["task_id"] = "different"
            write_json_atomic(status_path, status, root=status_path.parent)
            recommend(suite_dir / kind, pair_root=PAIR_ROOT / suite_dir.name / kind, acquisition_root=acquisition_root, min_pairs=3)
        else:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except DogfoodOperatorError as exc:
        if fixture.get("expected_error") != exc.code:
            raise
        return {"status": "blocked", "error": exc.to_record()}
    raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        pair_root = PAIR_ROOT / suite_dir.name / fixture_id
        acquisition_root = ACQUIRE_ROOT / suite_dir.name / fixture_id
        if pair_root.exists():
            shutil.rmtree(pair_root)
        if acquisition_root.exists():
            shutil.rmtree(acquisition_root)
        if kind == "ready-next-task":
            status = recommend(suite_dir / fixture_id, pair_root=pair_root, acquisition_root=acquisition_root, min_pairs=3)
        elif kind == "waiting-receipt":
            make_waiting_acquisition(acquisition_root, "waiting-receipt", "v44-candidate-review-gate")
            status = recommend(suite_dir / fixture_id, pair_root=pair_root, acquisition_root=acquisition_root, min_pairs=3)
        elif kind == "graph-ready":
            for index, task_id in enumerate(["v44-candidate-review-gate", "v45-readme-asset-promotion", "v46-workflow-queue"]):
                make_pair_record(pair_root, f"pair-{index}", task_id)
            status = recommend(suite_dir / fixture_id, pair_root=pair_root, acquisition_root=acquisition_root, min_pairs=3)
        elif kind == "duplicate-pair-root":
            for index, task_id in enumerate(["v44-candidate-review-gate", "v45-readme-asset-promotion", "v46-workflow-queue", "v44-candidate-review-gate"]):
                make_pair_record(pair_root, f"pair-{index}", task_id)
            status = recommend(suite_dir / fixture_id, pair_root=pair_root, acquisition_root=acquisition_root, min_pairs=3)
        elif kind in {"stale-pair", "stale-acquisition"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        recommendation = status.get("recommendation", {})
        expected_status = fixture.get("expected_recommendation_status")
        if expected_status is not None and recommendation.get("status") != expected_status:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", f"expected recommendation status {expected_status}, got {recommendation.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and recommendation.get("decision") != expected_decision:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", f"expected decision {expected_decision}, got {recommendation.get('decision')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": recommendation.get("status", status.get("status")), "required": fixture.get("required", True)}
    except DogfoodOperatorError as exc:
        record = exc.to_record()
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("operator_id") != suite_id:
            raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", "existing operator suite is not operator-owned", path=suite_dir)
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
        raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    OPERATOR_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-operator-self-test-", dir=OPERATOR_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v63" / "manifest.json", Path(tmp) / "dogfood-operator-self-test")
    if summary["decision"] != "keep":
        raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_FIXTURE_FAILED", "dogfood operator self-test manifest did not keep")
    print("dwm_dogfood_operator self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["recommend"])
    parser.add_argument("--acquisition-root", default="out/dogfood-acquisitions")
    parser.add_argument("--manifest")
    parser.add_argument("--min-pairs", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--pair-root", default="out/dogfood-pairs")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "recommend":
            if not args.out:
                raise DogfoodOperatorError("ERR_DOGFOOD_OPERATOR_PATH_UNSAFE", "recommend requires --out")
            status = recommend(Path(args.out), pair_root=Path(args.pair_root), acquisition_root=Path(args.acquisition_root), min_pairs=args.min_pairs)
            print(canonical_json_text(status))
        else:
            parser.error("expected --self-test, --manifest, or recommend")
    except DogfoodOperatorError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
