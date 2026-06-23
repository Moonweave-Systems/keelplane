#!/usr/bin/env python3
"""V61 one-command dogfood evidence acquisition loop."""

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
from dwm_dogfood_chart_candidate import CHART_ROOT, create_candidate  # noqa: E402
from dwm_dogfood_measure import DEFAULT_TASK_ID, MEASURE_ROOT, measure  # noqa: E402
from dwm_dogfood_pair import PAIR_ROOT, fixture_receipt, make_pair  # noqa: E402
from dwm_dogfood_pair_series import PAIR_SERIES_ROOT, build_series, pair_dirs_from_root  # noqa: E402


TOOL = "dwm_dogfood_acquire.py"
SCHEMA_VERSION = "1.0"
ACQUIRE_VERSION = "61.0.0"
ACQUIRE_ROOT = ROOT / "out" / "dogfood-acquisitions"
SENTINEL = ".dwm_dogfood_acquire-owned.json"


class DogfoodAcquireError(ValueError):
    """Structured V61 dogfood acquisition failure."""

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
        raise DogfoodAcquireError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise DogfoodAcquireError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", message="acquisition output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = ACQUIRE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", f"acquisition output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", "acquisition output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_ACQUIRE_PATH_SYMLINK")
    return resolved


def resolve_pair_root(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_ACQUIRE_PAIR_ROOT_INVALID", message="pair root must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = PAIR_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PAIR_ROOT_INVALID", f"pair root must resolve under {root_resolved}", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_ACQUIRE_PATH_SYMLINK")
    return resolved


def safe_repo_file(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_DOGFOOD_ACQUIRE_RECEIPT_MISSING", message="direct receipt path must not contain parent traversal")
    if raw.is_absolute():
        candidate = raw
    else:
        candidate = ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_RECEIPT_MISSING", "direct receipt must stay in repo", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_DOGFOOD_ACQUIRE_PATH_SYMLINK")
    if not candidate.is_file() or candidate.is_symlink():
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_RECEIPT_MISSING", "direct receipt is missing", path=value)
    return candidate


def read_sentinel(path: Path) -> dict[str, Any] | None:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return None
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def prepare_out_dir(path: Path, acquisition_id: str, *, source: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_SYMLINK", "acquisition output is a symlink", path=path)
        if not path.is_dir():
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", "acquisition output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("acquisition_id") != acquisition_id:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", "existing acquisition output is not acquisition-owned", path=path)
        shutil.rmtree(path)
    ACQUIRE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(
        path / SENTINEL,
        {
            "tool": TOOL,
            "schema_version": SCHEMA_VERSION,
            "acquire_version": ACQUIRE_VERSION,
            "acquisition_id": acquisition_id,
            "source_path": rel(source),
            "created_at": now_utc(),
        },
        root=path,
    )


def render_waiting(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# DWM Dogfood Acquisition",
            "",
            f"- acquisition: `{record['acquisition_id']}`",
            f"- task: `{record['task_id']}`",
            f"- status: `{record['status']}`",
            f"- blocked by: `{', '.join(record['blocked_by'])}`",
            f"- measurement: `{record['measurement_path']}`",
            f"- receipt template: `{record['direct_receipt_template_path']}`",
            "- next step: run a human-gated direct Codex attempt and fill the receipt template",
            "",
        ]
    )


def render_recorded(record: dict[str, Any]) -> str:
    lines = [
        "# DWM Dogfood Acquisition",
        "",
        f"- acquisition: `{record['acquisition_id']}`",
        f"- task: `{record['task_id']}`",
        f"- status: `{record['status']}`",
        f"- decision: `{record['decision']}`",
        f"- measurement: `{record['measurement_path']}`",
        f"- pair: `{record['pair_path']}`",
        f"- series: `{record['series_path']}`",
        f"- graph ready: `{record['series_graph_ready']}`",
    ]
    if record.get("chart_candidate_path"):
        lines.append(f"- chart candidate: `{record['chart_candidate_path']}`")
    lines.extend(["- claim policy: local evidence only; no public benchmark promotion", ""])
    return "\n".join(lines)


def receipt_template(task_id: str, measurement_path: str) -> dict[str, Any]:
    receipt = fixture_receipt("replace/with/direct-codex-evidence.md", task_id=task_id)
    receipt["summary"] = "replace with a human-gated direct Codex attempt summary"
    receipt["measurement_path"] = measurement_path
    receipt["human_gate"]["approver"] = "replace-with-human-approver"
    receipt["human_gate"]["approved_at"] = now_utc()
    return receipt


def measurement_dir_for(out_dir: Path, acquisition_id: str) -> Path:
    try:
        slug = "__".join(out_dir.relative_to(ACQUIRE_ROOT).parts)
    except ValueError:
        slug = acquisition_id
    return MEASURE_ROOT / acquisition_id / f"{slug}-measure"


