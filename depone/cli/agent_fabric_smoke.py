"""depone agent-fabric-smoke — export the V112 lifecycle smoke summary."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from depone.agent_fabric.lifecycle_smoke import build_compile_to_report_smoke


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read JSON {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _load_role_contracts(paths: list[str]) -> list[dict[str, Any]]:
    role_contracts: list[dict[str, Any]] = []
    if not paths:
        print("Error: --roles is required", file=sys.stderr)
        sys.exit(1)

    for value in paths:
        data = _read_json(Path(value))
        if isinstance(data, dict) and isinstance(data.get("roles"), list):
            role_contracts.extend(
                item for item in data["roles"] if isinstance(item, dict)
            )
        elif isinstance(data, list):
            role_contracts.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            role_contracts.append(data)
        else:
            print(
                f"Error: role contract JSON root must be an object or list: {value}",
                file=sys.stderr,
            )
            sys.exit(1)
    return role_contracts


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        print(f"Error: {label} JSON root must be an object", file=sys.stderr)
        sys.exit(1)
    return value


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def run(args: argparse.Namespace) -> None:
    if getattr(args, "self_test", False):
        _self_test()
        return

    missing = [name for name in ("profile", "plan") if not getattr(args, name, None)]
    if missing:
        print(
            "Usage: depone agent-fabric-smoke --profile <profile.json> "
            "--roles <role.json> --plan <plan.json> [--out smoke.json]",
            file=sys.stderr,
        )
        sys.exit(1)

    profile = _require_object(_read_json(Path(args.profile)), "profile")
    plan = _require_object(_read_json(Path(args.plan)), "plan")
    role_contracts = _load_role_contracts(list(getattr(args, "roles", [])))

    observer_capture = None
    if getattr(args, "observer_capture", None):
        observer_capture = _require_object(
            _read_json(Path(args.observer_capture)), "observer capture"
        )

    summary = build_compile_to_report_smoke(
        profile,
        str(getattr(args, "harness", "shell")),
        role_contracts,
        plan,
        observer_capture=observer_capture,
        allowed_touched_files=list(getattr(args, "allow_touched_file", []) or []),
    )

    out_path = Path(getattr(args, "out", "agent-fabric-smoke.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"Agent Fabric smoke summary written to {out_path}")
    print(f"  Overall decision: {summary['overall_decision']}")
    print(f"  Compile decision: {summary['compile_decision']}")
    print(f"  Report decision: {summary['report_decision']}")
    print(f"  Assurance: {summary['report_assurance']}")

    if getattr(args, "operator_view_out", None):
        view_path = Path(args.operator_view_out)
        _write_text(view_path, str(summary["operator_view"]))
        print(f"Operator view written to {view_path}")


def _role(role_id: str) -> dict[str, Any]:
    return {
        "id": role_id,
        "purpose": f"Run {role_id}",
        "allowed_tools": ["read", "test"],
        "forbidden_tools": ["write"],
        "context_policy": "local-code-only",
        "output_schema": f"{role_id}-result-v1",
        "evidence_obligations": ["command_receipt"],
        "trust_boundary": "local",
        "stop_rules": ["stop-on-complete"],
        "allowed_mcp_servers": [],
    }


def _profile(role_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "id": "agent-fabric-smoke-self-test",
        "version": "1.0.0",
        "description": "Agent Fabric smoke self-test profile",
        "activation": {"requires": [], "forbids": []},
        "limits": {"max_threads": 1, "max_writers": 0, "max_retries_per_role": 0},
        "roles": [{"role": role_id, "required": True}],
        "flow": [role_id],
        "required_evidence": ["command_receipt"],
    }


def _plan() -> dict[str, Any]:
    return {
        "schema_version": "0.5",
        "plan_id": "agent-fabric-smoke-self-test",
        "created_by": "depone",
        "source_prompt": "prove agent fabric smoke cli",
        "activation": {"decision": "activate", "matched_thresholds": []},
        "phases": [{"id": "phase-1", "title": "Phase 1"}],
        "handoffs": [],
        "risk_gates": [],
        "verification": [],
        "budget": {},
    }


def _self_test() -> None:
    print("depone agent-fabric-smoke --self-test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        profile_path = root / "profile.json"
        role_path = root / "role.json"
        plan_path = root / "plan.json"
        out_path = root / "smoke.json"
        profile_path.write_text(json.dumps(_profile("runner")))
        role_path.write_text(json.dumps(_role("runner")))
        plan_path.write_text(json.dumps(_plan()))

        args = argparse.Namespace(
            self_test=False,
            profile=str(profile_path),
            roles=[str(role_path)],
            plan=str(plan_path),
            harness="shell",
            out=str(out_path),
            operator_view_out=None,
            observer_capture=None,
            allow_touched_file=[],
        )
        run(args)
        summary = json.loads(out_path.read_text())
        if summary.get("overall_decision") != "ready-for-operator-review":
            print("  [FAIL] expected ready-for-operator-review", file=sys.stderr)
            sys.exit(1)
        print("  [PASS] source-only lifecycle smoke exported")
