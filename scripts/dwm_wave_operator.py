#!/usr/bin/env python3
"""V98 next-wave operator from benchmark readiness and activation evidence."""

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
from dwm_command_safety import assess_command_safety  # noqa: E402


TOOL = "dwm_wave_operator.py"
WAVE_VERSION = "98.0.0"
WAVE_ROOT = ROOT / "out" / "wave-operators"
SENTINEL = ".dwm_wave_operator-owned.json"
DEFAULT_READINESS = ROOT / "out" / "benchmark-readiness" / "v97-canonical" / "benchmark-readiness.json"
DEFAULT_ACTIVATION = ROOT / "out" / "workflow-activations" / "v90-canonical" / "workflow-activation.json"


class WaveOperatorError(ValueError):
    """Structured V98 wave-operator failure."""

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
        raise WaveOperatorError(code, message, path=path)


def check_components_not_symlink(path: Path, *, code: str) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise WaveOperatorError(code, "path contains a symlink", path=current)


def resolve_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WAVE_OPERATOR_PATH_UNSAFE", message="wave output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = WAVE_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WaveOperatorError("ERR_WAVE_OPERATOR_PATH_UNSAFE", f"wave output must resolve under {root_resolved}", path=value) from exc
    if resolved == root_resolved:
        raise WaveOperatorError("ERR_WAVE_OPERATOR_PATH_UNSAFE", "wave output must name a directory", path=value)
    check_components_not_symlink(candidate, code="ERR_WAVE_OPERATOR_PATH_SYMLINK")
    return resolved


