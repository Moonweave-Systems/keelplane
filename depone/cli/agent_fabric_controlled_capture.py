"""depone agent-fabric-controlled-capture — export source-only capture corpus."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from depone.agent_fabric.controlled_capture import (
    build_controlled_capture_corpus_report,
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

    capture_paths = getattr(args, "capture_manifest", []) or []
    if not capture_paths:
        print(
            "Usage: depone agent-fabric-controlled-capture "
            "--capture-manifest <capture-manifest.json> "
            "--capture-manifest <capture-manifest.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    captures = [
        _read_object(Path(path), f"capture manifest #{index + 1}")
        for index, path in enumerate(capture_paths)
    ]
    report = build_controlled_capture_corpus_report(captures)
    out_path = Path(getattr(args, "out", "controlled-capture-corpus.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Controlled capture corpus report written to {out_path}")
    print(f"  Decision: {report['decision']}")
    print(f"  Manifest count: {report['summary']['manifest_count']}")


def _self_test() -> None:
    print("depone agent-fabric-controlled-capture --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_path = root / "controlled-capture-corpus.json"
        args = argparse.Namespace(
            self_test=False,
            capture_manifest=[
                "depone/fixtures/agent_fabric/capture_manifest_shell.json",
                "depone/fixtures/agent_fabric/capture_manifest_shell_docs.json",
            ],
            out=str(out_path),
        )
        run(args)
        report = json.loads(out_path.read_text())
        if report.get("decision") != "controlled-capture-corpus-ready-source-only":
            print("  [FAIL] expected controlled capture corpus ready", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only controlled capture corpus exported")
