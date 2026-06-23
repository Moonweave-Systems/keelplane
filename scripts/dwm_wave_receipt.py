#!/usr/bin/env python3
"""V99 wave receipt from selected wave and dogfood acquisition evidence."""

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


TOOL = "dwm_wave_receipt.py"
RECEIPT_VERSION = "99.0.0"
RECEIPT_ROOT = ROOT / "out" / "wave-receipts"
SENTINEL = ".dwm_wave_receipt-owned.json"
DEFAULT_WAVE = ROOT / "out" / "wave-operators" / "v98-canonical" / "wave-operator.json"
DEFAULT_ACQUISITION = ROOT / "out" / "dogfood-acquisitions" / "v61-final" / "summary.json"


class WaveReceiptError(ValueError):
    """Structured V99 wave receipt failure."""

    def __init__(self, code: str, message: str, *, path: Path | str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
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
        raise WaveReceiptError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise WaveReceiptError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WAVE_RECEIPT_PATH_UNSAFE", message="receipt output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = RECEIPT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WaveReceiptError("ERR_WAVE_RECEIPT_PATH_UNSAFE", f"receipt output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise WaveReceiptError("ERR_WAVE_RECEIPT_PATH_UNSAFE", "receipt output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_WAVE_RECEIPT_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WAVE_RECEIPT_INPUT_UNSAFE", message="receipt input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise WaveReceiptError("ERR_WAVE_RECEIPT_INPUT_UNSAFE", "receipt input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_WAVE_RECEIPT_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise WaveReceiptError("ERR_WAVE_RECEIPT_INPUT_MISSING", "receipt input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, receipt_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise WaveReceiptError("ERR_WAVE_RECEIPT_PATH_SYMLINK", "receipt output is a symlink", path=path)
        if not path.is_dir():
            raise WaveReceiptError("ERR_WAVE_RECEIPT_PATH_UNSAFE", "receipt output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("receipt_id") != receipt_id:
            raise WaveReceiptError("ERR_WAVE_RECEIPT_PATH_UNSAFE", "existing receipt output is not receipt-owned", path=path)
        shutil.rmtree(path)
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(path / SENTINEL, {"tool": TOOL, "receipt_version": RECEIPT_VERSION, "receipt_id": receipt_id, "source_path": str(source), "created_at": now_utc()}, root=path)


def selected_wave_id(wave: dict[str, Any]) -> str:
    selected = wave.get("selected_wave")
    if isinstance(selected, dict):
        return str(selected.get("id", ""))
    return ""


def make_receipt(receipt_id: str, wave: dict[str, Any], acquisition: dict[str, Any], *, source_paths: dict[str, str] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if wave.get("tool") != "dwm_wave_operator.py":
        blockers.append({"code": "ERR_WAVE_RECEIPT_WAVE_TOOL_INVALID", "message": "wave input was not produced by V98"})
    if wave.get("decision") != "wave_ready":
        blockers.append({"code": "ERR_WAVE_RECEIPT_WAVE_NOT_READY", "message": "wave operator is not ready", "decision": wave.get("decision")})
    if selected_wave_id(wave) != "dogfood-evidence-wave":
        blockers.append({"code": "ERR_WAVE_RECEIPT_WAVE_MISMATCH", "message": "selected wave is not dogfood evidence", "selected_wave": selected_wave_id(wave)})
    if acquisition.get("tool") not in {None, "dwm_dogfood_acquire.py"} and acquisition.get("suite_id") is None:
        blockers.append({"code": "ERR_WAVE_RECEIPT_ACQUISITION_TOOL_INVALID", "message": "acquisition input is not recognized"})
    if acquisition.get("decision") != "keep":
        blockers.append({"code": "ERR_WAVE_RECEIPT_ACQUISITION_NOT_KEEP", "message": "dogfood acquisition did not keep", "decision": acquisition.get("decision")})
    if int(acquisition.get("required_passed", 0)) <= 0:
        blockers.append({"code": "ERR_WAVE_RECEIPT_ACQUISITION_EMPTY", "message": "dogfood acquisition has no passed required fixtures"})
    public_claim_allowed = False
    return {
        "schema_version": RECEIPT_VERSION,
        "tool": TOOL,
        "receipt_id": receipt_id,
        "decision": "blocked" if blockers else "wave_receipt_ready",
        "selected_wave": selected_wave_id(wave),
        "acquisition_decision": acquisition.get("decision"),
        "acquisition_fixture_count": acquisition.get("fixture_count"),
        "acquisition_required_passed": acquisition.get("required_passed"),
        "public_benchmark_publish_allowed": public_claim_allowed,
        "blocked_by": blockers,
        "next_step": "continue dogfood evidence acquisition" if not blockers else "repair wave or acquisition evidence",
        "claim_policy": {
            "wave_receipt_is_public_benchmark": False,
            "requires_promotion_for_public_graph": True,
            "requires_human_review_for_readme_publication": True,
        },
        "execution_policy": {"executes_commands": False, "creates_worktrees": False, "uses_network": False},
        "source_paths": source_paths or {},
        "source_hashes": {"wave_operator": canonical_hash(wave), "dogfood_acquisition": canonical_hash(acquisition)},
    }


def render_markdown(receipt: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Wave Receipt",
            "",
            f"- Decision: `{receipt['decision']}`",
            f"- Selected wave: `{receipt['selected_wave']}`",
            f"- Acquisition decision: `{receipt['acquisition_decision']}`",
            f"- Required passed: `{receipt['acquisition_required_passed']}`",
            f"- Public benchmark publish allowed: `{receipt['public_benchmark_publish_allowed']}`",
            f"- Next step: `{receipt['next_step']}`",
            "",
            "This receipt is source-only. It does not execute commands or publish benchmark claims.",
            "Public benchmark graph publication still requires promotion evidence and human review.",
            "",
        ]
    )


def write_receipt(out_dir: Path, receipt: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "wave-receipt.json", receipt, root=out_dir)
    write_json_atomic(out_dir / "status.json", receipt, root=out_dir)
    write_text_atomic(out_dir / "wave-receipt.md", render_markdown(receipt), root=out_dir)


def receipt_from_files(wave_path: Path, acquisition_path: Path, out_dir: Path) -> dict[str, Any]:
    wave_resolved = resolve_input(wave_path)
    acquisition_resolved = resolve_input(acquisition_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=wave_resolved)
    receipt = make_receipt(
        out_dir.name,
        read_json(wave_resolved),
        read_json(acquisition_resolved),
        source_paths={"wave_operator": rel(wave_resolved), "dogfood_acquisition": rel(acquisition_resolved)},
    )
    write_receipt(out_dir, receipt)
    if receipt["decision"] != "wave_receipt_ready":
        raise WaveReceiptError("ERR_WAVE_RECEIPT_BLOCKED", "wave receipt is blocked", path=out_dir)
    return receipt


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise WaveReceiptError("ERR_WAVE_RECEIPT_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        receipt = make_receipt(
            fixture_id,
            fixture.get("wave") if isinstance(fixture.get("wave"), dict) else {},
            fixture.get("acquisition") if isinstance(fixture.get("acquisition"), dict) else {},
        )
        write_receipt(fixture_out, receipt)
        errors: list[str] = []
        if fixture.get("expected_decision") is not None and fixture["expected_decision"] != receipt["decision"]:
            errors.append(f"expected {fixture['expected_decision']}, got {receipt['decision']}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": receipt["decision"], "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": RECEIPT_VERSION,
        "tool": TOOL,
        "suite_id": str(manifest.get("suite_id", "v99-wave-receipt")),
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
        raise WaveReceiptError("ERR_WAVE_RECEIPT_FIXTURE_FAILED", "required wave receipt fixture failed", path=manifest_path)
    return summary


def sample_wave(*, decision: str = "wave_ready", selected: str = "dogfood-evidence-wave") -> dict[str, Any]:
    return {"tool": "dwm_wave_operator.py", "decision": decision, "selected_wave": {"id": selected}}


def sample_acquisition(*, decision: str = "keep", required_passed: int = 5) -> dict[str, Any]:
    return {"suite_id": "v61-final", "decision": decision, "fixture_count": 5, "required_passed": required_passed}


def self_test() -> None:
    ready = make_receipt("self-test", sample_wave(), sample_acquisition())
    if ready["decision"] != "wave_receipt_ready":
        raise ValueError("ready wave and acquisition should produce receipt")
    blocked_wave = make_receipt("self-test-blocked-wave", sample_wave(decision="blocked"), sample_acquisition())
    if blocked_wave["decision"] != "blocked":
        raise ValueError("blocked wave should block receipt")
    blocked_acquisition = make_receipt("self-test-blocked-acquisition", sample_wave(), sample_acquisition(decision="kill"))
    if blocked_acquisition["decision"] != "blocked":
        raise ValueError("blocked acquisition should block receipt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    record = subparsers.add_parser("record")
    record.add_argument("--wave", type=Path, default=DEFAULT_WAVE)
    record.add_argument("--acquisition", type=Path, default=DEFAULT_ACQUISITION)
    record.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("wave receipt self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise WaveReceiptError("ERR_WAVE_RECEIPT_OUT_REQUIRED", "--out is required with --manifest")
            print(json.dumps(run_manifest(args.manifest, args.out), sort_keys=True))
            return
        if args.command == "record":
            receipt = receipt_from_files(args.wave, args.acquisition, args.out)
            print(json.dumps({"decision": receipt["decision"], "receipt_id": receipt["receipt_id"], "selected_wave": receipt["selected_wave"]}, sort_keys=True))
            return
        raise WaveReceiptError("ERR_WAVE_RECEIPT_COMMAND_REQUIRED", "use --self-test, --manifest, or record")
    except WaveReceiptError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