def resolve_input(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal(raw, code="ERR_WAVE_OPERATOR_INPUT_UNSAFE", message="wave input path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError as exc:
        raise WaveOperatorError("ERR_WAVE_OPERATOR_INPUT_UNSAFE", "wave input must resolve inside this repository", path=value) from exc
    check_components_not_symlink(candidate, code="ERR_WAVE_OPERATOR_PATH_SYMLINK")
    if not resolved.is_file() or resolved.is_symlink():
        raise WaveOperatorError("ERR_WAVE_OPERATOR_INPUT_MISSING", "wave input is missing or unsafe", path=value)
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


def prepare_out_dir(path: Path, wave_id: str, *, source: Path | str) -> None:
    if path.exists():
        if path.is_symlink():
            raise WaveOperatorError("ERR_WAVE_OPERATOR_PATH_SYMLINK", "wave output is a symlink", path=path)
        if not path.is_dir():
            raise WaveOperatorError("ERR_WAVE_OPERATOR_PATH_UNSAFE", "wave output is not a directory", path=path)
        sentinel = read_sentinel(path)
        if sentinel is None or sentinel.get("wave_id") != wave_id:
            raise WaveOperatorError("ERR_WAVE_OPERATOR_PATH_UNSAFE", "existing wave output is not wave-owned", path=path)
        shutil.rmtree(path)
    WAVE_ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True)
    write_json_atomic(path / SENTINEL, {"tool": TOOL, "wave_version": WAVE_VERSION, "wave_id": wave_id, "source_path": str(source), "created_at": now_utc()}, root=path)


def default_wave_candidates() -> list[dict[str, Any]]:
    return [
        {
            "id": "dogfood-evidence-wave",
            "objective": "Acquire more real local dogfood evidence before any public benchmark graph promotion.",
            "priority": 100,
            "command": "python scripts/dwm_dogfood_acquire.py --manifest fixtures/v61/manifest.json --out out/dogfood-acquisitions/v61-final",
            "risk_codes": ["read-only", "evidence"],
            "exit_criteria": [
                "new dogfood acquisition summary exists",
                "claim limits still block public benchmark publication",
                "source files remain unchanged except intentional release docs",
            ],
        },
        {
            "id": "control-plane-hardening-wave",
            "objective": "Harden the control-plane evidence chain before live adapter execution expands.",
            "priority": 80,
            "command": "python scripts/check_contract.py --tier changed",
            "risk_codes": ["read-only", "evidence"],
            "exit_criteria": [
                "changed-surface contract passes",
                "V88-V98 evidence chain remains source-hash coherent",
                "no README benchmark publication approval is inferred",
            ],
        },
        {
            "id": "benchmark-promotion-human-gate",
            "objective": "Prepare human review for README benchmark publication only after promotion evidence exists.",
            "priority": 10,
            "command": "",
            "risk_codes": ["human-gate", "publish"],
            "exit_criteria": [
                "human approval exists",
                "promotion receipt exists",
                "README publication diff is reviewed before tracking",
            ],
        },
    ]


def readiness_blockers(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if readiness.get("tool") != "dwm_benchmark_readiness.py":
        blockers.append({"code": "ERR_WAVE_OPERATOR_READINESS_TOOL_INVALID", "message": "readiness input was not produced by V97"})
    if readiness.get("decision") != "benchmark_readiness_recorded":
        blockers.append({"code": "ERR_WAVE_OPERATOR_READINESS_BLOCKED", "message": "benchmark readiness is blocked", "decision": readiness.get("decision")})
    policy = readiness.get("claim_policy") if isinstance(readiness.get("claim_policy"), dict) else {}
    if policy.get("readiness_score_is_public_benchmark") is not False:
        blockers.append({"code": "ERR_WAVE_OPERATOR_CLAIM_POLICY_UNSAFE", "message": "readiness score claim policy is unsafe"})
    if policy.get("requires_promotion_for_public_graph") is not True:
        blockers.append({"code": "ERR_WAVE_OPERATOR_PROMOTION_POLICY_MISSING", "message": "public graph promotion policy is missing"})
    return blockers


def activation_blockers(activation: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if activation.get("decision") != "ready_for_next_workflow_design":
        blockers.append({"code": "ERR_WAVE_OPERATOR_ACTIVATION_NOT_READY", "message": "workflow activation is not ready", "decision": activation.get("decision")})
    if activation.get("blocked_by"):
        blockers.append({"code": "ERR_WAVE_OPERATOR_ACTIVATION_BLOCKED", "message": "workflow activation contains blockers"})
    return blockers


def select_wave(readiness: dict[str, Any], activation: dict[str, Any], candidates: list[dict[str, Any]] | None = None, *, wave_id: str = "wave") -> dict[str, Any]:
    blockers = readiness_blockers(readiness) + activation_blockers(activation)
    candidates = candidates or default_wave_candidates()
    public_allowed = readiness.get("public_benchmark_publish_allowed") is True
    selected = next((candidate for candidate in sorted(candidates, key=lambda item: (-int(item.get("priority", 0)), str(item.get("id", "")))) if candidate.get("id") != "benchmark-promotion-human-gate"), None)
    human_gate = None
    if public_allowed:
        selected = next((candidate for candidate in candidates if candidate.get("id") == "benchmark-promotion-human-gate"), selected)
        human_gate = {
            "code": "ERR_WAVE_OPERATOR_HUMAN_REVIEW_REQUIRED",
            "message": "public benchmark publication requires human review",
            "safe_default": "do not change README benchmark assets",
        }
    if selected is None:
        blockers.append({"code": "ERR_WAVE_OPERATOR_CANDIDATES_MISSING", "message": "no wave candidates are available"})
    command = str(selected.get("command", "")) if selected else ""
    command_safety = assess_command_safety(command, selected.get("risk_codes") if selected else []) if command else None
    if command_safety is not None and not command_safety.supported:
        blockers.append({"code": "ERR_WAVE_OPERATOR_COMMAND_UNSUPPORTED", "message": "selected wave command is unsupported", "command": command})
    if command_safety is not None and command_safety.gated_risk_codes:
        human_gate = human_gate or {
            "code": "ERR_WAVE_OPERATOR_COMMAND_GATE_REQUIRED",
            "risk_codes": command_safety.gated_risk_codes,
            "safe_default": "do not execute selected command without approval",
        }
    decision = "blocked" if blockers else "human_gate_required" if human_gate else "wave_ready"
    return {
        "schema_version": WAVE_VERSION,
        "tool": TOOL,
        "wave_id": wave_id,
        "decision": decision,
        "selected_wave": selected,
        "command": "" if human_gate else command,
        "human_gate": human_gate,
        "blocked_by": blockers,
        "next_mode": "human_review" if human_gate else "source_only_wave" if not blockers else "repair_inputs",
        "claim_policy": {
            "may_publish_public_benchmark_graph": bool(public_allowed and human_gate is None),
            "requires_human_review_for_publication": True,
            "process_or_operator_graph_only_until_promotion": not public_allowed,
        },
        "execution_policy": {"executes_commands": False, "creates_worktrees": False, "uses_network": False},
        "source_hashes": {
            "benchmark_readiness": canonical_hash(readiness),
            "workflow_activation": canonical_hash(activation),
        },
    }


def render_markdown(wave: dict[str, Any]) -> str:
    selected = wave.get("selected_wave") if isinstance(wave.get("selected_wave"), dict) else {}
    lines = [
        "# Wave Operator",
        "",
        f"- Decision: `{wave['decision']}`",
        f"- Next mode: `{wave['next_mode']}`",
        f"- Selected wave: `{selected.get('id', '')}`",
        f"- Command ready: `{bool(wave.get('command'))}`",
        "",
        "## Objective",
        "",
        str(selected.get("objective", "")),
        "",
        "## Exit Criteria",
        "",
    ]
    for item in selected.get("exit_criteria", []) if isinstance(selected.get("exit_criteria"), list) else []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "This wave operator does not execute commands, create worktrees, use the network, or publish benchmark claims.",
            "Public benchmark graph publication still requires promotion evidence and human review.",
            "",
        ]
    )
    return "\n".join(lines)


def write_wave(out_dir: Path, wave: dict[str, Any]) -> None:
    write_json_atomic(out_dir / "wave-operator.json", wave, root=out_dir)
    write_json_atomic(out_dir / "status.json", wave, root=out_dir)
    write_text_atomic(out_dir / "wave-operator.md", render_markdown(wave), root=out_dir)


def select_from_files(readiness_path: Path, activation_path: Path, out_dir: Path) -> dict[str, Any]:
    readiness_resolved = resolve_input(readiness_path)
    activation_resolved = resolve_input(activation_path)
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=readiness_resolved)
    wave = select_wave(read_json(readiness_resolved), read_json(activation_resolved), wave_id=out_dir.name)
    wave["source_paths"] = {"benchmark_readiness": rel(readiness_resolved), "workflow_activation": rel(activation_resolved)}
    write_wave(out_dir, wave)
    if wave["decision"] == "blocked":
        raise WaveOperatorError("ERR_WAVE_OPERATOR_BLOCKED", "wave operator is blocked", path=out_dir)
    return wave


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise WaveOperatorError("ERR_WAVE_OPERATOR_MANIFEST_INVALID", "manifest fixtures must be a list", path=manifest_path)
    suite_id = str(manifest.get("suite_id", "v98-wave-operator"))
    out_dir = resolve_out(out_dir)
    prepare_out_dir(out_dir, out_dir.name, source=manifest_path)
    records = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("id", "fixture"))
        fixture_out = out_dir / fixture_id
        prepare_out_dir(fixture_out, fixture_id, source=manifest_path)
        wave = select_wave(
            fixture.get("readiness") if isinstance(fixture.get("readiness"), dict) else {},
            fixture.get("activation") if isinstance(fixture.get("activation"), dict) else {},
            fixture.get("candidates") if isinstance(fixture.get("candidates"), list) else None,
            wave_id=fixture_id,
        )
        write_wave(fixture_out, wave)
        errors: list[str] = []
        if fixture.get("expected_decision") is not None and fixture["expected_decision"] != wave["decision"]:
            errors.append(f"expected {fixture['expected_decision']}, got {wave['decision']}")
        if fixture.get("expected_wave_id") is not None:
            selected_id = wave["selected_wave"].get("id") if isinstance(wave.get("selected_wave"), dict) else None
            if fixture["expected_wave_id"] != selected_id:
                errors.append(f"expected wave {fixture['expected_wave_id']}, got {selected_id}")
        records.append({"id": fixture_id, "required": bool(fixture.get("required", True)), "status": "pass" if not errors else "fail", "decision": wave["decision"], "selected_wave": wave["selected_wave"].get("id") if isinstance(wave.get("selected_wave"), dict) else None, "error": "; ".join(errors) if errors else None})
    failed_required = [record for record in records if record["required"] and record["status"] != "pass"]
    summary = {
        "schema_version": WAVE_VERSION,
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
        raise WaveOperatorError("ERR_WAVE_OPERATOR_FIXTURE_FAILED", "required wave-operator fixture failed", path=manifest_path)
    return summary


def sample_readiness(*, public: bool = False, decision: str = "benchmark_readiness_recorded") -> dict[str, Any]:
    return {
        "tool": "dwm_benchmark_readiness.py",
        "decision": decision,
        "readiness_score": 100 if public else 70,
        "public_benchmark_publish_allowed": public,
        "claim_policy": {
            "readiness_score_is_public_benchmark": False,
            "requires_promotion_for_public_graph": True,
            "requires_human_review_for_readme_publication": True,
        },
    }


def sample_activation(*, ready: bool = True) -> dict[str, Any]:
    return {
        "decision": "ready_for_next_workflow_design" if ready else "blocked",
        "blocked_by": [] if ready else [{"code": "ERR_SAMPLE_BLOCKED"}],
    }


def self_test() -> None:
    wave = select_wave(sample_readiness(), sample_activation(), wave_id="self-test")
    if wave["decision"] != "wave_ready" or wave["selected_wave"]["id"] != "dogfood-evidence-wave":
        raise ValueError("operator-ready readiness should select dogfood evidence wave")
    public = select_wave(sample_readiness(public=True), sample_activation(), wave_id="self-test-public")
    if public["decision"] != "human_gate_required" or public["command"]:
        raise ValueError("public benchmark publication must stop at human gate")
    blocked = select_wave(sample_readiness(decision="blocked"), sample_activation(), wave_id="self-test-blocked")
    if blocked["decision"] != "blocked":
        raise ValueError("blocked readiness must block wave selection")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    select = subparsers.add_parser("select")
    select.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    select.add_argument("--activation", type=Path, default=DEFAULT_ACTIVATION)
    select.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("wave operator self-test: pass")
            return
        if args.manifest:
            if args.out is None:
                raise WaveOperatorError("ERR_WAVE_OPERATOR_OUT_REQUIRED", "--out is required with --manifest")
            summary = run_manifest(args.manifest, args.out)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "select":
            wave = select_from_files(args.readiness, args.activation, args.out)
            print(json.dumps({"decision": wave["decision"], "selected_wave": wave["selected_wave"]["id"], "wave_id": wave["wave_id"]}, sort_keys=True))
            return
        raise WaveOperatorError("ERR_WAVE_OPERATOR_COMMAND_REQUIRED", "use --self-test, --manifest, or select")
    except WaveOperatorError as exc:
        print(json.dumps({"error": exc.to_record()}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
