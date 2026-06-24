"""Depone CLI entrypoint: depone {design,compile,verify,validate,demo}."""

from __future__ import annotations

import argparse
import sys

from depone.cli import design, validate, demo, validate_contracts
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
    elif args.command == "demo":
        demo.run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
