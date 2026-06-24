#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import evaluate_plan  # noqa: E402
from depone.core.embedded_plan_contract import validate_embedded_contract  # noqa: E402
from depone.core.plan_schema import load_plan  # noqa: E402
from depone.verify.adapters import generic  # noqa: E402
from depone.verify.engine import run_verification  # noqa: E402


FIXTURE_ROOT = ROOT / "fixtures" / "v106-multi-wave"
V105_FIXTURE_ROOT = ROOT / "fixtures" / "v105-verify-wedge"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def read_v105_cases() -> dict[str, dict[str, Any]]:
    manifest = read_json(V105_FIXTURE_ROOT / "cases.json")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise evaluate_plan.EvaluationError("v105 cases fixture must list cases")
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str):
            raise evaluate_plan.EvaluationError(
                "v105 case entries must be named objects"
            )
        result[case["name"]] = case
    return result


def run_v105_case(case: dict[str, Any]) -> dict[str, Any]:
    evidence_dir = case.get("evidence_dir")
    if not isinstance(evidence_dir, str) or not evidence_dir:
        raise evaluate_plan.EvaluationError("v105 case evidence_dir is missing")
    report = run_verification(
        load_plan(V105_FIXTURE_ROOT / "plan.json"),
        generic.read_evidence(str(V105_FIXTURE_ROOT / evidence_dir)),
    )
    report_data = asdict(report)
    contract_entries = report_data["evidence_contract"]
    return {
        "case_id": case["name"],
        "actual_verdict": report_data["verdict"],
        "actual_codes": sorted(entry["code"] for entry in contract_entries),
    }


def collect_v105_case_results(case_ids: list[str]) -> list[dict[str, Any]]:
    cases = read_v105_cases()
    results = []
    for case_id in case_ids:
        case = cases.get(case_id)
        if case is None:
            raise evaluate_plan.EvaluationError(f"v105 case is missing: {case_id}")
        results.append(run_v105_case(case))
    return results


def assert_plan_outcome(
    plan: dict[str, Any], *, expect_pass: bool, label: str, error_contains: str | None
) -> None:
    evaluate_error = ""
    try:
        evaluate_plan.validate_plan(plan, require_dynamic_created_by=False)
    except evaluate_plan.EvaluationError as exc:
        evaluate_error = str(exc)
        if expect_pass:
            raise evaluate_plan.EvaluationError(
                f"{label}: evaluate_plan.validate_plan should pass"
            )
    else:
        if not expect_pass:
            raise evaluate_plan.EvaluationError(
                f"{label}: evaluate_plan.validate_plan should fail"
            )

    embedded_errors = validate_embedded_contract(plan)
    if expect_pass and embedded_errors:
        raise evaluate_plan.EvaluationError(f"{label}: embedded contract should pass")
    if not expect_pass and not embedded_errors:
        raise evaluate_plan.EvaluationError(f"{label}: embedded contract should fail")
    if error_contains is not None:
        combined_error = evaluate_error + "\n" + "\n".join(embedded_errors)
        if error_contains not in combined_error:
            raise evaluate_plan.EvaluationError(
                f"{label}: expected error containing {error_contains!r}"
            )


def validate_progression_fixture(
    plan: dict[str, Any], expected: dict[str, Any]
) -> None:
    execution = plan["execution_path"]
    first_wave = execution["first_wave"]
    waves = execution["waves"]
    chain = expected.get("receipt_chain")
    if not isinstance(chain, list) or len(chain) != len(waves) + 1:
        raise evaluate_plan.EvaluationError(
            "v106 receipt fixture must cover first_wave plus every follow-on wave"
        )
    if chain[0].get("wave_id") != first_wave["id"]:
        raise evaluate_plan.EvaluationError(
            "v106 receipt fixture must start at first_wave"
        )
    expected_wave_ids = [first_wave["id"], *[wave["id"] for wave in waves]]
    actual_wave_ids = [item.get("wave_id") for item in chain]
    if actual_wave_ids != expected_wave_ids:
        raise evaluate_plan.EvaluationError(
            "v106 receipt fixture order must match the execution path"
        )
    for previous, item in zip(chain, chain[1:]):
        wave_id = item.get("wave_id")
        if previous.get("receipt") != "verified" or wave_id not in previous.get(
            "unlocks", []
        ):
            raise evaluate_plan.EvaluationError(
                f"v106 receipt fixture does not unlock {wave_id}"
            )
        entry_gate = str(item.get("entry_gate", "")).lower()
        if not all(term in entry_gate for term in ["receipt", "verified"]):
            raise evaluate_plan.EvaluationError(
                f"v106 receipt fixture entry gate is not verified for {wave_id}"
            )


