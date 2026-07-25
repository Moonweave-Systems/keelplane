#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from depone.verify.adapters.generic import read_evidence
from depone.verify.engine import run_verification


FIXTURE_ROOT = ROOT / "depone/fixtures/code_health/tiered_mixed"


def _plan() -> dict[str, object]:
    return {
        "schema_version": "0.5",
        "plan_id": "code-health-revalidation",
        "phases": [{"id": "phase-1"}],
    }


def _actual_result() -> dict[str, Any]:
    report = run_verification(_plan(), read_evidence(str(FIXTURE_ROOT)))
    return {
        "decision": report.decision,
        "error_codes": [entry.code for entry in report.evidence_contract],
        "health_conformance": asdict(report.health_conformance),
    }


def _expected_result() -> dict[str, Any]:
    parsed = json.loads(
        (FIXTURE_ROOT / "expected-verdict.json").read_text(encoding="utf-8")
    )
    if not isinstance(parsed, dict):
        raise AssertionError("expected-verdict.json must contain an object")
    return parsed


def _assert_result(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    if actual != expected:
        raise AssertionError(
            "code health fixture mismatch:\n"
            f"expected={json.dumps(expected, sort_keys=True)}\n"
            f"actual={json.dumps(actual, sort_keys=True)}"
        )


def revalidate() -> dict[str, Any]:
    actual = _actual_result()
    _assert_result(actual, _expected_result())
    return actual


def self_test() -> None:
    actual = revalidate()
    wrong = dict(actual)
    wrong["decision"] = "fail"
    try:
        _assert_result(actual, wrong)
    except AssertionError:
        pass
    else:
        raise AssertionError("self-test failed: mismatched decision was accepted")
    print("code health revalidator self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    actual = revalidate()
    for axis in actual["health_conformance"]["axes"]:
        print(
            f"{axis['gate']}: {axis['status']} "
            f"enforcement={axis['enforcement']} "
            f"blocks_handoff={axis['blocks_handoff']}"
        )
    print("code health fixture: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
