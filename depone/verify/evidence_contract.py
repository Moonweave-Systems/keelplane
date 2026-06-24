from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from depone.verify.adapters.base import EvidenceContext


@dataclass
class EvidenceContractEntry:
    code: str
    message: str
    evidence_path: str


_EVIDENCE_CONTRACT_FILENAME = "evidence-contract.json"
_CONTRACT_SCHEMA_VERSION = "v105.verify_wedge"
_ROOT_CONTROL_FILENAMES = frozenset(
    {"evidence-contract.json", "git-diff-name-only.txt", "git-diff.patch"}
)
_ERR_CONTRACT_INVALID = "ERR_EVIDENCE_CONTRACT_INVALID"
_ERR_CONTRACT_MISSING = "ERR_EVIDENCE_CONTRACT_MISSING"
_ERR_CONTRACT_SHADOWED = "ERR_EVIDENCE_CONTRACT_SHADOWED"
_ERR_REQUIRED_TEST_EVIDENCE_MISSING = "ERR_REQUIRED_TEST_EVIDENCE_MISSING"
_ERR_TEST_EXIT_CODE_MISMATCH = "ERR_TEST_EXIT_CODE_MISMATCH"
_ERR_FORBIDDEN_FILE_TOUCHED = "ERR_FORBIDDEN_FILE_TOUCHED"
_ERR_TEST_WEAKENED = "ERR_TEST_WEAKENED"


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
    return contract.get("forbid_test_weakening") is True and _has_non_empty_str_list(
        contract,
        "test_file_patterns",
    )


def _validate_contract_semantics(
    contract: dict[str, Any],
) -> EvidenceContractEntry | None:
    if contract.get("schema_version") != _CONTRACT_SCHEMA_VERSION:
        return EvidenceContractEntry(
            code=_ERR_CONTRACT_INVALID,
            message=f"evidence-contract.json must declare schema_version {_CONTRACT_SCHEMA_VERSION!r}",
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
    entry = _find_evidence_file(evidence, "git-diff-name-only.txt")
    if entry is None:
        return []
    _, content = entry
    return [line.strip() for line in content.splitlines() if line.strip()]


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
