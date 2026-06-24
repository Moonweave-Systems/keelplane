"""depone agent-fabric-harness-snapshot — export harness capability snapshots."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from depone.agent_fabric.harness_snapshot import build_harness_snapshot


def run(args: argparse.Namespace) -> None:
    if getattr(args, "self_test", False):
        _self_test()
        return

    harnesses = list(getattr(args, "harness", []) or []) or None
    snapshot = build_harness_snapshot(harnesses)
    out_path = Path(getattr(args, "out", "agent-fabric-harness-snapshot.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"Harness snapshot written to {out_path}")
    print(f"  Decision: {snapshot['decision']}")
    print(f"  Harnesses: {snapshot['summary']['harness_count']}")
    if snapshot["unknown_harnesses"]:
        print(
            f"  Unknown harnesses: {', '.join(snapshot['unknown_harnesses'])}",
            file=sys.stderr,
        )


def _self_test() -> None:
    print("depone agent-fabric-harness-snapshot --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "harness-snapshot.json"
        args = argparse.Namespace(
            self_test=False,
            harness=["shell", "codex"],
            out=str(out_path),
        )
        run(args)
        snapshot = json.loads(out_path.read_text())
        if snapshot.get("decision") != "snapshot-with-approximations":
            print("  [FAIL] expected snapshot-with-approximations", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only harness snapshot exported")
