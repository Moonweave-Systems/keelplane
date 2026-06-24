"""depone agent-fabric-adapter-smoke — export source-only adapter smoke report."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from depone.agent_fabric.adapter_smoke import build_adapter_smoke_report
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

    if not getattr(args, "adapter_fixture", None):
        print(
            "Usage: depone agent-fabric-adapter-smoke "
            "--adapter-fixture <fixture.json> [--harness-snapshot snapshot.json]",
            file=sys.stderr,
        )
        sys.exit(1)

    fixture = _read_object(Path(args.adapter_fixture), "adapter fixture")
    if getattr(args, "harness_snapshot", None):
        snapshot = _read_object(Path(args.harness_snapshot), "harness snapshot")
    else:
        snapshot = build_harness_snapshot([fixture.get("adapter", {}).get("harness")])

    report = build_adapter_smoke_report(fixture, snapshot)
    out_path = Path(getattr(args, "out", "agent-fabric-adapter-smoke.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Adapter smoke report written to {out_path}")
    print(f"  Decision: {report['decision']}")
    print(f"  Harness: {report['harness']}")


def _self_test() -> None:
    print("depone agent-fabric-adapter-smoke --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_path = root / "adapter-smoke.json"
        args = argparse.Namespace(
            self_test=False,
            adapter_fixture="depone/fixtures/agent_fabric/reference_adapter_shell.json",
            harness_snapshot=None,
            out=str(out_path),
        )
        run(args)
        report = json.loads(out_path.read_text())
        if report.get("decision") != "ready-source-only":
            print("  [FAIL] expected ready-source-only", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only adapter smoke report exported")