def validate_v105_wave_receipts(expected: dict[str, Any]) -> None:
    case_ids = expected.get("v105_wave_1_cases")
    if case_ids != [
        "missing-test-log",
        "forbidden-file-touch",
        "test-weakened",
        "good",
    ]:
        raise evaluate_plan.EvaluationError(
            "v106 receipt fixture must name the selected V105 wave-1 cases"
        )
    chain = expected.get("receipt_chain")
    if not isinstance(chain, list) or not chain:
        raise evaluate_plan.EvaluationError(
            "v106 receipt fixture must include a receipt chain"
        )
    first_receipt = chain[0]
    if not isinstance(first_receipt, dict):
        raise evaluate_plan.EvaluationError("v106 wave-1 receipt must be an object")
    if (
        first_receipt.get("wave_id") != "wave-1"
        or first_receipt.get("receipt") != "verified"
    ):
        raise evaluate_plan.EvaluationError("v106 wave-1 receipt must be verified")
    if first_receipt.get("unlocks") != ["wave-2"]:
        raise evaluate_plan.EvaluationError(
            "v106 wave-1 receipt must unlock only wave-2"
        )
    expected_results = first_receipt.get("case_results")
    if not isinstance(expected_results, list) or len(expected_results) != len(case_ids):
        raise evaluate_plan.EvaluationError(
            "v106 wave-1 receipt must include all selected V105 case results"
        )
    expected_by_case = {
        item.get("case_id"): item for item in expected_results if isinstance(item, dict)
    }
    actual_results = collect_v105_case_results(case_ids)
    for actual in actual_results:
        case_id = actual["case_id"]
        expected_case = expected_by_case.get(case_id)
        if expected_case is None:
            raise evaluate_plan.EvaluationError(
                f"v106 wave-1 receipt missing V105 case result: {case_id}"
            )
        expected_codes = sorted(
            expected_case.get("expected_codes")
            if isinstance(expected_case.get("expected_codes"), list)
            else []
        )
        if expected_case.get("status") != "matched":
            raise evaluate_plan.EvaluationError(
                f"v106 wave-1 receipt case is not matched: {case_id}"
            )
        if actual["actual_verdict"] != expected_case.get("expected_verdict"):
            raise evaluate_plan.EvaluationError(
                f"v106 wave-1 receipt verdict drifted for {case_id}"
            )
        if actual["actual_codes"] != expected_codes:
            raise evaluate_plan.EvaluationError(
                f"v106 wave-1 receipt codes drifted for {case_id}"
            )


def self_test() -> None:
    manifest = read_json(FIXTURE_ROOT / "manifest.json")
    fixtures = manifest.get("fixtures")
    if manifest.get("suite_id") != "v106-multi-wave":
        raise evaluate_plan.EvaluationError("v106 manifest has the wrong suite id")
    if not isinstance(fixtures, list) or len(fixtures) != 6:
        raise evaluate_plan.EvaluationError(
            "v106 manifest must list six deterministic fixtures"
        )

    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise evaluate_plan.EvaluationError("v106 fixture entry must be an object")
        plan_name = fixture.get("plan")
        expect = fixture.get("expect")
        label = fixture.get("id", "v106-fixture")
        if not isinstance(plan_name, str) or not plan_name:
            raise evaluate_plan.EvaluationError(f"{label}: plan path is missing")
        if not isinstance(expect, dict):
            raise evaluate_plan.EvaluationError(f"{label}: expect block is missing")
        plan = read_json(FIXTURE_ROOT / plan_name)
        expected_evaluate = expect.get("evaluate_plan")
        expected_embedded = expect.get("embedded_contract")
        error_contains = expect.get("error_contains")
        if expected_evaluate not in {"pass", "fail"} or expected_embedded not in {
            "pass",
            "fail",
        }:
            raise evaluate_plan.EvaluationError(
                f"{label}: expect block must use pass/fail values"
            )
        if error_contains is not None and not isinstance(error_contains, str):
            raise evaluate_plan.EvaluationError(
                f"{label}: error_contains must be a string"
            )
        expect_pass = expected_evaluate == "pass"
        if (expected_embedded == "pass") != expect_pass:
            raise evaluate_plan.EvaluationError(
                f"{label}: embedded contract expectation must match evaluate_plan"
            )
        assert_plan_outcome(
            plan, expect_pass=expect_pass, label=label, error_contains=error_contains
        )

    progression = read_json(FIXTURE_ROOT / "expected-wave-receipts.json")
    validate_progression_fixture(
        read_json(FIXTURE_ROOT / "multi-wave-plan.json"), progression
    )
    validate_v105_wave_receipts(progression)

    print("v106 multi-wave self-test: pass")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("use --self-test")
    self_test()


if __name__ == "__main__":
    main()
