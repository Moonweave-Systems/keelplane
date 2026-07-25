from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from depone.agent_fabric.claim_gate import canonical_hash
from depone.agent_fabric.evidence_substrate import decode_dsse_payload
from depone.agent_fabric.paired_run import validate_runner_receipt
from depone.agent_fabric.sign import verify_dsse_envelope
from depone.verify.adapters.base import EvidenceContext


@dataclass
class EvidenceContractEntry:
    code: str
    message: str
    evidence_path: str
    health_gate: dict[str, str] | None = None


_EVIDENCE_CONTRACT_FILENAME = "evidence-contract.json"
_CONTRACT_SCHEMA_VERSION = "v105.verify_wedge"
_ROLE_CAPABILITY_CONTRACT_SCHEMA_VERSION = "v106.role_capability_write_scope"
_ROLE_CAPABILITY_TOOL_CALLS_CONTRACT_SCHEMA_VERSION = "v107.role_capability_tool_calls"
_ADVISORY_PROVENANCE_CONTRACT_SCHEMA_VERSION = "v108.advisory_provenance"
_ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION = "v110.advisory_provenance"
_ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION = (
    "v109.role_capability_write_scope"
)
_ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION = (
    "v110.role_capability_skill_routing"
)
_CODE_HEALTH_CONTRACT_SCHEMA_VERSION = "v111.code_health"
_OBSERVED_TOUCHED_FILES_FILENAME = "observed-touched-files.txt"
_OBSERVED_SKILLS_FILENAME = "observed-skills.txt"
# Deprecated compatibility alias for evidence sealed before the honest rename.
_LEGACY_TOUCHED_FILES_FILENAME = "git-diff-name-only.txt"
_OBSERVATION_FILENAMES = (
    _OBSERVED_TOUCHED_FILES_FILENAME,
    _LEGACY_TOUCHED_FILES_FILENAME,
)
_ROOT_CONTROL_FILENAMES = frozenset(
    {
        "evidence-contract.json",
        _OBSERVED_TOUCHED_FILES_FILENAME,
        _OBSERVED_SKILLS_FILENAME,
        _LEGACY_TOUCHED_FILES_FILENAME,
        "git-diff.patch",
    }
)
_ERR_CONTRACT_INVALID = "ERR_EVIDENCE_CONTRACT_INVALID"
_ERR_CONTRACT_MISSING = "ERR_EVIDENCE_CONTRACT_MISSING"
_ERR_CONTRACT_SHADOWED = "ERR_EVIDENCE_CONTRACT_SHADOWED"
_ERR_REQUIRED_TEST_EVIDENCE_MISSING = "ERR_REQUIRED_TEST_EVIDENCE_MISSING"
_ERR_TEST_EXIT_CODE_MISMATCH = "ERR_TEST_EXIT_CODE_MISMATCH"
_ERR_FORBIDDEN_FILE_TOUCHED = "ERR_FORBIDDEN_FILE_TOUCHED"
_ERR_TEST_WEAKENED = "ERR_TEST_WEAKENED"
_ERR_ROLE_CAPABILITY_RUN_INTENT_MISSING = "ERR_ROLE_CAPABILITY_RUN_INTENT_MISSING"
_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID = "ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID"
_ERR_ROLE_CAPABILITY_SIGNATURE_MISSING = "ERR_ROLE_CAPABILITY_SIGNATURE_MISSING"
_ERR_ROLE_CAPABILITY_SIGNATURE_INVALID = "ERR_ROLE_CAPABILITY_SIGNATURE_INVALID"
_ERR_ROLE_CAPABILITY_TRUST_ANCHOR_MISSING = "ERR_ROLE_CAPABILITY_TRUST_ANCHOR_MISSING"
_ERR_ROLE_CAPABILITY_WRITE_SCOPE_VIOLATION = "ERR_ROLE_CAPABILITY_WRITE_SCOPE_VIOLATION"
_ERR_ROLE_CAPABILITY_SKILL_ROUTING_VIOLATION = (
    "ERR_ROLE_CAPABILITY_SKILL_ROUTING_VIOLATION"
)
_ERR_HEALTH_GATE_VIOLATION = "ERR_HEALTH_GATE_VIOLATION"
_ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT = (
    "ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT"
)
_ERR_HEALTH_GATE_ARTIFACT_MISSING = "ERR_HEALTH_GATE_ARTIFACT_MISSING"
_ERR_HEALTH_GATE_ARTIFACT_DIGEST_MISMATCH = (
    "ERR_HEALTH_GATE_ARTIFACT_DIGEST_MISMATCH"
)
_ERR_ROLE_CAPABILITY_OBSERVATION_UNBOUND = "ERR_ROLE_CAPABILITY_OBSERVATION_UNBOUND"
_ERR_ROLE_CAPABILITY_OBSERVATION_DIGEST_MISMATCH = (
    "ERR_ROLE_CAPABILITY_OBSERVATION_DIGEST_MISMATCH"
)
_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_MISSING = "ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_MISSING"
_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID = "ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID"
_ERR_ROLE_CAPABILITY_TOOL_GRANT_MISSING = "ERR_ROLE_CAPABILITY_TOOL_GRANT_MISSING"
_ERR_ROLE_CAPABILITY_TOOL_DECISION_MISMATCH = (
    "ERR_ROLE_CAPABILITY_TOOL_DECISION_MISMATCH"
)
_ERR_ROLE_CAPABILITY_TOOL_ALLOW_OUTSIDE_GRANT = (
    "ERR_ROLE_CAPABILITY_TOOL_ALLOW_OUTSIDE_GRANT"
)
_ERR_ROLE_CAPABILITY_TOOL_RECEIPT_MISSING = "ERR_ROLE_CAPABILITY_TOOL_RECEIPT_MISSING"
_ERR_ROLE_CAPABILITY_TOOL_DENY_EXECUTED = "ERR_ROLE_CAPABILITY_TOOL_DENY_EXECUTED"
_ERR_ROLE_CAPABILITY_TOOL_REQUEST_HASH_MISMATCH = (
    "ERR_ROLE_CAPABILITY_TOOL_REQUEST_HASH_MISMATCH"
)
_ERR_ROLE_CAPABILITY_TOOL_SEQUENCE_GAP = "ERR_ROLE_CAPABILITY_TOOL_SEQUENCE_GAP"
_ERR_ROLE_CAPABILITY_TOOL_BUNDLE_DIGEST_MISMATCH = (
    "ERR_ROLE_CAPABILITY_TOOL_BUNDLE_DIGEST_MISMATCH"
)
_ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID = "ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID"
_ERR_ADVISORY_SKETCH_CHOSEN_NOT_IN_CANDIDATES = (
    "ERR_ADVISORY_SKETCH_CHOSEN_NOT_IN_CANDIDATES"
)
_ERR_ADVISORY_SKETCH_CHOSEN_ALSO_REJECTED = "ERR_ADVISORY_SKETCH_CHOSEN_ALSO_REJECTED"
_ERR_ADVISORY_SKETCH_REJECTED_REASON_MISSING = (
    "ERR_ADVISORY_SKETCH_REJECTED_REASON_MISSING"
)
_ERR_ADVISORY_SKETCH_TAMPER = "ERR_ADVISORY_SKETCH_TAMPER"
_ERR_ADVISORY_TRACE_CONFIRMED_UNBACKED = "ERR_ADVISORY_TRACE_CONFIRMED_UNBACKED"
_ERR_ADVISORY_TRACE_UNRELATED_RED = "ERR_ADVISORY_TRACE_UNRELATED_RED"
_ERR_ADVISORY_TRACE_RIVAL_NOT_RULED_OUT = "ERR_ADVISORY_TRACE_RIVAL_NOT_RULED_OUT"
_ERR_ADVISORY_TRACE_RECEIPT_HASH_MISMATCH = "ERR_ADVISORY_TRACE_RECEIPT_HASH_MISMATCH"
_ERR_ADVISORY_TRACE_RED_NOT_EXECUTED = "ERR_ADVISORY_TRACE_RED_NOT_EXECUTED"
_ERR_ADVISORY_TRACE_TAMPER = "ERR_ADVISORY_TRACE_TAMPER"