def write_waiting_record(out_dir: Path, acquisition_id: str, task_id: str, measurement: dict[str, Any], measurement_dir: Path) -> dict[str, Any]:
    template = receipt_template(task_id, rel(measurement_dir))
    template_path = out_dir / "direct-receipt-template.json"
    write_json_atomic(template_path, template, root=out_dir)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "acquire_version": ACQUIRE_VERSION,
        "status": "waiting-direct-receipt",
        "decision": "blocked-needs-direct-receipt",
        "acquisition_id": acquisition_id,
        "task_id": task_id,
        "measurement_path": rel(measurement_dir),
        "direct_receipt_template_path": rel(template_path),
        "blocked_by": ["ERR_DOGFOOD_ACQUIRE_DIRECT_RECEIPT_REQUIRED"],
        "source_hashes": {"measurement": canonical_hash(measurement)},
    }
    write_json_atomic(out_dir / "acquisition.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "acquisition.md", render_waiting(record), root=out_dir)
    return record


def acquire(
    out_dir: Path,
    *,
    task_id: str,
    direct_receipt: Path | None,
    pair_root: Path,
    min_pairs: int,
) -> dict[str, Any]:
    out_dir = resolve_out(out_dir)
    acquisition_id = out_dir.name
    pair_root = resolve_pair_root(pair_root)
    prepare_out_dir(out_dir, acquisition_id, source=Path("dogfood-acquire"))
    measurement_dir = measurement_dir_for(out_dir, acquisition_id)
    measurement = measure(measurement_dir, task_id=task_id)
    if direct_receipt is None:
        return write_waiting_record(out_dir, acquisition_id, task_id, measurement, measurement_dir)
    receipt_path = safe_repo_file(direct_receipt)
    pair_dir = pair_root / f"{acquisition_id}-pair"
    pair = make_pair(measurement_dir, receipt_path, pair_dir)
    series_dir = PAIR_SERIES_ROOT / f"{acquisition_id}-series"
    pairs = pair_dirs_from_root(pair_root)
    series = build_series(pairs, series_dir, series_id=series_dir.name, min_pairs=min_pairs, source=pair_root)
    chart_candidate_path = ""
    if series["graph_readiness"]["graph_ready"] is True:
        chart_dir = CHART_ROOT / f"{acquisition_id}-chart"
        create_candidate(series_dir, chart_dir, chart_id=chart_dir.name)
        chart_candidate_path = rel(chart_dir)
    record = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "acquire_version": ACQUIRE_VERSION,
        "status": "dogfood-acquisition-recorded",
        "decision": "pair-recorded-series-updated",
        "acquisition_id": acquisition_id,
        "task_id": task_id,
        "measurement_path": rel(measurement_dir),
        "pair_path": rel(pair_dir),
        "series_path": rel(series_dir),
        "series_graph_ready": series["graph_readiness"]["graph_ready"],
        "series_blocked_by": series["graph_readiness"]["blocked_by"],
        "chart_candidate_path": chart_candidate_path,
        "public_readme_ready": False,
        "safe_next_step": "collect more pairs" if not chart_candidate_path else "review chart candidate before rendering",
        "source_hashes": {
            "measurement": canonical_hash(measurement),
            "direct_receipt": canonical_hash(read_json(receipt_path)),
            "pair": canonical_hash(pair),
            "series": canonical_hash(series),
        },
    }
    write_json_atomic(out_dir / "acquisition.json", record, root=out_dir)
    write_json_atomic(out_dir / "status.json", record, root=out_dir)
    write_text_atomic(out_dir / "acquisition.md", render_recorded(record), root=out_dir)
    return record


def make_direct_receipt(suite_dir: Path, task_id: str, name: str, *, mismatch: bool = False) -> Path:
    evidence = suite_dir / f"{name}-direct-evidence.md"
    evidence.write_text(f"direct Codex evidence for {task_id}\n")
    receipt = fixture_receipt(rel(evidence), task_id=("v44-candidate-review-gate" if mismatch else task_id))
    receipt_path = suite_dir / f"{name}-direct-receipt.json"
    write_json_atomic(receipt_path, receipt, root=suite_dir)
    return receipt_path


def blocked_fixture_status(kind: str, fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    try:
        if kind == "missing-receipt":
            acquire(suite_dir / kind, task_id=DEFAULT_TASK_ID, direct_receipt=suite_dir / "missing-receipt.json", pair_root=PAIR_ROOT / suite_dir.name, min_pairs=3)
        elif kind == "task-mismatch":
            receipt = make_direct_receipt(suite_dir, DEFAULT_TASK_ID, kind, mismatch=True)
            acquire(suite_dir / kind, task_id=DEFAULT_TASK_ID, direct_receipt=receipt, pair_root=PAIR_ROOT / suite_dir.name, min_pairs=3)
        else:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"unknown blocked fixture kind: {kind}")
    except Exception as exc:
        code = getattr(exc, "code", "ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED")
        if fixture.get("expected_error") != code:
            raise
        return {"status": "blocked", "error": exc.to_record() if hasattr(exc, "to_record") else {"code": code, "message": str(exc)}}
    raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"{kind} unexpectedly passed")


