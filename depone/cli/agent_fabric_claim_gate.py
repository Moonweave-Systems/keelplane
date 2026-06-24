"""depone agent-fabric-claim-gate — gate public claims on evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
from depone.agent_fabric.claim_gate import build_claim_gate_report
from depone.agent_fabric.harness_snapshot import build_harness_snapshot


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read {label} JSON {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(value, dict):
        print(f"Error: {label} JSON root must be an object", file=sys.stderr)
        sys.exit(1)
    return value


def run(args: argparse.Namespace) -> None:
    if getattr(args, "self_test", False):
        _self_test()
        return

    if not getattr(args, "adapter_smoke", None):
        print(
            "Usage: depone agent-fabric-claim-gate "
            "--adapter-smoke <adapter-smoke.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    adapter_smoke = _read_object(Path(args.adapter_smoke), "adapter smoke")
    report = build_claim_gate_report(
        adapter_smoke,
        claim_scope=getattr(args, "claim_scope", "public-benefit"),
    )
    out_path = Path(getattr(args, "out", "agent-fabric-claim-gate.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Claim gate report written to {out_path}")
    print(f"  Decision: {report['decision']}")
    print(f"  Claim scope: {report['claim_scope']}")


def _self_test() -> None:
    print("depone agent-fabric-claim-gate --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        smoke_path = root / "adapter-smoke.json"
        out_path = root / "claim-gate.json"
        fixture = _read_object(
            Path("depone/fixtures/agent_fabric/reference_adapter_shell.json"),
            "adapter fixture",
        )
        smoke = build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))
        smoke_path.write_text(json.dumps(smoke))
        args = argparse.Namespace(
            self_test=False,
            adapter_smoke=str(smoke_path),
            claim_scope="public-benefit",
            out=str(out_path),
        )
        run(args)
        report = json.loads(out_path.read_text())
        if report.get("decision") != "blocked-missing-paired-evidence":
            print("  [FAIL] expected paired evidence blocker", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only claim gate report exported")