def _evidence_map(evidence: EvidenceContext) -> dict[str, Any]:
    return {f.path: f for f in evidence.files}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _find_evidence_file(evidence: EvidenceContext, name: str) -> tuple[str, str] | None:
    for entry in evidence.files:
        if entry.path == name:
            return entry.path, entry.content
    return None


def _evidence_file_entry(evidence: EvidenceContext, name: str) -> Any | None:
    for entry in evidence.files:
        if entry.path == name:
            return entry
    return None


def _find_observation_entry(evidence: EvidenceContext) -> Any | None:
    for filename in _OBSERVATION_FILENAMES:
        entry = _evidence_file_entry(evidence, filename)
        if entry is not None:
            return entry
    return None


def _find_control_shadow(evidence: EvidenceContext) -> EvidenceContractEntry | None:
    for entry in evidence.files:
        filename = Path(entry.path).name
        if filename in _ROOT_CONTROL_FILENAMES and entry.path != filename:
            return EvidenceContractEntry(
                code=_ERR_CONTRACT_SHADOWED,
                message=f"control file must be root-relative, found nested {filename}: {entry.path}",
                evidence_path=entry.path,
            )
    return None


def _read_evidence_contract(
    evidence: EvidenceContext,
) -> tuple[dict[str, Any] | None, EvidenceContractEntry | None]:
    found = _find_evidence_file(evidence, _EVIDENCE_CONTRACT_FILENAME)
    if found is None:
        return None, EvidenceContractEntry(
            code=_ERR_CONTRACT_MISSING,
            message="evidence-contract.json is required at the evidence root",
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    evidence_path, content = found
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message="evidence-contract.json is not valid JSON",
            evidence_path=evidence_path,
        )
    if not isinstance(parsed, dict):
        return None, EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message="evidence-contract.json must contain a JSON object",
            evidence_path=evidence_path,
        )
    return parsed, None


def _has_actionable_command(command: Any) -> bool:
    if not isinstance(command, dict):
        return False
    return isinstance(command.get("log_path"), str) or isinstance(
        command.get("expected_exit_code"),
        int,
    )


def _has_non_empty_str_list(contract: dict[str, Any], *keys: str) -> bool:
    return any(_as_str_list(contract.get(key)) for key in keys)


def _has_enforcement_directive(contract: dict[str, Any]) -> bool:
    if _has_non_empty_str_list(
        contract,
        "required_evidence",
        "required_paths",
        "required_evidence_paths",
    ):
        return True
    required_commands = contract.get("required_commands")
    if isinstance(required_commands, list) and any(
        _has_actionable_command(command) for command in required_commands
    ):
        return True
    if isinstance(contract.get("expected_exit_code"), int):
        return True
    if _has_non_empty_str_list(contract, "allowed_touched_files", "allowed_files"):
        return True
    if _has_non_empty_str_list(contract, "forbidden_touched_files", "forbidden_files"):
        return True
    if _has_non_empty_str_list(contract, "forbidden_test_files"):
        return True
    if isinstance(contract.get("role_capability_write_scope"), dict):
        return True
    if isinstance(contract.get("role_capability_tool_calls"), dict):
        return True
    if isinstance(contract.get("role_capability_skill_routing"), dict):
        return True
    if "code_health" in contract:
        return True
    if isinstance(contract.get("advisory_provenance"), dict):
        return True
    return contract.get("forbid_test_weakening") is True and _has_non_empty_str_list(
        contract,
        "test_file_patterns",
    )


def _validate_contract_semantics(
    contract: dict[str, Any],
) -> EvidenceContractEntry | None:
    schema_version = contract.get("schema_version")
    if schema_version not in {
        _CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_TOOL_CALLS_CONTRACT_SCHEMA_VERSION,
        _ADVISORY_PROVENANCE_CONTRACT_SCHEMA_VERSION,
        _ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION,
        _CODE_HEALTH_CONTRACT_SCHEMA_VERSION,
    }:
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=(
                "evidence-contract.json must declare schema_version "
                f"{_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ROLE_CAPABILITY_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ROLE_CAPABILITY_TOOL_CALLS_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ADVISORY_PROVENANCE_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_CODE_HEALTH_CONTRACT_SCHEMA_VERSION!r}"
            ),
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    if (
        isinstance(contract.get("role_capability_write_scope"), dict)
        and schema_version
        not in {
            _ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION,
            _ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION,
        }
    ):
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=(
                "role_capability_write_scope requires schema_version "
                f"{_ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION!r} "
                "(the bound-observation schemas); earlier versions cannot bind "
                "the git-diff observation to the signed bundle and are refused"
            ),
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    if isinstance(
        contract.get("role_capability_tool_calls"), dict
    ) and schema_version not in {
        _ROLE_CAPABILITY_TOOL_CALLS_CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION,
    }:
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=(
                "role_capability_tool_calls requires schema_version "
                f"{_ROLE_CAPABILITY_TOOL_CALLS_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION!r} "
                f"or {_ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION!r} "
                "(the bound-observation schemas, for contracts that also carry "
                "bound observation directives)"
            ),
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    if (
        isinstance(contract.get("role_capability_skill_routing"), dict)
        and schema_version != _ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION
    ):
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=(
                "role_capability_skill_routing requires schema_version "
                f"{_ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION!r}"
            ),
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    if (
        "code_health" in contract
        and schema_version != _CODE_HEALTH_CONTRACT_SCHEMA_VERSION
    ):
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=(
                "code_health requires schema_version "
                f"{_CODE_HEALTH_CONTRACT_SCHEMA_VERSION!r}"
            ),
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    if isinstance(contract.get("advisory_provenance"), dict) and schema_version not in {
        _ADVISORY_PROVENANCE_CONTRACT_SCHEMA_VERSION,
        _ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION,
    }:
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=(
                "advisory_provenance requires schema_version "
                f"{_ADVISORY_PROVENANCE_CONTRACT_SCHEMA_VERSION!r} or "
                f"{_ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION!r}"
            ),
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    if not _has_enforcement_directive(contract):
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message="evidence-contract.json must declare at least one enforcement directive",
            evidence_path=_EVIDENCE_CONTRACT_FILENAME,
        )
    return None


def _read_exit_code(evidence: EvidenceContext, exit_code_path: str) -> int | None:
    evidence_map = _evidence_map(evidence)
    exit_code_file = evidence_map.get(exit_code_path)
    if exit_code_file is not None:
        try:
            return int(exit_code_file.content.strip())
        except ValueError:
            return None

    metadata = evidence.raw.get("metadata")
    if isinstance(metadata, dict):
        exit_code = metadata.get("exit_code")
        if isinstance(exit_code, int):
            return exit_code
    return None


def _touched_files(evidence: EvidenceContext) -> list[str]:
    entry = _find_observation_entry(evidence)
    if entry is None:
        return []
    return [line.strip() for line in entry.content.splitlines() if line.strip()]


def _observed_skills(evidence: EvidenceContext) -> list[str]:
    entry = _evidence_file_entry(evidence, _OBSERVED_SKILLS_FILENAME)
    if entry is None:
        return []
    return [line.strip() for line in entry.content.splitlines() if line.strip()]


def _json_object(
    content: str,
    path: str,
    error_code: str = _ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
) -> tuple[dict[str, Any] | None, EvidenceContractEntry | None]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, EvidenceContractEntry(
            code=error_code,
            message=f"{path} is not valid JSON",
            evidence_path=path,
        )
    if not isinstance(parsed, dict):
        return None, EvidenceContractEntry(
            code=error_code,
            message=f"{path} must contain a JSON object",
            evidence_path=path,
        )
    return parsed, None


