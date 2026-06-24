"""depone agent-fabric-dogfood-evidence — export source-only dogfood evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from depone.agent_fabric.dogfood_evidence import (
    build_controlled_capture_corpus_report,
    build_dogfood_evidence_report,
)


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

    capture_manifest_args = getattr(args, "capture_manifest", None)
    if not capture_manifest_args:
        print(
            "Usage: depone agent-fabric-dogfood-evidence "
            "--capture-manifest <capture-manifest.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    capture_paths = (
        capture_manifest_args
        if isinstance(capture_manifest_args, list)
        else [capture_manifest_args]
    )
    captures = [
        _read_object(Path(path), "capture manifest") for path in capture_paths
    ]
    out_path = Path(getattr(args, "out", "dogfood-evidence.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if len(captures) == 1:
        report = build_dogfood_evidence_report(captures[0])
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"Dogfood evidence report written to {out_path}")
        print(f"  Decision: {report['decision']}")
        print(f"  Capture assurance: {report['capture_assurance']}")
        return

    report = build_controlled_capture_corpus_report(captures)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Controlled capture corpus written to {out_path}")
    print(f"  Decision: {report['decision']}")
    print(f"  Capture count: {report['capture_count']}")


def _self_test() -> None:
    print("depone agent-fabric-dogfood-evidence --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        capture_path = root / "capture-manifest.json"
        out_path = root / "dogfood-evidence.json"
        capture = _read_object(
            Path("depone/fixtures/agent_fabric/capture_manifest_shell.json"),
            "capture manifest fixture",
        )
        capture_path.write_text(json.dumps(capture))
        args = argparse.Namespace(
            self_test=False,
            capture_manifest=str(capture_path),
            out=str(out_path),
        )
        run(args)
        report = json.loads(out_path.read_text())
        if report.get("decision") != "dogfood-evidence-ready-source-only":
            print("  [FAIL] expected dogfood evidence ready", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only dogfood evidence report exported")
