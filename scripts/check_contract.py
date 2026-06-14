#!/usr/bin/env python3
"""Check release-contract terms for the dynamic workflow designer skill."""

from pathlib import Path
import argparse
import re


ROOT = Path(__file__).resolve().parents[1]
FIELD_LABELS = [
    "objective",
    "surface",
    "assumptions",
    "phases",
    "workers",
    "handoffs",
    "parallelism",
    "verification",
    "risk gates",
    "budget",
    "resume",
    "execution path",
    "falsifiable verification",
    "safe default",
]
FIXTURE_RECORD_LABELS = [
    "fixture type",
    "local context inspected",
]
V05_REQUIRED_TERMS = [
    "router-first rule",
    "exclusive condition",
    "workflow.plan.json",
    "tool_permissions",
    "artifact_schema",
    "first_slice",
    "baseline must be normalized",
    "downstream consumer protocol",
    "borderline downgrade fixtures",
    "valid downgrade artifact",
]


def require_terms(path: str, terms: list[str]) -> None:
    text = (ROOT / path).read_text().lower()
    missing = [term for term in terms if term not in text]
    if missing:
        raise SystemExit(f"{path} missing required terms: {missing}")


def canonical_patterns() -> set[str]:
    text = (ROOT / "references" / "workflow-patterns.md").read_text()
    return {
        match.group(1).strip().lower()
        for match in re.finditer(r"(?m)^## ([^\n]+)$", text)
    }


def collect_fixture_blocks() -> list[tuple[str, str]]:
    smoke_dir = ROOT / "docs" / "fixture-smoke"
    blocks: list[tuple[str, str]] = []
    for path in sorted(smoke_dir.glob("*.md")):
        text = path.read_text()
        parts = re.split(r"(?m)^## Fixture \d+\s*$", text)
        for index, part in enumerate(parts[1:], start=1):
            blocks.append((f"{path.relative_to(ROOT)} fixture {index}", part.lower()))
    return blocks


def section_between(block: str, start: str, end: str) -> str:
    pattern = re.compile(
        rf"{re.escape(start)}\s*\n(?P<body>.*?)(?=\n{re.escape(end)}\s*\n|\Z)",
        re.DOTALL,
    )
    match = pattern.search(block)
    return match.group("body").strip() if match else ""


def parse_selected_patterns(block: str) -> list[str]:
    body = section_between(block, "selected patterns:", "generated workflow output:")
    return [
        line.removeprefix("-").strip()
        for line in body.splitlines()
        if line.strip().startswith("-")
    ]


def parse_fixture_record_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        match = re.match(r"^([a-z ]+):\s*(.*)$", line)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def parse_output_fields(block: str) -> dict[str, str]:
    body = section_between(block, "generated workflow output:", "failed criteria:")
    fields: dict[str, list[str]] = {}
    current_label = ""
    for line in body.splitlines():
        match = re.match(r"^- ([a-z ]+):\s*(.*)$", line)
        if match:
            current_label = match.group(1).strip()
            fields.setdefault(current_label, []).append(match.group(2).strip())
        elif current_label and line.startswith("  "):
            fields[current_label].append(line.strip())
    return {label: " ".join(parts).strip() for label, parts in fields.items()}


def require_fixture_smoke(blocks: list[tuple[str, str]] | None = None) -> None:
    blocks = collect_fixture_blocks() if blocks is None else blocks
    if len(blocks) < 2:
        raise SystemExit("fixture smoke requires at least two fixture records")

    valid_patterns = canonical_patterns()
    type_counts = {
        "codebase-facing": 0,
        "non-code/meta": 0,
    }
    required_terms = [
        "fixture type:",
        "prompt:",
        "selected patterns:",
        "generated workflow output:",
        "objective:",
        "surface:",
        "assumptions:",
        "phases:",
        "workers:",
        "handoffs:",
        "parallelism:",
        "verification:",
        "risk gates:",
        "budget:",
        "resume:",
        "execution path:",
        "falsifiable verification:",
        "safe default:",
        "failed criteria: none",
        "resulting change:",
        "overclaims execution: no",
    ]

    for index, (name, raw_block) in enumerate(blocks, start=1):
        block = raw_block.lower()
        missing = [term for term in required_terms if term not in block]
        if missing:
            raise SystemExit(f"{name} missing required terms: {missing}")

        record_fields = parse_fixture_record_fields(block)
        empty_record_fields = [
            label for label in FIXTURE_RECORD_LABELS
            if not record_fields.get(label, "").strip()
        ]
        if empty_record_fields:
            raise SystemExit(
                f"{name} has empty fixture record fields: {empty_record_fields}"
            )

        local_context = record_fields["local context inspected"]
        if local_context not in {"yes", "no", "not-needed"}:
            raise SystemExit(
                f"{name} has invalid local context inspected value: {local_context}"
            )

        patterns = parse_selected_patterns(block)
        if not patterns:
            raise SystemExit(f"{name} has no selected patterns")
        unknown_patterns = [
            pattern for pattern in patterns if pattern.lower() not in valid_patterns
        ]
        if unknown_patterns:
            raise SystemExit(f"{name} has unknown patterns: {unknown_patterns}")

        fields = parse_output_fields(block)
        empty_fields = [
            label for label in FIELD_LABELS if not fields.get(label, "").strip()
        ]
        if empty_fields:
            raise SystemExit(f"{name} has empty output fields: {empty_fields}")

        for fixture_type in type_counts:
            if f"fixture type: {fixture_type}" in block:
                type_counts[fixture_type] += 1

    missing_types = [
        fixture_type for fixture_type, count in type_counts.items() if count == 0
    ]
    if missing_types:
        raise SystemExit(f"fixture smoke missing fixture types: {missing_types}")