def _run_intent_payload(intent_artifact: dict[str, Any]) -> dict[str, Any] | None:
    envelope = intent_artifact.get("dsse_envelope")
    if not isinstance(envelope, dict):
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, str):
        return None
    try:
        decoded = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        parsed = json.loads(decoded)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _subject_digest(bundle: dict[str, Any], name: str) -> str | None:
    statement = bundle.get("statement")
    if not isinstance(statement, dict):
        return None
    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        return None
    for subject in subjects:
        if not isinstance(subject, dict) or subject.get("name") != name:
            continue
        digest = subject.get("digest")
        if isinstance(digest, dict) and isinstance(digest.get("sha256"), str):
            return digest["sha256"]
    return None


def _find_observation_subject(
    bundle: dict[str, Any],
    filenames: tuple[str, ...] = _OBSERVATION_FILENAMES,
) -> tuple[str, str] | None:
    for filename in filenames:
        digest = _subject_digest(bundle, filename)
        if digest is not None:
            return filename, digest
    return None


def _path_allowed_by_scope(path: str, write_scope: list[str]) -> bool:
    return any(
        path == pattern or fnmatch.fnmatchcase(path, pattern) for pattern in write_scope
    )


def _matches_any_pattern(value: str, patterns: list[str]) -> bool:
    return any(value == pattern or fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _run_intent_digest_matches(
    expected_digest: str,
    run_intent_content: str,
    intent: dict[str, Any],
) -> bool:
    raw_digest = hashlib.sha256(run_intent_content.encode("utf-8")).hexdigest()
    # witnessd bundles bind the raw run-intent artifact bytes. Depone's existing
    # evidence-substrate helper binds the canonical intent object. Accept both so
    # the verifier remains compatible with both producers while still requiring
    # the DSSE payload and intent object to match.
    return expected_digest in {raw_digest, canonical_hash(intent)}


def _raw_artifact_digest_matches(expected_digest: str, content: str) -> bool:
    return expected_digest == hashlib.sha256(content.encode("utf-8")).hexdigest()


def _health_evidence_substrates(
    evidence: EvidenceContext,
    contract: dict[str, Any],
) -> tuple[dict[str, str], list[EvidenceContractEntry]]:
    directive = contract.get("code_health")
    if not isinstance(directive, dict):
        return {}, []
    gates = directive.get("gates")
    if not isinstance(gates, list):
        return {}, []
    substrates = {
        gate["gate"]: "producer-transcribed"
        for gate in gates
        if isinstance(gate, dict) and isinstance(gate.get("gate"), str)
    }
    manifest_path = directive.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path:
        manifest_path = "health-gate-artifacts.json"
    manifest_entry = _evidence_file_entry(evidence, manifest_path)
    if manifest_entry is None:
        return substrates, []

    bundle_path = directive.get("bundle_path")
    if not isinstance(bundle_path, str) or not bundle_path:
        bundle_path = "bundle.json"
    bundle_entry = _evidence_file_entry(evidence, bundle_path)
    if bundle_entry is None:
        return substrates, [
            EvidenceContractEntry(
                code=_ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT,
                message=f"health manifest {manifest_path} is not a subject in {bundle_path}",
                evidence_path=bundle_path,
            )
        ]
    bundle, invalid = _json_object(bundle_entry.content, bundle_path)
    if invalid is not None or bundle is None:
        return substrates, [
            EvidenceContractEntry(
                code=_ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT,
                message=f"health manifest {manifest_path} is not a subject in {bundle_path}",
                evidence_path=bundle_path,
            )
        ]
    verified_bundle, signature_error = _verified_role_capability_bundle(
        evidence, bundle, bundle_path
    )
    if signature_error is not None or verified_bundle is None:
        return substrates, [
            signature_error
            if signature_error is not None
            else EvidenceContractEntry(
                code=_ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT,
                message=f"health manifest {manifest_path} is not a verified bundle subject",
                evidence_path=bundle_path,
            )
        ]
    bundle = verified_bundle
    expected_manifest_digest = _subject_digest(bundle, manifest_path)
    if expected_manifest_digest is None or not _raw_artifact_digest_matches(
        expected_manifest_digest, manifest_entry.content
    ):
        return substrates, [
            EvidenceContractEntry(
                code=_ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT,
                message=f"health manifest {manifest_path} is not a verified bundle subject",
                evidence_path=bundle_path,
            )
        ]
    manifest, invalid = _json_object(
        manifest_entry.content,
        manifest_path,
        _ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT,
    )
    if invalid is not None or manifest is None:
        return substrates, [invalid] if invalid is not None else []
    manifest_gates = manifest.get("gates")
    if not isinstance(manifest_gates, list):
        return substrates, [
            EvidenceContractEntry(
                code=_ERR_HEALTH_GATE_MANIFEST_NOT_BUNDLE_SUBJECT,
                message=f"health manifest {manifest_path} must contain gates",
                evidence_path=manifest_path,
            )
        ]
    for item in manifest_gates:
        if not isinstance(item, dict):
            continue
        gate_id = item.get("gate")
        if not isinstance(gate_id, str):
            continue
        for path_key, digest_key in (
            ("exit_code_path", "exit_code_sha256"),
            ("log_path", "log_sha256"),
        ):
            path = item.get(path_key)
            expected_digest = item.get(digest_key)
            if not isinstance(path, str) or not isinstance(expected_digest, str):
                continue
            artifact = _evidence_file_entry(evidence, path)
            if artifact is None:
                return substrates, [
                    EvidenceContractEntry(
                        code=_ERR_HEALTH_GATE_ARTIFACT_MISSING,
                        message=f"health gate artifact missing: {path}",
                        evidence_path=path,
                    )
                ]
            if not _raw_artifact_digest_matches(expected_digest, artifact.content):
                return substrates, [
                    EvidenceContractEntry(
                        code=_ERR_HEALTH_GATE_ARTIFACT_DIGEST_MISMATCH,
                        message=f"health gate artifact digest mismatch: {path}",
                        evidence_path=path,
                    )
                ]
        if gate_id in substrates:
            substrates[gate_id] = "bound"
    return substrates, []


def _canonical_decision_hash(decision: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            decision,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _decision_receipt_key(item: dict[str, Any]) -> tuple[str, str] | None:
    canonical_tool_name = item.get("canonical_tool_name")
    request_sha256 = item.get("canonical_request_sha256")
    if not isinstance(canonical_tool_name, str) or not isinstance(
        request_sha256,
        str,
    ):
        return None
    return canonical_tool_name, request_sha256


def _role_capability_signature_entry(
    code: str,
    detail: str,
    bundle_path: str,
) -> EvidenceContractEntry:
    return EvidenceContractEntry(
        code=code,
        message=(f"{detail}; this does not assess whether the work itself is correct"),
        evidence_path=bundle_path,
    )


def _has_well_formed_dsse_signature(signatures: Any) -> bool:
    if not isinstance(signatures, list):
        return False
    for signature in signatures:
        if not isinstance(signature, dict):
            continue
        signature_text = signature.get("sig")
        if not isinstance(signature_text, str) or not signature_text:
            continue
        try:
            signature_bytes = base64.b64decode(
                signature_text.encode("ascii"),
                validate=True,
            )
        except (UnicodeEncodeError, ValueError):
            continue
        if signature_bytes:
            return True
    return False


def _verified_role_capability_bundle(
    evidence: EvidenceContext,
    bundle: dict[str, Any],
    bundle_path: str,
    *,
    verified_signature_anchors: set[str] | None = None,
) -> tuple[dict[str, Any] | None, EvidenceContractEntry | None]:
    public_key_path = evidence.raw.get("trusted_observer_public_key_file")
    if not isinstance(public_key_path, str) or not public_key_path:
        return None, _role_capability_signature_entry(
            _ERR_ROLE_CAPABILITY_TRUST_ANCHOR_MISSING,
            (
                "bundle DSSE signature is not re-derivable from a trusted anchor "
                "because no trusted observer public key is configured"
            ),
            bundle_path,
        )

    envelope = bundle.get("dsse_envelope")
    if not isinstance(envelope, dict):
        return None, _role_capability_signature_entry(
            _ERR_ROLE_CAPABILITY_SIGNATURE_MISSING,
            (
                "bundle DSSE signature is not re-derivable from a trusted anchor "
                "because the envelope is missing or malformed"
            ),
            bundle_path,
        )
    signatures = envelope.get("signatures")
    if not _has_well_formed_dsse_signature(signatures):
        return None, _role_capability_signature_entry(
            _ERR_ROLE_CAPABILITY_SIGNATURE_MISSING,
            (
                "bundle DSSE signature is not re-derivable from a trusted anchor "
                "because the envelope signature is missing or malformed"
            ),
            bundle_path,
        )
    try:
        signed_statement = decode_dsse_payload(envelope)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, _role_capability_signature_entry(
            _ERR_ROLE_CAPABILITY_SIGNATURE_MISSING,
            (
                "bundle DSSE signature is not re-derivable from a trusted anchor "
                "because the envelope is missing or malformed"
            ),
            bundle_path,
        )
    if not verify_dsse_envelope(envelope, public_key_path):
        return None, _role_capability_signature_entry(
            _ERR_ROLE_CAPABILITY_SIGNATURE_INVALID,
            (
                "bundle DSSE signature is not verifiable under the configured "
                "trusted observer public key"
            ),
            bundle_path,
        )
    if verified_signature_anchors is not None:
        verified_signature_anchors.add(public_key_path)

    # M1 closes the no-signature-checked hole. A valid signature under this
    # configured key does not establish that the anchor is independent of the
    # executor; that requires an operator-provided key and real observer/runner
    # separation (M7).
    verified_bundle = dict(bundle)
    verified_bundle["statement"] = signed_statement
    return verified_bundle, None


def _validate_bound_observation(
    evidence: EvidenceContext,
    bundle: dict[str, Any] | None,
    bundle_path: str,
    *,
    filenames: tuple[str, ...],
    display_filename: str,
) -> list[EvidenceContractEntry]:
    observation_subject = _find_observation_subject(bundle, filenames) if bundle else None
    if observation_subject is None:
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_OBSERVATION_UNBOUND,
                message=(
                    f"{display_filename} observation is not bound to the signed "
                    "bundle as a named digest subject"
                ),
                evidence_path=bundle_path,
            )
        ]
    observation_filename, expected_observation_digest = observation_subject
    observation_entry = _evidence_file_entry(
        evidence,
        observation_filename,
    )
    if observation_entry is None or not _raw_artifact_digest_matches(
        expected_observation_digest,
        observation_entry.content,
    ):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_OBSERVATION_DIGEST_MISMATCH,
                message=(
                    f"{observation_filename} observation digest does not match "
                    "the signed bundle subject; the observation is not "
                    "re-derivable as tamper-evident"
                ),
                evidence_path=observation_filename,
            )
        ]
    return []


