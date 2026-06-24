"""V109 Agent Fabric capture bridge.

The bridge converts a V108 reference adapter fixture into a Depone-facing
capture manifest. Agent self-report alone remains A0. Only observer-supplied
local capture material can reach A1, and that material is hash-bound so tamper,
stale source, and unexpected touched-file cases fail closed.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from depone.agent_fabric.reference_adapter import validate_reference_adapter_fixture

CAPTURE_MANIFEST_VERSION = "1.0"
CAPTURE_MANIFEST_KIND = "agent-fabric-capture-manifest"
ASSURANCE_A0 = "A0-claims-only"
ASSURANCE_A1 = "A1-local-observed"
DECISION_CLAIMS_ONLY = "claims-only"
DECISION_OBSERVED = "observed-local-capture"
OBSERVER_ID = "depone-observer"
REQUIRED_OBSERVER_FIELDS = frozenset(
    {
        "observed_by",
        "source_fixture_hash",
        "diff_summary",
        "touched_files",
        "test_output",
        "command_receipts",
    }
)
VALID_TEST_STATUSES = frozenset({"not-run", "passed", "failed", "error"})


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def build_capture_manifest(
    fixture: dict[str, Any],
    *,
    observer_capture: dict[str, Any] | None = None,
    allowed_touched_files: list[str] | None = None,
) -> dict[str, Any]:
    """Build a Depone-facing capture manifest from an adapter fixture.

    ``observer_capture`` is optional. Without it, the manifest is valid but
    remains ``A0-claims-only``. With it, the bridge records an A1 candidate and
    hash-binds the observer payload for validation.
    """

    fixture_copy = deepcopy(fixture)
    fixture_hash = _sha256_json(fixture_copy)
    allowed = _string_list(allowed_touched_files)
    manifest: dict[str, Any] = {
        "schema_version": CAPTURE_MANIFEST_VERSION,
        "kind": CAPTURE_MANIFEST_KIND,
        "source_fixture_hash": fixture_hash,
        "fixture": fixture_copy,
        "allowed_touched_files": allowed,
        "required_observer_fields": sorted(REQUIRED_OBSERVER_FIELDS),
    }

    if observer_capture is None:
        manifest.update(
            {
                "assurance": ASSURANCE_A0,
                "decision": DECISION_CLAIMS_ONLY,
                "observer_capture": None,
                "observer_capture_hash": None,
            }
        )
        return manifest

    observed = deepcopy(observer_capture)
    if not observed.get("source_fixture_hash"):
        observed["source_fixture_hash"] = fixture_hash
    observed_hash = _sha256_json(observed)
    manifest.update(
        {
            "assurance": ASSURANCE_A1,
            "decision": DECISION_OBSERVED,
            "observer_capture": observed,
            "observer_capture_hash": observed_hash,
        }
    )
    return manifest


def validate_capture_manifest(manifest: dict[str, Any]) -> list[str]:
    """Validate a V109 Agent Fabric capture manifest."""

    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["capture_manifest must be an object"]

    _check_top_level(manifest, errors)
    fixture = manifest.get("fixture")
    fixture_hash = manifest.get("source_fixture_hash")
    if isinstance(fixture, dict):
        errors.extend(validate_reference_adapter_fixture(fixture))
        actual_fixture_hash = _sha256_json(fixture)
        if fixture_hash != actual_fixture_hash:
            errors.append("source_fixture_hash mismatch")
    elif "fixture" in manifest:
        errors.append("fixture must be an object")

    assurance = manifest.get("assurance")
    if assurance == ASSURANCE_A0:
        _check_a0_manifest(manifest, errors)
    elif assurance == ASSURANCE_A1:
        _check_a1_manifest(manifest, errors)
    elif "assurance" in manifest:
        errors.append("assurance must be 'A0-claims-only' or 'A1-local-observed'")

    return errors


def _check_top_level(manifest: dict[str, Any], errors: list[str]) -> None:
    required = (
        "schema_version",
        "kind",
        "source_fixture_hash",
        "fixture",
        "assurance",
        "decision",
        "allowed_touched_files",
        "observer_capture",
        "observer_capture_hash",
        "required_observer_fields",
    )
    for field in required:
        if field not in manifest:
            errors.append(f"capture_manifest missing required field: {field}")

    if manifest.get("schema_version") != CAPTURE_MANIFEST_VERSION:
        errors.append(
            "capture_manifest.schema_version expected "
            f"{CAPTURE_MANIFEST_VERSION!r}, got {manifest.get('schema_version')!r}"
        )
    if manifest.get("kind") != CAPTURE_MANIFEST_KIND:
        errors.append(f"capture_manifest.kind expected {CAPTURE_MANIFEST_KIND!r}")
    if "source_fixture_hash" in manifest and not isinstance(
        manifest.get("source_fixture_hash"), str
    ):
        errors.append("source_fixture_hash must be a string")

    allowed = manifest.get("allowed_touched_files")
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) for item in allowed
    ):
        errors.append("allowed_touched_files must be a list of strings")


def _check_a0_manifest(manifest: dict[str, Any], errors: list[str]) -> None:
    if manifest.get("decision") != DECISION_CLAIMS_ONLY:
        errors.append("A0 manifest decision must be 'claims-only'")
    if manifest.get("observer_capture") is not None:
        errors.append("A0 manifest must not include observer_capture")
    if manifest.get("observer_capture_hash") is not None:
        errors.append("A0 manifest must not include observer_capture_hash")


def _check_a1_manifest(manifest: dict[str, Any], errors: list[str]) -> None:
    if manifest.get("decision") != DECISION_OBSERVED:
        errors.append("A1 manifest decision must be 'observed-local-capture'")

    observer_capture = manifest.get("observer_capture")
    if not isinstance(observer_capture, dict):
        errors.append("A1 manifest requires observer_capture object")
        return

    _check_observer_capture_shape(observer_capture, errors)
    expected_hash = manifest.get("observer_capture_hash")
    actual_hash = _sha256_json(observer_capture)
    if expected_hash != actual_hash:
        errors.append("observer_capture_hash mismatch")

    source_fixture_hash = manifest.get("source_fixture_hash")
    observed_source_hash = observer_capture.get("source_fixture_hash")
    if observed_source_hash != source_fixture_hash:
        errors.append("observer_capture.source_fixture_hash is stale")

    allowed = set(_string_list(manifest.get("allowed_touched_files")))
    touched = set(_string_list(observer_capture.get("touched_files")))
    extra = sorted(touched - allowed)
    if extra:
        errors.append(f"unexpected touched files: {extra}")

    diff_summary = observer_capture.get("diff_summary")
    if isinstance(diff_summary, dict):
        changed = set(_string_list(diff_summary.get("changed_files")))
        extra_diff = sorted(changed - allowed)
        if extra_diff:
            errors.append(f"unexpected diff files: {extra_diff}")


def _check_observer_capture_shape(
    observer_capture: dict[str, Any], errors: list[str]
) -> None:
    for field in sorted(REQUIRED_OBSERVER_FIELDS):
        if field not in observer_capture:
            errors.append(f"observer_capture missing required field: {field}")

    if observer_capture.get("observed_by") != OBSERVER_ID:
        errors.append("observer_capture.observed_by must be 'depone-observer'")
    if not isinstance(observer_capture.get("source_fixture_hash"), str):
        errors.append("observer_capture.source_fixture_hash must be a string")

    diff_summary = observer_capture.get("diff_summary")
    if isinstance(diff_summary, dict):
        changed_files = diff_summary.get("changed_files", [])
        if not isinstance(changed_files, list) or not all(
            isinstance(item, str) for item in changed_files
        ):
            errors.append(
                "observer_capture.diff_summary.changed_files must be a list of strings"
            )
    elif "diff_summary" in observer_capture:
        errors.append("observer_capture.diff_summary must be an object")

    touched_files = observer_capture.get("touched_files")
    if not isinstance(touched_files, list) or not all(
        isinstance(item, str) for item in touched_files
    ):
        errors.append("observer_capture.touched_files must be a list of strings")

    test_output = observer_capture.get("test_output")
    if isinstance(test_output, dict):
        status = test_output.get("status")
        if status not in VALID_TEST_STATUSES:
            errors.append(
                f"observer_capture.test_output.status={status!r} not in "
                f"{sorted(VALID_TEST_STATUSES)}"
            )
    elif "test_output" in observer_capture:
        errors.append("observer_capture.test_output must be an object")

    receipts = observer_capture.get("command_receipts")
    if not isinstance(receipts, list) or not all(
        isinstance(item, dict) for item in receipts
    ):
        errors.append("observer_capture.command_receipts must be a list of objects")
    elif not receipts:
        errors.append("observer_capture.command_receipts must be non-empty for A1")
    else:
        for i, receipt in enumerate(receipts):
            if "command" not in receipt:
                errors.append(f"observer_capture.command_receipts[{i}] missing command")
            if not isinstance(receipt.get("exit_code"), int):
                errors.append(
                    f"observer_capture.command_receipts[{i}].exit_code must be an int"
                )


def _self_test() -> None:
    print("depone agent_fabric capture_bridge --self-test")

    from depone.agent_fabric.reference_adapter import build_reference_adapter_fixture

    invocation = {
        "packet_version": "1.0",
        "target_harness": "shell",
        "profile": "self-test-profile",
        "role": "runner",
        "toolbelt": {
            "allowed_tools": ["cat", "python3"],
            "allowed_mcp": [],
            "forbidden_tools": ["write"],
            "context_policy": "local-code-only",
            "output_schema": "runner-result-v1",
            "evidence_obligations": ["command_receipt"],
        },
        "instructions": "Run checks and report outputs.",
        "evidence_obligations": ["command_receipt"],
        "context_policy": "local-code-only",
    }
    result = {
        "result_version": "1.0",
        "agent_role": "runner",
        "profile": "self-test-profile",
        "status": "success",
        "output_files": ["out/agent/result.txt"],
        "self_reported_claims": ["checks completed"],
        "command_receipts": [],
    }
    fixture = build_reference_adapter_fixture(invocation, self_report=result)
    observer_capture = {
        "observed_by": "depone-observer",
        "source_fixture_hash": "",
        "diff_summary": {"changed_files": ["depone/example.py"]},
        "touched_files": ["depone/example.py"],
        "test_output": {"status": "passed", "summary": "1 passed"},
        "command_receipts": [
            {
                "command": ["python3", "test.py"],
                "exit_code": 0,
                "log_path": "logs/test.txt",
            }
        ],
    }

    a1 = build_capture_manifest(
        fixture,
        observer_capture=observer_capture,
        allowed_touched_files=["depone/example.py"],
    )
    assert not validate_capture_manifest(a1)
    print("  [PASS] valid observer capture reaches A1")

    a0 = build_capture_manifest(fixture)
    assert a0["assurance"] == ASSURANCE_A0
    assert not validate_capture_manifest(a0)
    print("  [PASS] self-report-only manifest stays A0")

    tampered = deepcopy(a1)
    tampered["observer_capture"]["test_output"]["summary"] = "tampered"
    assert any(
        "observer_capture_hash mismatch" in e
        for e in validate_capture_manifest(tampered)
    )
    print("  [PASS] tampered observer capture rejected")

    stale = build_capture_manifest(
        fixture,
        observer_capture=dict(observer_capture, source_fixture_hash="stale"),
        allowed_touched_files=["depone/example.py"],
    )
    assert any(
        "source_fixture_hash is stale" in e for e in validate_capture_manifest(stale)
    )
    print("  [PASS] stale source fixture rejected")

    extra = build_capture_manifest(
        fixture,
        observer_capture=dict(
            observer_capture,
            touched_files=["depone/example.py", "README.md"],
            diff_summary={"changed_files": ["depone/example.py", "README.md"]},
        ),
        allowed_touched_files=["depone/example.py"],
    )
    assert any(
        "unexpected touched files" in e for e in validate_capture_manifest(extra)
    )
    print("  [PASS] unexpected touched files rejected")

    print("\nSelf-test: 5/5 passed")


if __name__ == "__main__":
    _self_test()
