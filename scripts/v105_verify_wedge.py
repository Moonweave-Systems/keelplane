#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from depone.core.plan_schema import load_plan  # noqa: E402
from depone.verify.adapters import generic  # noqa: E402
from depone.verify.engine import run_verification  # noqa: E402


FIXTURE_ROOT = ROOT / "fixtures" / "v105-verify-wedge"


def _load_cases() -> dict:
    with open(FIXTURE_ROOT / "cases.json", encoding="utf-8") as handle:
        return json.load(handle)


def self_test() -> None:
    plan = load_plan(FIXTURE_ROOT / "plan.json")
    manifest = _load_cases()
    cases = manifest.get("cases", [])
    expected_tests = len(cases)

    tests = 0
    passed = 0

    for case in cases:
        tests += 1
        case_name = case["name"]
        evidence_dir = FIXTURE_ROOT / case["evidence_dir"]
        expected_verdict = case["expect"]["verdict"]
        expected_codes = case["expect"].get("codes", [])

        report = run_verification(plan, generic.read_evidence(str(evidence_dir)))
        report_dict = asdict(report)
        contract_entries = report_dict["evidence_contract"]
        actual_codes = [entry["code"] for entry in contract_entries]

        if report_dict["verdict"] != expected_verdict:
            raise AssertionError(
                f"{case_name}: expected {expected_verdict}, got {report_dict['verdict']}"
            )
        if sorted(actual_codes) != sorted(expected_codes):
            raise AssertionError(
                f"{case_name}: expected only codes {expected_codes}, got {actual_codes}"
            )
        if expected_verdict == "verified" and contract_entries:
            raise AssertionError(
                f"{case_name}: verified case must not emit contract errors"
            )
        passed += 1

    if tests != expected_tests:
        raise AssertionError(f"expected {expected_tests} cases, got {tests}")

    print(f"v105 verify wedge self-test: {passed}/{tests} passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test", action="store_true", help="run the V105 verify wedge self-test"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.self_test:
        print("use --self-test", file=sys.stderr)
        return 1
    self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