def _validate_role_capability_write_scope(
    evidence: EvidenceContext,
    contract: dict[str, Any],
    touched_files: list[str],
    *,
    verified_signature_anchors: set[str] | None = None,
) -> list[EvidenceContractEntry]:
    directive = contract.get("role_capability_write_scope")
    if not isinstance(directive, dict):
        return []

    run_intent_path = directive.get("run_intent_path")
    if not isinstance(run_intent_path, str) or not run_intent_path:
        run_intent_path = "run-intent.json"
    bundle_path = directive.get("bundle_path")
    if not isinstance(bundle_path, str) or not bundle_path:
        bundle_path = "bundle.json"
    intent, bundle, errors = _load_bound_run_intent(
        evidence,
        run_intent_path,
        bundle_path,
        verified_signature_anchors=verified_signature_anchors,
    )
    if errors:
        return errors
    if intent is None:
        return []

    if contract.get("schema_version") in {
        _ROLE_CAPABILITY_BOUND_OBSERVATION_CONTRACT_SCHEMA_VERSION,
        _ROLE_CAPABILITY_SKILL_ROUTING_CONTRACT_SCHEMA_VERSION,
    }:
        errors = _validate_bound_observation(
            evidence,
            bundle,
            bundle_path,
            filenames=_OBSERVATION_FILENAMES,
            display_filename=_OBSERVED_TOUCHED_FILES_FILENAME,
        )
        if errors:
            return errors

    role_capability = intent.get("role_capability")
    if not isinstance(role_capability, dict):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                message="run-intent role_capability is required",
                evidence_path=run_intent_path,
            )
        ]
    declared_write_scope = _as_str_list(role_capability.get("declared_write_scope"))
    if not declared_write_scope:
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                message="run-intent role_capability.declared_write_scope is required",
                evidence_path=run_intent_path,
            )
        ]

    for touched in touched_files:
        if not _path_allowed_by_scope(touched, declared_write_scope):
            return [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_WRITE_SCOPE_VIOLATION,
                    message=(
                        "touched file is outside declared role capability "
                        f"write_scope: {touched}"
                    ),
                    evidence_path=touched,
                )
            ]
    return []


def _validate_role_capability_skill_routing(
    evidence: EvidenceContext,
    contract: dict[str, Any],
    observed_skills: list[str],
    *,
    verified_signature_anchors: set[str] | None = None,
) -> list[EvidenceContractEntry]:
    directive = contract.get("role_capability_skill_routing")
    if not isinstance(directive, dict):
        return []

    run_intent_path = directive.get("run_intent_path")
    if not isinstance(run_intent_path, str) or not run_intent_path:
        run_intent_path = "run-intent.json"
    bundle_path = directive.get("bundle_path")
    if not isinstance(bundle_path, str) or not bundle_path:
        bundle_path = "bundle.json"
    intent, bundle, errors = _load_bound_run_intent(
        evidence,
        run_intent_path,
        bundle_path,
        verified_signature_anchors=verified_signature_anchors,
    )
    if errors:
        return errors
    if intent is None:
        return []

    errors = _validate_bound_observation(
        evidence,
        bundle,
        bundle_path,
        filenames=(_OBSERVED_SKILLS_FILENAME,),
        display_filename=_OBSERVED_SKILLS_FILENAME,
    )
    if errors:
        return errors

    role_capability = intent.get("role_capability")
    if not isinstance(role_capability, dict):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                message="run-intent role_capability is required",
                evidence_path=run_intent_path,
            )
        ]

    forbidden_skills = _as_str_list(directive.get("forbidden_skills"))
    for observed_skill in observed_skills:
        if _matches_any_pattern(observed_skill, forbidden_skills):
            return [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_SKILL_ROUTING_VIOLATION,
                    message=(
                        "observed skill is forbidden by declared role capability "
                        f"skill_routing: {observed_skill}"
                    ),
                    evidence_path=_OBSERVED_SKILLS_FILENAME,
                )
            ]
    return []


