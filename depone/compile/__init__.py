"""Compile workflow plans into target framework formats.

Supported targets:
  - conductor: Microsoft Conductor workflow YAML
  - langgraph: stub (not yet implemented in V104.0)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from depone.compile import agent_fabric, conductor


def run(args: argparse.Namespace) -> None:
    """Dispatch compile to the appropriate target emitter."""
    # Self-test bypasses target requirement
    if getattr(args, "self_test", False):
        conductor.run(args)
        agent_fabric._self_test()
        return

    target = args.target
    if not args.plan:
        print(
            "Usage: depone compile <plan.json> --target conductor [--out workflow.yaml]",
            file=sys.stderr,
        )
        sys.exit(1)

    if target is None:
        print(
            "Error: --target is required (choices: conductor, langgraph)",
            file=sys.stderr,
        )
        sys.exit(1)

    if target == "conductor":
        conductor.run(args)
    elif target == "agent-fabric":
        _run_agent_fabric(args)
    elif target == "langgraph":
        print("Error: langgraph compile is not implemented", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Error: unknown compile target: {target}", file=sys.stderr)
        sys.exit(1)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read JSON {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _load_role_contracts(paths: list[str]) -> list[dict[str, Any]]:
    role_contracts: list[dict[str, Any]] = []
    if not paths:
        print(
            "Error: --target agent-fabric requires at least one --roles JSON path",
            file=sys.stderr,
        )
        sys.exit(1)

    for value in paths:
        data = _read_json(Path(value))
        if isinstance(data, dict) and isinstance(data.get("roles"), list):
            role_contracts.extend(item for item in data["roles"] if isinstance(item, dict))
        elif isinstance(data, list):
            role_contracts.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            role_contracts.append(data)
        else:
            print(f"Error: role contract JSON root must be an object or list: {value}", file=sys.stderr)
            sys.exit(1)

    return role_contracts


def _run_agent_fabric(args: argparse.Namespace) -> None:
    profile = _read_json(Path(args.plan))
    if not isinstance(profile, dict):
        print("Error: Agent Fabric profile JSON root must be an object", file=sys.stderr)
        sys.exit(1)

    role_contracts = _load_role_contracts(list(getattr(args, "roles", [])))
    bundle = agent_fabric.compile_agent_fabric(
        profile,
        str(getattr(args, "harness", "shell")),
        role_contracts,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    print(f"Agent Fabric bundle written to {out_path}")
