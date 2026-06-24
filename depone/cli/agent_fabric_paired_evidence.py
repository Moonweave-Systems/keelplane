"""depone agent-fabric-paired-evidence — export source-only paired evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
from depone.agent_fabric.harness_snapshot import build_harness_snapshot
from depone.agent_fabric.paired_evidence import build_paired_evidence_report


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

    if not getattr(args, "adapter_smoke", None) or not getattr(
        args, "dogfood_evidence", None
    ):
        print(
            "Usage: depone agent-fabric-paired-evidence "
            "--adapter-smoke <adapter-smoke.json> "
            "--dogfood-evidence <dogfood-evidence.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    adapter_smoke = _read_object(Path(args.adapter_smoke), "adapter smoke")
    dogfood_evidence = _read_object(Path(args.dogfood_evidence), "dogfood evidence")
    report = build_paired_evidence_report(
        adapter_smoke,
        dogfood_evidence,
        claim_scope=getattr(args, "claim_scope", "public-benefit"),
    )
    out_path = Path(getattr(args, "out", "agent-fabric-paired-evidence.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Paired evidence report written to {out_path}")
    print(f"  Decision: {report['decision']}")
    print(f"  Claim scope: {report['claim_scope']}")


def _self_test() -> None:
    print("depone agent-fabric-paired-evidence --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        smoke_path = root / "adapter-smoke.json"
        dogfood_path = root / "dogfood-evidence.json"
        out_path = root / "paired-evidence.json"
        fixture = _read_object(
            Path("depone/fixtures/agent_fabric/reference_adapter_shell.json"),
            "adapter fixture",
        )
        smoke = build_adapter_smoke_report(fixture, build_harness_snapshot(["shell"]))
        dogfood = {
            "kind": "agent-fabric-dogfood-evidence",
            "decision": "dogfood-evidence-ready-source-only",
            "evidence_type": "paired-dogfood",
            "boundary": {
                "executes_commands": False,
                "calls_live_models": False,
                "approves_public_claim": False,
            },
        }
        smoke_path.write_text(json.dumps(smoke))
        dogfood_path.write_text(json.dumps(dogfood))
        args = argparse.Namespace(
            self_test=False,
            adapter_smoke=str(smoke_path),
            dogfood_evidence=str(dogfood_path),
            claim_scope="public-benefit",
            out=str(out_path),
        )
        run(args)
        report = json.loads(out_path.read_text())
        if report.get("decision") != "paired-evidence-ready-source-only":
            print("  [FAIL] expected paired evidence ready", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only paired evidence report exported")