def _validate_code_health(
    evidence: EvidenceContext,
    contract: dict[str, Any],
) -> list[EvidenceContractEntry]:
    if "code_health" not in contract:
        return []
    directive = contract.get("code_health")
    if not isinstance(directive, dict):
        return [
            EvidenceContractEntry(
                code=_ERR_CONTRACT_INVALID,
                message="code_health must be an object",
                evidence_path=_EVIDENCE_CONTRACT_FILENAME,
            )
        ]

    gates = directive.get("gates")
    if not isinstance(gates, list) or not gates:
        return [
            EvidenceContractEntry(
                code=_ERR_CONTRACT_INVALID,
                message="code_health.gates must be a non-empty list",
                evidence_path=_EVIDENCE_CONTRACT_FILENAME,
            )
        ]

    _substrates, binding_errors = _health_evidence_substrates(evidence, contract)
    results: list[EvidenceContractEntry] = list(binding_errors)
    for index, gate in enumerate(gates):
        prefix = f"code_health.gates[{index}]"
        if not isinstance(gate, dict):
            return [
                EvidenceContractEntry(
                    code=_ERR_CONTRACT_INVALID,
                    message=f"{prefix} must be an object",
                    evidence_path=_EVIDENCE_CONTRACT_FILENAME,
                )
            ]
        for key in ("gate", "tool", "exit_code_path", "log_path"):
            if not isinstance(gate.get(key), str) or not gate[key]:
                return [
                    EvidenceContractEntry(
                        code=_ERR_CONTRACT_INVALID,
                        message=f"{prefix}.{key} must be a non-empty string",
                        evidence_path=_EVIDENCE_CONTRACT_FILENAME,
                    )
                ]
        enforcement = gate.get("enforcement")
        if enforcement not in {"block", "advisory"}:
            return [
                EvidenceContractEntry(
                    code=_ERR_CONTRACT_INVALID,
                    message=(
                        f"{prefix}.enforcement must be 'block' or 'advisory'"
                    ),
                    evidence_path=_EVIDENCE_CONTRACT_FILENAME,
                )
            ]
        expected_exit_code = gate.get("expected_exit_code")
        if type(expected_exit_code) is not int:
            return [
                EvidenceContractEntry(
                    code=_ERR_CONTRACT_INVALID,
                    message=f"{prefix}.expected_exit_code must be an integer",
                    evidence_path=_EVIDENCE_CONTRACT_FILENAME,
                )
            ]

        exit_code_path = gate["exit_code_path"]
        actual_exit_code = _read_exit_code(evidence, exit_code_path)
        if actual_exit_code != expected_exit_code:
            results.append(
                EvidenceContractEntry(
                    code=_ERR_HEALTH_GATE_VIOLATION,
                    message=(
                        "code health gate exit code mismatch: "
                        f"gate={gate['gate']!r}, tool={gate['tool']!r}, "
                        f"enforcement={enforcement!r}, "
                        f"expected={expected_exit_code}, got={actual_exit_code}"
                    ),
                    evidence_path=exit_code_path,
                    health_gate={
                        "gate": gate["gate"],
                        "tool": gate["tool"],
                        "enforcement": enforcement,
                    },
                )
            )
    return results


def _load_bound_run_intent(
    evidence: EvidenceContext,
    run_intent_path: str,
    bundle_path: str,
    *,
    verified_signature_anchors: set[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[EvidenceContractEntry]]:
    run_intent_entry = _evidence_file_entry(evidence, run_intent_path)
    if run_intent_entry is None:
        return (
            None,
            None,
            [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_RUN_INTENT_MISSING,
                    message=f"role capability verification requires {run_intent_path}",
                    evidence_path=run_intent_path,
                )
            ],
        )

    run_intent_artifact, invalid = _json_object(
        run_intent_entry.content,
        run_intent_path,
    )
    if invalid is not None:
        return None, None, [invalid]

    bundle_entry = _evidence_file_entry(evidence, bundle_path)
    if bundle_entry is None:
        return (
            None,
            None,
            [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                    message=f"role capability verification requires {bundle_path}",
                    evidence_path=bundle_path,
                )
            ],
        )
    bundle, invalid = _json_object(bundle_entry.content, bundle_path)
    if invalid is not None:
        return None, None, [invalid]
    bundle, signature_error = _verified_role_capability_bundle(
        evidence,
        bundle,
        bundle_path,
        verified_signature_anchors=verified_signature_anchors,
    )
    if signature_error is not None:
        return None, None, [signature_error]
    if bundle is None:
        return None, None, []

    intent = run_intent_artifact.get("intent")
    if not isinstance(intent, dict):
        return (
            None,
            None,
            [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                    message="run-intent.json must contain intent object",
                    evidence_path=run_intent_path,
                )
            ],
        )
    payload = _run_intent_payload(run_intent_artifact)
    if payload != intent:
        return (
            None,
            None,
            [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                    message="run-intent DSSE payload must match intent object",
                    evidence_path=run_intent_path,
                )
            ],
        )

    expected_digest = _subject_digest(bundle, "run-intent")
    if expected_digest is None:
        return (
            None,
            None,
            [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                    message="bundle.json must bind run-intent as a subject",
                    evidence_path=bundle_path,
                )
            ],
        )
    if not _run_intent_digest_matches(
        expected_digest,
        run_intent_entry.content,
        intent,
    ):
        return (
            None,
            None,
            [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                    message="bundle run-intent subject digest does not match run-intent",
                    evidence_path=bundle_path,
                )
            ],
        )
    return intent, bundle, []


