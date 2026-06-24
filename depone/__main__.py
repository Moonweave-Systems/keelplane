"""Depone CLI entrypoint for core commands and Agent Fabric smoke."""

from __future__ import annotations

import argparse
import sys

from depone.cli import (
    agent_fabric_adapter_smoke,
    agent_fabric_claim_gate,
    agent_fabric_harness_snapshot,
    agent_fabric_smoke,
    demo,
    design,
    validate,
    validate_contracts,
)
from depone import compile as compile_mod
from depone import verify as verify_mod


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="depone",
        description="Workflow designer + cross-platform evidence verifier.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"depone v{__import__('depone').__version__}",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # design
    design_parser = sub.add_parser(
        "design", help="Decompose an objective into a workflow plan"
    )
    design_parser.add_argument(
        "objective", nargs="?", help="Natural-language objective"
    )
    design_parser.add_argument(
        "--out", default="plan.json", help="Output path for plan.json"
    )
    design_parser.add_argument(
        "--surface", help="Repo path, API spec, or doc URL in scope"
    )
    design_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # validate
    validate_parser = sub.add_parser(
        "validate", help="Validate a plan.json against the schema"
    )
    validate_parser.add_argument("plan", nargs="?", help="Path to plan.json")
    validate_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # compile
    compile_parser = sub.add_parser(
        "compile", help="Compile a plan into a target framework workflow"
    )
    compile_parser.add_argument("plan", nargs="?", help="Path to plan.json")
    compile_parser.add_argument(
        "--target",
        default=None,
        choices=["conductor", "langgraph", "agent-fabric"],
        help="Target workflow framework",
    )
    compile_parser.add_argument("--out", default="workflow.yaml", help="Output path")
    compile_parser.add_argument(
        "--harness",
        default="shell",
        help="Agent Fabric target harness (used with --target agent-fabric)",
    )
    compile_parser.add_argument(
        "--roles",
        action="append",
        default=[],
        help=(
            "Role contract JSON path for --target agent-fabric; may be repeated "
            "or point at a role-set JSON"
        ),
    )
    compile_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # verify
    verify_parser = sub.add_parser(
        "verify", help="Verify execution evidence against a plan"
    )
    verify_parser.add_argument("plan", nargs="?", help="Path to plan.json")
    verify_parser.add_argument(
        "--evidence", default=None, help="Path to execution evidence directory"
    )
    verify_parser.add_argument(
        "--adapter", default="generic", help="Evidence adapter (conductor, generic)"
    )
    verify_parser.add_argument(
        "--out", default="verification-report.json", help="Output path for report"
    )
    verify_parser.add_argument(
        "--operator-view-out",
        default=None,
        help="Output path for a V111 operator-readable report view",
    )
    verify_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # validate-contracts
    vc_parser = sub.add_parser(
        "validate-contracts",
        help="Validate V107 Agent Fabric contracts (roles, toolbelts, harnesses)",
    )
    vc_parser.add_argument("--file", help="Path to a single contract JSON file")
    vc_parser.add_argument(
        "--all", action="store_true", help="Validate all contracts under contracts/"
    )
    vc_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # agent-fabric-smoke
    smoke_parser = sub.add_parser(
        "agent-fabric-smoke",
        help="Export the source-only Agent Fabric compile-to-report smoke summary",
    )
    smoke_parser.add_argument("--profile", help="Agent Fabric profile JSON path")
    smoke_parser.add_argument(
        "--roles",
        action="append",
        default=[],
        help="Role contract JSON path; may be repeated or point at a role-set JSON",
    )
    smoke_parser.add_argument(
        "--plan", help="Depone plan JSON path for report verification"
    )
    smoke_parser.add_argument("--harness", default="shell", help="Target harness name")
    smoke_parser.add_argument(
        "--out",
        default="agent-fabric-smoke.json",
        help="Output path for smoke summary JSON",
    )
    smoke_parser.add_argument(
        "--operator-view-out",
        default=None,
        help="Optional output path for the embedded operator Markdown view",
    )
    smoke_parser.add_argument(
        "--observer-capture",
        default=None,
        help="Optional Depone observer capture JSON for A1-local-observed smoke",
    )
    smoke_parser.add_argument(
        "--allow-touched-file",
        action="append",
        default=[],
        help="Allowed touched file for observer capture validation; may be repeated",
    )
    smoke_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # agent-fabric-harness-snapshot
    harness_snapshot_parser = sub.add_parser(
        "agent-fabric-harness-snapshot",
        help="Export source-only Agent Fabric harness capability snapshots",
    )
    harness_snapshot_parser.add_argument(
        "--harness",
        action="append",
        default=[],
        help=(
            "Harness name to include; may be repeated, "
            "defaults to all known harnesses"
        ),
    )
    harness_snapshot_parser.add_argument(
        "--out",
        default="agent-fabric-harness-snapshot.json",
        help="Output path for harness snapshot JSON",
    )
    harness_snapshot_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # agent-fabric-adapter-smoke
    adapter_smoke_parser = sub.add_parser(
        "agent-fabric-adapter-smoke",
        help="Export source-only Agent Fabric adapter smoke reports",
    )
    adapter_smoke_parser.add_argument(
        "--adapter-fixture", help="Reference adapter fixture JSON path"
    )
    adapter_smoke_parser.add_argument(
        "--harness-snapshot",
        default=None,
        help="Optional harness snapshot JSON path; defaults to adapter harness",
    )
    adapter_smoke_parser.add_argument(
        "--out",
        default="agent-fabric-adapter-smoke.json",
        help="Output path for adapter smoke report JSON",
    )
    adapter_smoke_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # agent-fabric-claim-gate
    claim_gate_parser = sub.add_parser(
        "agent-fabric-claim-gate",
        help="Gate Agent Fabric public claims on source evidence",
    )
    claim_gate_parser.add_argument(
        "--adapter-smoke", help="Adapter smoke report JSON path"
    )
    claim_gate_parser.add_argument(
        "--claim-scope",
        default="public-benefit",
        help="Claim scope being gated",
    )
    claim_gate_parser.add_argument(
        "--out",
        default="agent-fabric-claim-gate.json",
        help="Output path for claim gate report JSON",
    )
    claim_gate_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    # demo
    demo_parser = sub.add_parser(
        "demo", help="Run a complete design→compile→verify cycle"
    )
    demo_parser.add_argument(
        "--out", default=None, help="Output directory for demo artifacts"
    )
    demo_parser.add_argument(
        "--self-test", action="store_true", help="Run self-test and exit"
    )

    args = parser.parse_args()

    if args.command == "design":
        design.run(args)
    elif args.command == "validate":
        validate.run(args)
    elif args.command == "compile":
        compile_mod.run(args)
    elif args.command == "verify":
        verify_mod.run(args)
    elif args.command == "validate-contracts":
        validate_contracts.run(args)
    elif args.command == "agent-fabric-smoke":
        agent_fabric_smoke.run(args)
    elif args.command == "agent-fabric-harness-snapshot":
        agent_fabric_harness_snapshot.run(args)
    elif args.command == "agent-fabric-adapter-smoke":
        agent_fabric_adapter_smoke.run(args)
    elif args.command == "agent-fabric-claim-gate":
        agent_fabric_claim_gate.run(args)
    elif args.command == "demo":
        demo.run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
