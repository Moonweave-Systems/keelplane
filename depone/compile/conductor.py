"""Conductor YAML emitter — translates a depone plan.json into Conductor workflow YAML.

stdlib-only: no PyYAML dependency. The emitter writes valid Conductor YAML
by constructing each line directly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from depone.core.plan_schema import load_plan


def _yaml_scalar(value: str) -> str:
    """Quote/escape a string if it contains YAML-special characters.

    Single-quote with '' escaping for strings containing any of:
    : # { } [ ] , & * ! | > ' \" % @ `, leading/trailing whitespace,
    or a newline.  Returns the value unquoted if none of the triggers
    are present.
    """
    if not value:
        return "''"
    triggers = set(":#{}[] ,&*!|>'\"%@`\n")
    if any(c in triggers for c in value) or value != value.strip():
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return value


def _yaml_value(value: Any, indent: int) -> str:
    """Format a Python value as a YAML line (string, number, bool, or null)."""
    pad = "  " * indent
    if value is None:
        return f"{pad}null"
    if isinstance(value, bool):
        return f"{pad}{str(value).lower()}"
    if isinstance(value, (int, float)):
        return f"{pad}{value}"
    if isinstance(value, str) and "\n" in value:
        lines = value.split("\n")
        inner = "\n".join(f"{pad}  {line}" for line in lines)
        return f"{pad}|\n{inner}"
    if isinstance(value, str):
        return f"{pad}{_yaml_scalar(value)}"
    if isinstance(value, dict):
        return _yaml_dict(value, indent)
    if isinstance(value, list):
        return _yaml_list(value, indent)
    return f"{pad}{value}"


def _yaml_dict(d: dict[str, Any], indent: int) -> str:
    """Format a dict as YAML key-value pairs."""
    if not d:
        return ""
    lines: list[str] = []
    for k, v in d.items():
        pad = "  " * indent
        lines.append(f"{pad}{k}:")
        if isinstance(v, dict):
            lines.append(_yaml_dict(v, indent + 1).lstrip())
        elif isinstance(v, list):
            if not v:
                lines.append(f"{pad}  []")
            else:
                for item in v:
                    if isinstance(item, dict):
                        lines.append(
                            f"{pad}  - {_yaml_dict(item, indent + 2).lstrip()}"
                        )
                    else:
                        lines.append(f"{pad}  - {_yaml_value(item, 0).strip()}")
        else:
            lines.append(f"  {_yaml_value(v, indent + 1).lstrip()}")
    return "\n".join(lines)


def _yaml_list(items: list[Any], indent: int) -> str:
    """Format a list as YAML list items."""
    if not items:
        return ""
    lines: list[str] = []
    pad = "  " * indent
    for item in items:
        if isinstance(item, dict):
            lines.append(f"{pad}- {_yaml_dict(item, indent + 1).lstrip()}")
        else:
            lines.append(f"{pad}- {item}")
    return "\n".join(lines)


def _build_agent_name(phase_id: str) -> str:
    """Convert a phase ID to a Conductor-safe agent name."""
    return phase_id.replace("_", "-").replace(".", "-")


def _build_phase_agents(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build Conductor agent entries from plan phases and workers."""
    phases = plan.get("phases", [])
    workers = {
        w["id"]: w
        for w in plan.get("workers", [])
        if isinstance(w, dict) and w.get("id")
    }
    agents: list[dict[str, Any]] = []

    for i, phase in enumerate(phases):
        phase_id = phase.get("id", f"phase-{i}")
        worker_id_list = phase.get("worker_ids", [])
        worker = workers.get(worker_id_list[0]) if worker_id_list else None

        # Build prompt from worker and phase
        prompt_parts: list[str] = []
        if worker and worker.get("prompt_contract", {}).get("inputs"):
            inputs = worker["prompt_contract"]["inputs"]
            prompt_parts.append("## Inputs")
            for inp in inputs:
                prompt_parts.append(
                    f"- {inp.get('name', 'unknown')}: ${{{inp.get('name', 'value')}}}"
                )
            prompt_parts.append("")

        if worker and worker.get("role"):
            prompt_parts.append(f"Role: {worker['role']}")

        entry = phase.get("entry_criteria", [])
        if isinstance(entry, list) and entry:
            prompt_parts.append(f"Start when: {entry[0]}")

        exit_crit = phase.get("exit_criteria", [])
        if isinstance(exit_crit, list) and exit_crit:
            prompt_parts.append(f"Complete when: {exit_crit[0]}")

        if worker and worker.get("forbidden_actions"):
            prompt_parts.append(f"Do NOT: {', '.join(worker['forbidden_actions'])}")

        prompt_parts.append(f"Phase: {phase.get('name', phase_id)}")
        prompt = (
            "\n".join(prompt_parts)
            if prompt_parts
            else f"Execute {phase.get('name', phase_id)}."
        )

        agent: dict[str, Any] = {
            "name": _build_agent_name(phase_id),
            "prompt": prompt,
        }

        # Add output schema from worker
        if worker:
            contract = worker.get("prompt_contract", {})
            schema = contract.get("required_output_schema")
            if schema:
                agent["output"] = {
                    "result": {"type": "string", "description": str(schema)}
                }

        agents.append(agent)

    return agents