def _validate_role_capability_tool_calls(
    evidence: EvidenceContext,
    contract: dict[str, Any],
    *,
    verified_signature_anchors: set[str] | None = None,
) -> list[EvidenceContractEntry]:
    directive = contract.get("role_capability_tool_calls")
    if not isinstance(directive, dict):
        return []

    run_intent_path = directive.get("run_intent_path")
    if not isinstance(run_intent_path, str) or not run_intent_path:
        run_intent_path = "run-intent.json"
    bundle_path = directive.get("bundle_path")
    if not isinstance(bundle_path, str) or not bundle_path:
        bundle_path = "bundle.json"
    receipts_path = directive.get("decision_receipts_path")
    if not isinstance(receipts_path, str) or not receipts_path:
        receipts_path = "tool-call-decision-receipts.json"

    intent, bundle, errors = _load_bound_run_intent(
        evidence,
        run_intent_path,
        bundle_path,
        verified_signature_anchors=verified_signature_anchors,
    )
    if errors:
        return errors
    if intent is None or bundle is None:
        return []

    role_capability = intent.get("role_capability")
    if not isinstance(role_capability, dict):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_RUN_INTENT_INVALID,
                message="run-intent role_capability is required",
                evidence_path=run_intent_path,
            )
        ]
    declared_tools = role_capability.get("declared_tools")
    if not isinstance(declared_tools, dict):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_TOOL_GRANT_MISSING,
                message="run-intent role_capability.declared_tools is required",
                evidence_path=run_intent_path,
            )
        ]
    allowed_tools = set(_as_str_list(declared_tools.get("allow")))

    receipts_entry = _evidence_file_entry(evidence, receipts_path)
    if receipts_entry is None:
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_MISSING,
                message=f"role capability tool_calls requires {receipts_path}",
                evidence_path=receipts_path,
            )
        ]
    receipts, invalid = _json_object(
        receipts_entry.content,
        receipts_path,
        _ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
    )
    if invalid is not None:
        return [invalid]

    expected_receipts_digest = _subject_digest(
        bundle,
        "tool-call-decision-receipts",
    )
    if expected_receipts_digest is None:
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_TOOL_BUNDLE_DIGEST_MISMATCH,
                message="bundle.json must bind tool-call-decision-receipts as a subject",
                evidence_path=bundle_path,
            )
        ]
    if not _raw_artifact_digest_matches(
        expected_receipts_digest,
        receipts_entry.content,
    ):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_TOOL_BUNDLE_DIGEST_MISMATCH,
                message=(
                    "bundle tool-call-decision-receipts subject digest does not "
                    "match receipts artifact"
                ),
                evidence_path=bundle_path,
            )
        ]

    decisions = receipts.get("decisions")
    observed_calls = receipts.get("observed_mcp_tool_calls")
    if not isinstance(decisions, list) or not isinstance(observed_calls, list):
        return [
            EvidenceContractEntry(
                code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                message=(
                    "tool-call decision receipts must contain decisions and "
                    "observed_mcp_tool_calls lists"
                ),
                evidence_path=receipts_path,
            )
        ]

    results: list[EvidenceContractEntry] = []
    decision_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    decision_names: dict[str, list[dict[str, Any]]] = {}
    previous_hash: str | None = None
    for index, item in enumerate(decisions, start=1):
        if not isinstance(item, dict):
            return [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                    message="tool-call decision entries must be JSON objects",
                    evidence_path=receipts_path,
                )
            ]
        if (
            item.get("sequence") != index
            or item.get("previous_decision_sha256") != previous_hash
        ):
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_SEQUENCE_GAP,
                    message="tool-call decision sequence must be contiguous and linked",
                    evidence_path=receipts_path,
                ),
            )
            break
        previous_hash = _canonical_decision_hash(item)

        key = _decision_receipt_key(item)
        if key is None:
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                    message=(
                        "tool-call decision requires canonical_tool_name and "
                        "canonical_request_sha256"
                    ),
                    evidence_path=receipts_path,
                ),
            )
            continue
        canonical_tool_name, _ = key
        if not canonical_tool_name.startswith("mcp__"):
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                    message=(
                        "role_capability_tool_calls only accepts MCP tool "
                        f"decisions: {canonical_tool_name}"
                    ),
                    evidence_path=receipts_path,
                ),
            )
            continue

        decision_by_key[key] = item
        decision_names.setdefault(canonical_tool_name, []).append(item)
        decision = item.get("decision")
        is_granted = canonical_tool_name in allowed_tools
        if decision == "allow" and not is_granted:
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_ALLOW_OUTSIDE_GRANT,
                    message=f"tool-call allow is outside declared grant: {canonical_tool_name}",
                    evidence_path=receipts_path,
                ),
            )
        elif decision == "deny" and is_granted:
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_DECISION_MISMATCH,
                    message=f"granted MCP tool-call must be allowed: {canonical_tool_name}",
                    evidence_path=receipts_path,
                ),
            )
        elif decision not in {"allow", "deny"}:
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                    message=f"unknown tool-call decision: {decision!r}",
                    evidence_path=receipts_path,
                ),
            )

    for item in observed_calls:
        if not isinstance(item, dict):
            return [
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                    message="observed MCP tool-call entries must be JSON objects",
                    evidence_path=receipts_path,
                )
            ]
        key = _decision_receipt_key(item)
        if key is None:
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_RECEIPTS_INVALID,
                    message=(
                        "observed MCP tool-call requires canonical_tool_name and "
                        "canonical_request_sha256"
                    ),
                    evidence_path=receipts_path,
                ),
            )
            continue
        canonical_tool_name, _ = key
        matching_decision = decision_by_key.get(key)
        if matching_decision is None:
            code = (
                _ERR_ROLE_CAPABILITY_TOOL_REQUEST_HASH_MISMATCH
                if canonical_tool_name in decision_names
                else _ERR_ROLE_CAPABILITY_TOOL_RECEIPT_MISSING
            )
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=code,
                    message=(
                        "observed MCP tool-call does not match a sealed "
                        f"decision receipt: {canonical_tool_name}"
                    ),
                    evidence_path=receipts_path,
                ),
            )
            continue
        if (
            matching_decision.get("decision") == "deny"
            and item.get("result_status") == "success"
        ):
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_ROLE_CAPABILITY_TOOL_DENY_EXECUTED,
                    message=f"denied MCP tool-call has a successful observed result: {canonical_tool_name}",
                    evidence_path=receipts_path,
                ),
            )

    return results


def _advisory_entry(
    code: str,
    detail: str,
    evidence_path: str,
) -> EvidenceContractEntry:
    return EvidenceContractEntry(
        code=code,
        message=(
            f"{detail}; the claim is not re-derivable from sealed bytes. "
            "This verdict does not assess whether the advisory decision is correct."
        ),
        evidence_path=evidence_path,
    )


def _advisory_json_object(
    evidence: EvidenceContext,
    path: str,
    error_code: str,
) -> tuple[dict[str, Any] | None, EvidenceContractEntry | None]:
    entry = _evidence_file_entry(evidence, path)
    if entry is None:
        return None, _advisory_entry(
            error_code,
            f"required advisory artifact is missing: {path}",
            path,
        )
    parsed, invalid = _json_object(entry.content, path, error_code)
    if invalid is not None:
        return None, _advisory_entry(
            error_code,
            f"advisory artifact is not a JSON object: {path}",
            path,
        )
    return parsed, None


def _sealed_advisory_statement(
    evidence: EvidenceContext,
    bundle_path: str,
    tamper_code: str,
    schema_version: str,
) -> tuple[dict[str, Any] | None, EvidenceContractEntry | None]:
    envelope, invalid = _advisory_json_object(evidence, bundle_path, tamper_code)
    if invalid is not None:
        return None, invalid
    public_key_path = evidence.raw.get("trusted_observer_public_key_file")
    if not isinstance(public_key_path, str) or not verify_dsse_envelope(
        envelope,
        public_key_path,
    ):
        return None, _advisory_entry(
            tamper_code,
            "advisory DSSE signature is missing or invalid",
            bundle_path,
        )
    try:
        statement = decode_dsse_payload(envelope)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, _advisory_entry(
            tamper_code,
            "advisory DSSE payload is not a valid in-toto statement",
            bundle_path,
        )
    predicate = statement.get("predicate")
    schema_number = schema_version.split(".", 1)[0]
    if (
        statement.get("predicateType")
        != f"https://depone.dev/attestations/advisory-provenance/{schema_number}"
        or not isinstance(predicate, dict)
        or predicate.get("schema_version") != schema_version
    ):
        return None, _advisory_entry(
            tamper_code,
            f"advisory DSSE statement does not declare the {schema_number} predicate",
            bundle_path,
        )
    return statement, None


def _advisory_subject_matches(
    statement: dict[str, Any],
    path: str,
    artifact: dict[str, Any],
) -> bool:
    expected_digest = _subject_digest({"statement": statement}, path)
    return expected_digest is not None and expected_digest == canonical_hash(artifact)


def _validate_advisory_sketch(
    decision: dict[str, Any],
    decision_path: str,
) -> list[EvidenceContractEntry]:
    candidates = decision.get("candidates")
    chosen = decision.get("chosen")
    candidate_axes = (
        {
            item.get("axis")
            for item in candidates
            if isinstance(item, dict) and isinstance(item.get("axis"), str)
        }
        if isinstance(candidates, list)
        else set()
    )
    direction = chosen.get("direction") if isinstance(chosen, dict) else None
    if not isinstance(direction, str) or direction not in candidate_axes:
        return [
            _advisory_entry(
                _ERR_ADVISORY_SKETCH_CHOSEN_NOT_IN_CANDIDATES,
                "sealed sketch chosen.direction is absent from candidates[].axis",
                decision_path,
            )
        ]

    rejected = decision.get("rejected")
    if not isinstance(rejected, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("why_lost"), str)
        or not item["why_lost"].strip()
        for item in rejected
    ):
        return [
            _advisory_entry(
                _ERR_ADVISORY_SKETCH_REJECTED_REASON_MISSING,
                "sealed sketch has a rejected option without non-empty why_lost",
                decision_path,
            )
        ]
    if any(item.get("option") == direction for item in rejected):
        return [
            _advisory_entry(
                _ERR_ADVISORY_SKETCH_CHOSEN_ALSO_REJECTED,
                (
                    "sealed sketch is internally inconsistent because "
                    "chosen.direction also appears in rejected[].option"
                ),
                decision_path,
            )
        ]
    return []