def self_test() -> None:
    valid_block = """
Fixture type: codebase-facing
Local context inspected: not-needed
Prompt:
Design a workflow.
Selected patterns:
- Pipeline
Generated workflow output:
- Objective: audit routes.
- Surface: route files.
- Assumptions: routes are discoverable.
- Phases: inventory, audit, verify.
- Workers: auditor and verifier.
- Handoffs: route table and finding ledger.
- Parallelism: batch routes.
- Verification: refute findings.
- Risk gates: read-only until approved.
- Budget: cap batches.
- Resume: cache inventory.
- Execution path: direct Codex work.
- Falsifiable verification: verifier must find counter-evidence.
- Safe default: stop before edits.
Failed criteria: none
Resulting change: none
Overclaims execution: no
"""
    meta_block = valid_block.replace(
        "Fixture type: codebase-facing", "Fixture type: non-code/meta"
    )
    require_fixture_smoke([("valid 1", valid_block), ("valid 2", meta_block)])

    bad_pattern = valid_block.replace("- Pipeline", "- Imaginary Pattern")
    try:
        require_fixture_smoke([("bad pattern", bad_pattern), ("valid 2", meta_block)])
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: unknown pattern passed")

    empty_safe_default = valid_block.replace(
        "- Safe default: stop before edits.", "- Safe default:"
    )
    try:
        require_fixture_smoke(
            [("empty safe default", empty_safe_default), ("valid 2", meta_block)]
        )
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: empty field passed")

    missing_local_context = valid_block.replace(
        "Local context inspected: not-needed\n", ""
    )
    try:
        require_fixture_smoke(
            [("missing local context", missing_local_context), ("valid 2", meta_block)]
        )
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: missing local context passed")

    empty_local_context = valid_block.replace(
        "Local context inspected: not-needed",
        "Local context inspected:",
    )
    try:
        require_fixture_smoke(
            [("empty local context", empty_local_context), ("valid 2", meta_block)]
        )
    except SystemExit:
        pass
    else:
        raise SystemExit("self-test failed: empty local context passed")

    print("contract self-test: pass")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    require_terms(
        "SKILL.md",
        [
            "`assumptions`",
            "`execution path`",
            "`workflow.plan.json`",
            "references/workflow-plan-schema.md",
            "downgrade artifact",
            "dependency",
            "database",
            "production",
            "secret",
            "history-rewrite",
        ],
    )
    require_terms(
        "docs/spec.md",
        [
            "fixture smoke gate",
            "docs/fixture-smoke/",
            "generated workflow output",
            "one codebase-facing fixture",
            "one non-code or meta fixture",
            "does not imply the requested work has already been executed",
            "v0.5 remains a separate continuation gate",
        ],
    )
    require_terms(
        "README.md",
        [
            "docs/v0.5-plan-schema-evaluator-spec.md",
            "docs/fixture-smoke/",
            "python scripts/check_contract.py --self-test",
            "python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5",
        ],
    )
    require_terms("docs/v0.5-plan-schema-evaluator-spec.md", V05_REQUIRED_TERMS)
    require_terms(
        "docs/spec.md",
        [
            "references/workflow-plan-schema.md",
            "scripts/evaluate_plan.py --self-test",
            "fixtures/v0.5/manifest.json",
            "samples/v0.5/candidates/",
            "samples/v0.5/raw/",
            "samples/v0.5/consumer/",
            "docs/v0.5-decision.md",
        ],
    )
    require_terms(
        "docs/v0.5-decision.md",
        [
            "decision: keep",
            "12 fixtures",
            "workflow-router-skill",
            "claude-agent-workflow-designer",
            "samples/v0.5/raw/",
            "samples/v0.5/consumer/",
            "out/v0.5/summary.json",
        ],
    )
    require_fixture_smoke()
    print("contract smoke: pass")


if __name__ == "__main__":
    main()