def run_fixture(fixture: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    fixture_id = fixture["id"]
    try:
        kind = fixture["kind"]
        pair_root = PAIR_ROOT / suite_dir.name / fixture_id
        if pair_root.exists():
            shutil.rmtree(pair_root)
        pair_root.mkdir(parents=True, exist_ok=True)
        if kind == "waiting-template":
            status = acquire(suite_dir / fixture_id, task_id=DEFAULT_TASK_ID, direct_receipt=None, pair_root=pair_root, min_pairs=3)
        elif kind == "pair-recorded":
            receipt = make_direct_receipt(suite_dir, DEFAULT_TASK_ID, fixture_id)
            status = acquire(suite_dir / fixture_id, task_id=DEFAULT_TASK_ID, direct_receipt=receipt, pair_root=pair_root, min_pairs=3)
        elif kind == "chart-candidate-ready":
            from dwm_dogfood_pair_series import make_pair_dir

            make_pair_dir(f"{suite_dir.name}-{fixture_id}-seed-a", 0, suite_dir, task_id="v44-candidate-review-gate")
            make_pair_dir(f"{suite_dir.name}-{fixture_id}-seed-b", 1, suite_dir, task_id="v45-readme-asset-promotion")
            seed_root = PAIR_ROOT / suite_dir.name
            for seed in seed_root.iterdir():
                if seed.is_dir() and seed.name.startswith(f"{suite_dir.name}-{fixture_id}-seed-"):
                    shutil.copytree(seed, pair_root / seed.name)
            receipt = make_direct_receipt(suite_dir, "v46-workflow-queue", fixture_id)
            status = acquire(suite_dir / fixture_id, task_id="v46-workflow-queue", direct_receipt=receipt, pair_root=pair_root, min_pairs=3)
        elif kind in {"missing-receipt", "task-mismatch"}:
            status = blocked_fixture_status(kind, fixture, suite_dir)
        else:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"unknown fixture kind: {kind}")
        expected_status = fixture.get("expected_status")
        if expected_status is not None and status.get("status") != expected_status:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"expected status {expected_status}, got {status.get('status')}")
        expected_decision = fixture.get("expected_decision")
        if expected_decision is not None and status.get("decision") != expected_decision:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"expected decision {expected_decision}, got {status.get('decision')}")
        expected_chart = fixture.get("expected_chart_candidate")
        if expected_chart is not None and bool(status.get("chart_candidate_path")) is not expected_chart:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"expected chart candidate {expected_chart}, got {status.get('chart_candidate_path')}")
        expected_error = fixture.get("expected_error")
        actual_error = status.get("error", {}).get("code") if isinstance(status.get("error"), dict) else None
        if expected_error is not None and actual_error != expected_error:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", f"expected error {expected_error}, got {actual_error}")
        return {"id": fixture_id, "status": "pass", "observed_status": status.get("status"), "required": fixture.get("required", True)}
    except Exception as exc:
        code = getattr(exc, "code", "ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED")
        record = exc.to_record() if hasattr(exc, "to_record") else {"code": code, "message": str(exc)}
        record["fixture_id"] = fixture_id
        return {"id": fixture_id, "status": "fail", "required": fixture.get("required", True), "error": record}


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_out(out_dir)
    if suite_dir.exists():
        sentinel = read_sentinel(suite_dir)
        if sentinel is None or sentinel.get("acquisition_id") != suite_id:
            raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", "existing acquisition suite is not acquisition-owned", path=suite_dir)
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
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    ACQUIRE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwm-dogfood-acquire-self-test-", dir=ACQUIRE_ROOT) as tmp:
        summary = evaluate_manifest(ROOT / "fixtures" / "v61" / "manifest.json", Path(tmp) / "dogfood-acquire-self-test")
    if summary["decision"] != "keep":
        raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_FIXTURE_FAILED", "dogfood acquire self-test manifest did not keep")
    print("dwm_dogfood_acquire self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["acquire"])
    parser.add_argument("--direct-receipt")
    parser.add_argument("--manifest")
    parser.add_argument("--min-pairs", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--pair-root", default="out/dogfood-pairs")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text({key: summary[key] for key in ["suite_id", "fixture_count", "required_fixture_count", "required_passed", "passed", "failed", "skipped", "decision"]}))
        elif args.command == "acquire":
            if not args.out:
                raise DogfoodAcquireError("ERR_DOGFOOD_ACQUIRE_PATH_UNSAFE", "acquire requires --out")
            print(canonical_json_text(acquire(Path(args.out), task_id=args.task_id, direct_receipt=Path(args.direct_receipt) if args.direct_receipt else None, pair_root=Path(args.pair_root), min_pairs=args.min_pairs)))
        else:
            parser.error("expected --self-test, --manifest, or acquire")
    except Exception as exc:
        if hasattr(exc, "to_record"):
            print(canonical_json_text(exc.to_record()), file=sys.stderr)
        else:
            print(canonical_json_text({"code": "ERR_DOGFOOD_ACQUIRE_FAILED", "message": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