def _trace_receipt_reference(
    trace: dict[str, Any],
) -> str | None:
    reproduction = trace.get("reproduction")
    if not isinstance(reproduction, dict):
        return None
    receipt_sha256 = reproduction.get("receipt_sha256")
    return (
        receipt_sha256 if isinstance(receipt_sha256, str) and receipt_sha256 else None
    )


def _trace_execution_receipt(
    evidence: EvidenceContext,
    statement: dict[str, Any],
    reproduction: dict[str, Any],
    decision_path: str,
) -> tuple[dict[str, Any] | None, EvidenceContractEntry | None]:
    """Validate a recorded execution without claiming the diagnosed cause is true."""

    execution_path = "orro-trace-execution.json"
    execution_entry = _evidence_file_entry(evidence, execution_path)
    if execution_entry is None:
        return None, _advisory_entry(
            _ERR_ADVISORY_TRACE_RED_NOT_EXECUTED,
            "confirmed tier lacks a bound executed-red receipt",
            decision_path,
        )
    execution, invalid = _advisory_json_object(
        evidence,
        execution_path,
        _ERR_ADVISORY_TRACE_RED_NOT_EXECUTED,
    )
    if invalid is not None:
        return None, invalid
    execution_reference = reproduction.get("execution_receipt_sha256")
    if (
        execution is None
        or not _advisory_subject_matches(statement, execution_path, execution)
        or not isinstance(execution_reference, str)
        or execution_reference != canonical_hash(execution)
    ):
        return None, _advisory_entry(
            _ERR_ADVISORY_TRACE_RED_NOT_EXECUTED,
            "confirmed tier references an execution receipt whose digest does not match",
            execution_path,
        )

    command = execution.get("command")
    transcript = execution.get("transcript")
    transcript_sha256 = execution.get("transcript_sha256")
    transcript_matches = (
        isinstance(transcript, str)
        and bool(transcript)
        and isinstance(transcript_sha256, str)
        and transcript_sha256 == hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    )
    recorded_failure = (
        isinstance(execution.get("exit_code"), int) and execution.get("exit_code") != 0
    ) or execution.get("status") == "failed"
    if (
        validate_runner_receipt(execution)
        or not isinstance(command, str)
        or not command.strip()
        or not transcript_matches
        or not recorded_failure
    ):
        return None, _advisory_entry(
            _ERR_ADVISORY_TRACE_RED_NOT_EXECUTED,
            (
                "confirmed tier execution receipt must bind a command, failing "
                "exit or status, and matching transcript digest"
            ),
            execution_path,
        )
    return execution, None


def _validate_advisory_trace(
    evidence: EvidenceContext,
    trace: dict[str, Any],
    decision_path: str,
    statement: dict[str, Any],
    require_executed_red: bool,
) -> list[EvidenceContractEntry]:
    receipt_path = "orro-trace-reproduction.json"
    receipt_entry = _evidence_file_entry(evidence, receipt_path)
    receipt: dict[str, Any] | None = None
    if receipt_entry is not None:
        receipt, invalid = _advisory_json_object(
            evidence,
            receipt_path,
            _ERR_ADVISORY_TRACE_TAMPER,
        )
        if invalid is not None:
            return [invalid]
        if receipt is None or not _advisory_subject_matches(
            statement,
            receipt_path,
            receipt,
        ):
            return [
                _advisory_entry(
                    _ERR_ADVISORY_TRACE_TAMPER,
                    "sealed trace reproduction subject digest does not match its bytes",
                    receipt_path,
                )
            ]

    root_cause = trace.get("root_cause")
    tier = root_cause.get("tier") if isinstance(root_cause, dict) else None
    receipt_reference = _trace_receipt_reference(trace)
    receipt_reference_matches = (
        receipt is not None
        and receipt_reference is not None
        and receipt_reference == canonical_hash(receipt)
    )

    if tier in {"suspected", "speculative"} or isinstance(
        trace.get("unconfirmed"),
        dict,
    ):
        if receipt_reference is not None and not receipt_reference_matches:
            return [
                _advisory_entry(
                    _ERR_ADVISORY_TRACE_RECEIPT_HASH_MISMATCH,
                    "sealed trace references a reproduction receipt whose hash does not match",
                    receipt_path,
                )
            ]
        return []

    if tier != "confirmed":
        return [
            _advisory_entry(
                _ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID,
                "trace must contain unconfirmed or a recognized root_cause tier",
                decision_path,
            )
        ]

    reproduction = trace.get("reproduction")
    if (
        not isinstance(reproduction, dict)
        or reproduction.get("red_observed") is not True
        or not receipt_reference_matches
    ):
        return [
            _advisory_entry(
                _ERR_ADVISORY_TRACE_CONFIRMED_UNBACKED,
                "confirmed tier lacks red_observed and a matching sealed reproduction receipt",
                decision_path,
            )
        ]

    hypotheses = trace.get("hypotheses")
    hypothesis_index = root_cause.get("hypothesis_index")
    hypothesis = (
        hypotheses[hypothesis_index]
        if isinstance(hypotheses, list)
        and isinstance(hypothesis_index, int)
        and 0 <= hypothesis_index < len(hypotheses)
        and isinstance(hypotheses[hypothesis_index], dict)
        else None
    )
    symptom = reproduction.get("symptom")
    probe = hypothesis.get("discriminating_probe") if hypothesis is not None else None
    if require_executed_red:
        execution, invalid = _trace_execution_receipt(
            evidence,
            statement,
            reproduction,
            decision_path,
        )
        if invalid is not None:
            return [invalid]
        output = execution.get("transcript") if execution is not None else None
    else:
        output = receipt.get("output") if receipt is not None else None
    if (
        not isinstance(symptom, str)
        or not symptom
        or not isinstance(probe, str)
        or not probe
        or not isinstance(output, str)
        or symptom not in output
        or probe not in output
    ):
        return [
            _advisory_entry(
                _ERR_ADVISORY_TRACE_UNRELATED_RED,
                "recorded red output is not bound to the symptom and confirmed probe",
                receipt_path,
            )
        ]

    confirmation = trace.get("confirmation")
    ruled_out = (
        confirmation.get("rival_hypotheses_ruled_out")
        if isinstance(confirmation, dict)
        else None
    )
    has_ruled_out_rival = isinstance(ruled_out, list) and any(
        isinstance(index, int)
        and isinstance(hypotheses, list)
        and 0 <= index < len(hypotheses)
        and index != hypothesis_index
        for index in ruled_out
    )
    if not has_ruled_out_rival:
        return [
            _advisory_entry(
                _ERR_ADVISORY_TRACE_RIVAL_NOT_RULED_OUT,
                "confirmed tier does not seal an actively ruled-out rival hypothesis",
                decision_path,
            )
        ]
    return []