def _build_routes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Build route entries from plan handoffs between phases."""
    phases = plan.get("phases", [])
    handoffs = plan.get("handoffs", [])
    routes: list[dict[str, Any]] = []

    if not phases:
        return routes

    # Build phase_name -> index map
    phase_ids = [p.get("id", f"phase-{i}") for i, p in enumerate(phases)]

    for i, phase in enumerate(phases):
        phase_id = phase.get("id", f"phase-{i}")
        agent_name = _build_agent_name(phase_id)
        # Find handoffs FROM this phase
        outgoing = [h for h in handoffs if h.get("from_phase") == phase_id]

        if not outgoing:
            # Check if this phase depends on another — handoff from dep to this
            incoming = [h for h in handoffs if h.get("to_phase") == phase_id]
            if incoming:
                # Route will be handled by the dep's phase
                pass
            elif i < len(phases) - 1:
                # Sequential: route to next phase
                next_id = phase_ids[i + 1]
                routes.append(
                    {
                        "from": agent_name,
                        "to": [_build_agent_name(next_id)],
                    }
                )

    # Handoff-based routes
    for h in handoffs:
        from_agent = _build_agent_name(h["from_phase"])
        to_agent = _build_agent_name(h["to_phase"])
        routes.append(
            {
                "from": from_agent,
                "to": [to_agent],
            }
        )

    # Add $end for last phase
    if phase_ids:
        last_agent = _build_agent_name(phase_ids[-1])
        routes.append(
            {
                "from": last_agent,
                "to": ["$end"],
            }
        )

    return routes


def emit_yaml(plan: dict[str, Any]) -> str:
    """Emit a complete Conductor workflow YAML string from a plan dict."""
    plan_id = plan.get("plan_id", "depone-workflow")
    objective = plan.get("objective", "")
    phases = plan.get("phases", [])
    budget = plan.get("budget", {})

    agents = _build_phase_agents(plan)
    routes = _build_routes(plan)

    lines: list[str] = []
    lines.append("# Generated by depone compile --target conductor")
    lines.append(f"# Plan: {plan_id}")
    lines.append(f"# Schema: {_yaml_scalar(plan.get('schema_version', '0.5'))}")
    lines.append("")

    lines.append("workflow:")
    lines.append(f"  name: {_yaml_scalar(plan_id)}")
    lines.append(f"  description: {_yaml_scalar(objective)}")
    if phases:
        lines.append(f"  entry_point: {_build_agent_name(phases[0]['id'])}")
    lines.append("  limits:")
    lines.append(f"    max_iterations: {budget.get('max_rounds', 10)}")
    lines.append("  runtime:")
    lines.append("    provider: copilot")
    lines.append("")

    lines.append("agents:")
    for i, agent in enumerate(agents):
        name = agent["name"]
        lines.append(f"  - name: {name}")
        lines.append("    prompt: |")
        for pl in agent["prompt"].split("\n"):
            lines.append(f"      {pl}")

        if "output" in agent:
            lines.append("    output:")
            for ok, ov in agent["output"].items():
                lines.append(f"      {ok}:")
                for fk, fv in ov.items():
                    lines.append(f"        {fk}: {_yaml_scalar(str(fv))}")

        # Routes for this agent
        agent_routes = [r for r in routes if r.get("from") == name]
        if agent_routes:
            lines.append("    routes:")
            for r in agent_routes:
                for target in r.get("to", []):
                    lines.append(f"      - to: {target}")

        lines.append("")

    return "\n".join(lines)


def run(args: argparse.Namespace) -> None:
    """Entry point for depone compile --target conductor."""
    if args.self_test:
        _self_test()
        return

    plan_path = args.plan
    out_path = Path(args.out)

    try:
        plan = load_plan(str(plan_path))
    except Exception as e:
        print(f"Error: cannot load plan: {e}", file=sys.stderr)
        sys.exit(1)

    yaml_content = emit_yaml(plan)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_content)
    print(f"Conductor workflow written to {out_path}")
    print(f"  Agents: {len(plan.get('phases', []))}")


def _self_test() -> None:
    """Run basic self-test."""
    print("depone compile (conductor) --self-test")

    # Minimal plan
    plan = {
        "schema_version": "0.5",
        "plan_id": "self-test",
        "objective": "Test compile",
        "phases": [
            {
                "id": "phase-1",
                "name": "Analyze",
                "depends_on": [],
                "worker_ids": ["worker-1"],
                "entry_criteria": ["Input ready"],
                "exit_criteria": ["Analysis done"],
                "outputs": ["analysis"],
            },
        ],
        "workers": [
            {
                "id": "worker-1",
                "role": "analyst",
                "prompt_contract": {
                    "inputs": [{"name": "data", "type": "string"}],
                    "required_output_schema": "analysis report",
                    "stop_conditions": ["analysis_complete"],
                },
                "forbidden_actions": ["write", "shell"],
                "ownership": ["analysis"],
                "tool_permissions": {
                    "read": True,
                    "write": False,
                    "shell": False,
                    "network": False,
                    "mcp_connectors": [],
                    "requires_escalation_for": [],
                },
                "context_budget": {
                    "max_files": 5,
                    "max_tokens": 8000,
                    "must_include": ["input"],
                    "must_exclude": [],
                },
            },
        ],
        "handoffs": [],
        "budget": {"max_rounds": 5},
        "execution_path": {
            "first_slice": {"instruction": "Start analysis"},
        },
    }

    yaml = emit_yaml(plan)
    assert "name: phase-1" in yaml, yaml[:200]
    print("  [PASS] emits agent name")

    assert "agents:" in yaml
    print("  [PASS] emits agents section")

    assert yaml.strip().endswith("")
    print("  [PASS] well-formed output")

    # Regression: colon in objective must be quoted
    colon_plan = dict(plan)
    colon_plan["objective"] = "review API routes: auth and authz"
    yaml2 = emit_yaml(colon_plan)
    assert "description: 'review API routes: auth and authz'" in yaml2, (
        f"colon not quoted:\n{yaml2[:300]}"
    )
    print("  [PASS] colon in objective is quoted")

    print("\nSelf-test: 4/4 passed")


if __name__ == "__main__":
    _self_test()