def validate_advisory_provenance(
    evidence: EvidenceContext,
    contract: dict[str, Any],
) -> list[EvidenceContractEntry]:
    """Re-derive advisory record consistency without changing execution verdicts."""

    directive = contract.get("advisory_provenance")
    schema_version = contract.get("schema_version")
    if schema_version not in {
        _ADVISORY_PROVENANCE_CONTRACT_SCHEMA_VERSION,
        _ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION,
    } or not isinstance(directive, dict):
        return [
            _advisory_entry(
                _ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID,
                "advisory provenance requires the v108 or v110 directive",
                _EVIDENCE_CONTRACT_FILENAME,
            )
        ]
    decision_path = directive.get("decision_path")
    bundle_path = directive.get("bundle_path")
    if (
        not isinstance(decision_path, str)
        or not decision_path
        or not isinstance(bundle_path, str)
        or not bundle_path
    ):
        return [
            _advisory_entry(
                _ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID,
                "advisory provenance requires decision_path and bundle_path",
                _EVIDENCE_CONTRACT_FILENAME,
            )
        ]

    decision, invalid = _advisory_json_object(
        evidence,
        decision_path,
        _ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID,
    )
    if invalid is not None:
        return [invalid]
    if decision is None:
        return []
    kind = decision.get("kind")
    if kind not in {"orro-sketch", "orro-trace"}:
        return [
            _advisory_entry(
                _ERR_ADVISORY_PROVENANCE_CONTRACT_INVALID,
                "advisory decision kind must be orro-sketch or orro-trace",
                decision_path,
            )
        ]

    tamper_code = (
        _ERR_ADVISORY_SKETCH_TAMPER
        if kind == "orro-sketch"
        else _ERR_ADVISORY_TRACE_TAMPER
    )
    statement, invalid = _sealed_advisory_statement(
        evidence,
        bundle_path,
        tamper_code,
        schema_version,
    )
    if invalid is not None:
        return [invalid]
    if statement is None or not _advisory_subject_matches(
        statement,
        decision_path,
        decision,
    ):
        return [
            _advisory_entry(
                tamper_code,
                "sealed advisory decision subject digest does not match its bytes",
                decision_path,
            )
        ]

    if kind == "orro-sketch":
        return _validate_advisory_sketch(decision, decision_path)
    return _validate_advisory_trace(
        evidence,
        decision,
        decision_path,
        statement,
        schema_version == _ADVISORY_PROVENANCE_EXECUTED_RED_CONTRACT_SCHEMA_VERSION,
    )


def _diff_file_path(header: str) -> str | None:
    parts = header.split()
    if len(parts) < 4:
        return None
    target = parts[3]
    if target.startswith("b/"):
        return target[2:]
    return target


def _line_weakens_test(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("assert ")
        or stripped.startswith("self.assert")
        or "pytest.raises(" in stripped
        or "pytest.fail(" in stripped
        or stripped.startswith("raise AssertionError")
        or stripped == "pass"
    )


def _forbidden_test_file_weakened(
    patch_text: str, forbidden_test_files: set[str]
) -> str | None:
    current_file: str | None = None
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            current_file = _diff_file_path(line)
            continue
        if current_file not in forbidden_test_files:
            continue
        if line.startswith("-") and _line_weakens_test(line[1:]):
            return current_file
        if line.startswith("+") and line[1:].strip().startswith("assert True"):
            return current_file
    return None


def _append_unique_entry(
    results: list[EvidenceContractEntry], entry: EvidenceContractEntry
) -> None:
    if any(
        existing.code == entry.code and existing.evidence_path == entry.evidence_path
        for existing in results
    ):
        return
    results.append(entry)


def validate_evidence_contract(
    evidence: EvidenceContext,
    *,
    verified_signature_anchors: set[str] | None = None,
) -> list[EvidenceContractEntry]:
    shadowed = _find_control_shadow(evidence)
    if shadowed is not None:
        return [shadowed]

    contract, invalid = _read_evidence_contract(evidence)
    if invalid is not None:
        return [invalid]
    invalid = _validate_contract_semantics(contract)
    if invalid is not None:
        return [invalid]

    results: list[EvidenceContractEntry] = []
    evidence_map = _evidence_map(evidence)

    required_paths = _as_str_list(contract.get("required_evidence"))
    if not required_paths:
        required_paths = _as_str_list(contract.get("required_paths"))
    if not required_paths:
        required_paths = _as_str_list(contract.get("required_evidence_paths"))
    for required_path in required_paths:
        if required_path not in evidence_map:
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_REQUIRED_TEST_EVIDENCE_MISSING,
                    message=f"required evidence missing: {required_path}",
                    evidence_path=required_path,
                ),
            )

    required_commands = contract.get("required_commands")
    if isinstance(required_commands, list):
        for command in required_commands:
            if not isinstance(command, dict):
                continue
            log_path = command.get("log_path")
            if isinstance(log_path, str) and log_path not in evidence_map:
                _append_unique_entry(
                    results,
                    EvidenceContractEntry(
                        code=_ERR_REQUIRED_TEST_EVIDENCE_MISSING,
                        message=f"required command log missing: {log_path}",
                        evidence_path=log_path,
                    ),
                )
            expected_exit_code = command.get("expected_exit_code")
            exit_code_path = command.get("exit_code_path")
            if not isinstance(exit_code_path, str):
                exit_code_path = "exit-code.txt"
            actual_exit_code = _read_exit_code(evidence, exit_code_path)
            if (
                isinstance(expected_exit_code, int)
                and actual_exit_code != expected_exit_code
            ):
                _append_unique_entry(
                    results,
                    EvidenceContractEntry(
                        code=_ERR_TEST_EXIT_CODE_MISMATCH,
                        message=f"expected exit code {expected_exit_code}, got {actual_exit_code}",
                        evidence_path=exit_code_path
                        if exit_code_path in evidence_map
                        else "run-metadata.json",
                    ),
                )
    else:
        expected_exit_code = contract.get("expected_exit_code")
        actual_exit_code = _read_exit_code(evidence, "exit-code.txt")
        if (
            isinstance(expected_exit_code, int)
            and actual_exit_code != expected_exit_code
        ):
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_TEST_EXIT_CODE_MISMATCH,
                    message=f"expected exit code {expected_exit_code}, got {actual_exit_code}",
                    evidence_path="exit-code.txt"
                    if "exit-code.txt" in evidence_map
                    else "run-metadata.json",
                ),
            )

    touched_files = _touched_files(evidence)
    observed_skills = _observed_skills(evidence)
    allowed_files = set(_as_str_list(contract.get("allowed_touched_files")))
    if not allowed_files:
        allowed_files = set(_as_str_list(contract.get("allowed_files")))
    forbidden_files = set(_as_str_list(contract.get("forbidden_touched_files")))
    if not forbidden_files:
        forbidden_files = set(_as_str_list(contract.get("forbidden_files")))
    for touched in touched_files:
        if touched in forbidden_files or (
            allowed_files and touched not in allowed_files
        ):
            _append_unique_entry(
                results,
                EvidenceContractEntry(
                    code=_ERR_FORBIDDEN_FILE_TOUCHED,
                    message=f"touched file is not allowed: {touched}",
                    evidence_path=touched,
                ),
            )
            break

    for entry in _validate_role_capability_write_scope(
        evidence,
        contract,
        touched_files,
        verified_signature_anchors=verified_signature_anchors,
    ):
        _append_unique_entry(results, entry)
    for entry in _validate_role_capability_tool_calls(
        evidence,
        contract,
        verified_signature_anchors=verified_signature_anchors,
    ):
        _append_unique_entry(results, entry)
    for entry in _validate_role_capability_skill_routing(
        evidence,
        contract,
        observed_skills,
        verified_signature_anchors=verified_signature_anchors,
    ):
        _append_unique_entry(results, entry)
    for entry in _validate_code_health(evidence, contract):
        _append_unique_entry(results, entry)

    test_patterns = _as_str_list(contract.get("test_file_patterns"))
    forbidden_test_files = set(_as_str_list(contract.get("forbidden_test_files")))
    if contract.get("forbid_test_weakening") is True and test_patterns:
        forbidden_test_files.update(
            touched
            for touched in touched_files
            if any(touched.startswith(pattern) for pattern in test_patterns)
        )
    if forbidden_test_files:
        patch_entry = _find_evidence_file(evidence, "git-diff.patch")
        if patch_entry is not None:
            patch_path, patch_text = patch_entry
            weakened = _forbidden_test_file_weakened(patch_text, forbidden_test_files)
            if weakened is not None:
                _append_unique_entry(
                    results,
                    EvidenceContractEntry(
                        code=_ERR_TEST_WEAKENED,
                        message=f"forbidden test file was weakened: {weakened}",
                        evidence_path=patch_path,
                    ),
                )

    return results
