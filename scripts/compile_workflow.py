#!/usr/bin/env python3
"""Compile a V0.5 workflow plan into a deterministic V1 first-slice packet."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evaluate_plan import EvaluationError, validate_plan  # noqa: E402


TOOL = "compile_workflow.py"
SCHEMA_VERSION = "1.0"
COMPILER_VERSION = "1.0.0"
OUT_ROOT = ROOT / "out" / "v1"
PACKET_ID = "001-first-slice"
SENTINEL = ".compile_workflow-owned.json"
PROMPT_HEADINGS = [
    "# Packet 001-first-slice",
    "## Objective",
    "## Inputs",
    "## Ownership",
    "## Allowed Tools",
    "## Forbidden Actions",
    "## Risk Gates",
    "## Required Output",
    "## Verification",
    "## Handoff Context",
    "## Stop Conditions",
]
RISK_CATEGORIES = [
    "write",
    "shell-process",
    "network",
    "dependency-install",
    "database-migration",
    "production-deploy",
    "public-api-change",
    "external-message",
    "paid-api",
    "secret-access",
    "history-rewrite",
    "delete",
]
RISK_ALIASES = {
    "write": ["write", "write-action", "source-edits"],
    "shell-process": ["shell-process", "shell", "shell-action", "process-execution"],
    "network": ["network", "network-action", "external-network-calls"],
    "dependency-install": [
        "dependency-install",
        "dependency-installs",
        "dependency-change",
        "dependency-changes",
    ],
    "database-migration": ["database-migration", "database-migrations"],
    "production-deploy": ["production-deploy", "production-deploys"],
    "public-api-change": ["public-api-change", "public-api-changes"],
    "external-message": ["external-message", "external-message-action", "external-messages"],
    "paid-api": ["paid-api", "paid-external-api-use"],
    "secret-access": ["secret-access", "secret"],
    "history-rewrite": ["history-rewrite", "force-push", "hard-reset"],
    "delete": ["delete", "deletion"],
}
RISK_SAFE_DEFAULTS = {
    "write": "stop before writing and ask for approval",
    "shell-process": "stop before shell use and ask for approval",
    "network": "stop before network use and ask for approval",
    "dependency-install": "stop before dependency installs and ask for approval",
    "database-migration": "stop before database migration and ask for approval",
    "production-deploy": "stop before production deploy and ask for approval",
    "public-api-change": "stop before public API change and ask for approval",
    "external-message": "stop before sending external messages and ask for approval",
    "paid-api": "stop before paid API use and ask for approval",
    "secret-access": "stop before secret access and ask for approval",
    "history-rewrite": "stop before history rewrite and ask for approval",
    "delete": "stop before deletion and ask for approval",
}
RESUME_CODES = {
    "plan": "ERR_RESUME_STALE_PLAN",
    "packet": "ERR_RESUME_STALE_PACKET",
    "prompt": "ERR_RESUME_STALE_PROMPT",
    "input": "ERR_RESUME_STALE_INPUT",
    "handoff": "ERR_RESUME_STALE_HANDOFF",
    "gate": "ERR_RESUME_STALE_GATE",
    "compiler": "ERR_RESUME_STALE_COMPILER",
    "missing": "ERR_RESUME_MISSING_ARTIFACT",
}
DIGEST_FIELDS = [
    "packet_id",
    "source_plan_id",
    "source_first_slice",
    "objective",
    "surface_refs",
    "phase_context",
    "worker_refs",
    "allowed_tools",
    "forbidden_actions",
    "risk_gate_refs",
    "handoff_refs",
    "verification",
    "completion_check",
    "input_snapshot_hash",
    "prompt_contract",
]


class CompileError(ValueError):
    """Structured V1 compiler failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | str | None = None,
        fixture_id: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None
        self.fixture_id = fixture_id

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            record["path"] = self.path
        if self.fixture_id is not None:
            record["fixture_id"] = self.fixture_id
        return record


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_text(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(data: Any) -> str:
    return hashlib.sha256(canonical_json_text(data).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha8(data: Any) -> str:
    return canonical_hash(data)[:8]


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def rel_or_abs(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def run_source_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def safe_resume_source_plan_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise CompileError("ERR_OUT_PATH_UNSAFE", "resume source plan path must be repo-relative", path=path)
    reject_traversal_parts(path, message="resume source plan path escapes repository")
    candidate = ROOT / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise CompileError("ERR_OUT_PATH_UNSAFE", "resume source plan path escapes repository", path=path) from exc
    return candidate


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompileError("ERR_PLAN_INVALID", f"cannot read JSON: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise CompileError("ERR_PLAN_INVALID", "JSON root must be an object", path=path)
    return data


def normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("_", " ").replace("-", " "))


def contains_token_sequence(text: str, needle: str) -> bool:
    haystack = normalize_tokens(text)
    tokens = normalize_tokens(needle)
    if not tokens:
        return False
    return any(haystack[index:index + len(tokens)] == tokens for index in range(len(haystack) - len(tokens) + 1))


def category_from_text(text: str) -> str | None:
    matches = [
        category
        for category in RISK_CATEGORIES
        if any(contains_token_sequence(text, alias) for alias in RISK_ALIASES[category])
    ]
    if not matches:
        return None
    return matches[0]


def check_path_components_not_symlink(path: Path) -> None:
    absolute = path if path.is_absolute() else ROOT / path
    current = Path(absolute.anchor) if absolute.is_absolute() else Path(".")
    for part in absolute.parts[1:] if absolute.is_absolute() else absolute.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise CompileError("ERR_OUT_PATH_SYMLINK", "output path contains a symlink", path=current)
        except OSError as exc:
            raise CompileError("ERR_OUT_PATH_UNSAFE", f"cannot inspect output path: {exc}", path=current) from exc


def reject_traversal_parts(path: Path, *, message: str = "artifact path escapes owned run directory") -> None:
    if any(part == ".." for part in path.parts):
        raise CompileError("ERR_OUT_PATH_UNSAFE", message, path=path)


def ensure_contained_path(root: Path, path: Path) -> None:
    root = root.resolve(strict=False)
    reject_traversal_parts(path)
    target = path if path.is_absolute() else root / path
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(root)
    except ValueError as exc:
        raise CompileError("ERR_OUT_PATH_UNSAFE", "artifact path escapes owned run directory", path=target) from exc


def safe_descendant_path(root: Path, relative_path: str | Path, *, message: str = "path escapes owned directory") -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        raise CompileError("ERR_OUT_PATH_UNSAFE", message, path=relative)
    reject_traversal_parts(relative, message=message)
    target = root / relative
    ensure_contained_path(root, target)
    return target


def ensure_safe_artifact_parent(root: Path, path: Path) -> None:
    root = root.resolve(strict=False)
    target = path if path.is_absolute() else root / path
    ensure_contained_path(root, target)
    current = root
    for part in target.relative_to(root).parent.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise CompileError("ERR_OUT_PATH_SYMLINK", "artifact path contains a symlinked directory", path=current)
            if not current.is_dir():
                raise CompileError("ERR_OUT_PATH_UNSAFE", "artifact parent is not a directory", path=current)
        else:
            current.mkdir()


def ensure_safe_artifact_read(root: Path, path: Path) -> None:
    root = root.resolve(strict=False)
    target = path if path.is_absolute() else root / path
    ensure_contained_path(root, target)
    current = root
    for part in target.relative_to(root).parent.parts:
        current = current / part
        if current.is_symlink():
            raise CompileError("ERR_OUT_PATH_SYMLINK", "artifact path contains a symlinked directory", path=current)
        if not current.is_dir():
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", "artifact parent is missing or not a directory", path=current)


def resolve_v1_out(value: str | Path) -> Path:
    raw = Path(value)
    reject_traversal_parts(raw, message="output path must not contain parent traversal")
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    out_root = OUT_ROOT.resolve(strict=False)
    forbidden = {ROOT.resolve(), (ROOT / "out").resolve(strict=False), out_root}
    if resolved in forbidden:
        raise CompileError("ERR_OUT_PATH_UNSAFE", "output path must name a run directory under out/v1", path=value)
    try:
        resolved.relative_to(out_root)
    except ValueError as exc:
        raise CompileError("ERR_OUT_PATH_UNSAFE", "output path must resolve under repo-local out/v1", path=value) from exc
    if resolved == Path(".").resolve():
        raise CompileError("ERR_OUT_PATH_UNSAFE", "output path cannot be current directory", path=value)
    check_path_components_not_symlink(candidate)
    return resolved


def sentinel_matches(path: Path, run_id: str, mode: str) -> bool:
    sentinel = path / SENTINEL
    if not sentinel.is_file() or sentinel.is_symlink():
        return False
    try:
        data = json.loads(sentinel.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        data.get("tool") == TOOL
        and data.get("schema_version") == SCHEMA_VERSION
        and data.get("run_id") == run_id
        and data.get("mode") == mode
    )


def prepare_owned_dir(path: Path, run_id: str, mode: str, *, clear: bool) -> None:
    path = resolve_v1_out(path)
    if path.exists():
        if path.is_symlink():
            raise CompileError("ERR_OUT_PATH_SYMLINK", "run directory is a symlink", path=path)
        if not path.is_dir():
            raise CompileError("ERR_OUT_PATH_UNSAFE", "output path exists and is not a directory", path=path)
        if not sentinel_matches(path, run_id, mode):
            raise CompileError("ERR_OUT_PATH_NOT_OWNED", "existing run directory is not compiler-owned", path=path)
        if clear:
            shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path / SENTINEL, sentinel_payload(run_id, mode), root=path)


def ensure_safe_leaf(path: Path) -> None:
    if path.exists():
        if path.is_symlink():
            raise CompileError("ERR_OUT_PATH_SYMLINK", "refusing to overwrite symlinked file", path=path)
        if not path.is_file():
            raise CompileError("ERR_OUT_PATH_UNSAFE", "refusing to overwrite non-file leaf", path=path)


def write_text_atomic(path: Path, text: str, *, root: Path | None = None) -> None:
    if root is not None:
        ensure_safe_artifact_parent(root, path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    ensure_safe_leaf(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if root is not None:
            ensure_safe_artifact_parent(root, path)
        ensure_safe_leaf(path)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def write_json_atomic(path: Path, data: Any, *, root: Path | None = None) -> None:
    write_text_atomic(path, canonical_json_text(data), root=root)


def load_plan(plan_path: Path) -> tuple[dict[str, Any], str]:
    plan = read_json(plan_path)
    try:
        validate_plan(plan)
    except EvaluationError as exc:
        raise CompileError("ERR_PLAN_INVALID", str(exc), path=plan_path) from exc
    if plan["activation"]["decision"] != "activate":
        raise CompileError("ERR_PLAN_DOWNGRADE", "V1 accepts only activated workflow plans", path=plan_path)
    return plan, canonical_hash(plan)


def ordered_unique(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = canonical_json_text(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def source_handoff_id(index: int, handoff: dict[str, Any]) -> str:
    return f"handoff-{index:04d}-{sha8(handoff)}"


def source_gate_id(index: int, gate: dict[str, Any]) -> str:
    return f"gate-{index:04d}-{sha8(gate)}"


def detect_risks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []

    def add(category: str | None, source_field: str, source_id: str, token: str) -> None:
        if category:
            detections.append(
                {
                    "risk_category": category,
                    "source_field": source_field,
                    "source_id": source_id,
                    "normalized_token": " ".join(normalize_tokens(token)),
                }
            )

    for surface in plan["surfaces"]:
        if surface["access_mode"] != "read-only":
            add("write", "surfaces.access_mode", surface["id"], surface["access_mode"])
    for worker in plan["workers"]:
        permissions = worker["tool_permissions"]
        if permissions["write"]:
            add("write", "workers.tool_permissions.write", worker["id"], "write")
        if permissions["shell"]:
            add("shell-process", "workers.tool_permissions.shell", worker["id"], "shell")
        if permissions["network"]:
            add("network", "workers.tool_permissions.network", worker["id"], "network")
        if permissions["mcp_connectors"]:
            add("external-message", "workers.tool_permissions.mcp_connectors", worker["id"], "external message")
    for index, gate in enumerate(plan["risk_gates"]):
        add(category_from_text(gate["trigger"]), "risk_gates.trigger", str(index), gate["trigger"])
    first_slice = plan["execution_path"]["first_slice"]
    for field in ["instruction", "expected_output", "completion_check"]:
        add(category_from_text(first_slice[field]), f"execution_path.first_slice.{field}", plan["plan_id"], first_slice[field])
    for index, action in enumerate(first_slice["forbidden_actions"]):
        add(category_from_text(action), "execution_path.first_slice.forbidden_actions", str(index), action)

    unique: dict[str, dict[str, Any]] = {}
    for detection in detections:
        key = canonical_json_text(detection)
        unique[key] = detection
    return sorted(unique.values(), key=lambda item: (item["risk_category"], item["source_field"], item["source_id"], item["normalized_token"]))


def source_gate_matches_category(gate: dict[str, Any], category: str) -> bool:
    return any(contains_token_sequence(gate["trigger"], alias) for alias in RISK_ALIASES[category])


def build_gates(plan: dict[str, Any], plan_hash: str, run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    detections = detect_risks(plan)
    detected_categories = {item["risk_category"] for item in detections}
    gates: list[dict[str, Any]] = []
    matched_categories: set[str] = set()
    for index, source_gate in enumerate(plan["risk_gates"]):
        category = category_from_text(source_gate["trigger"])
        if category and category in detected_categories:
            matched_categories.add(category)
        gates.append(
            {
                "gate_id": source_gate_id(index, source_gate),
                "trigger": source_gate["trigger"],
                "risk_category": category,
                "source": "plan",
                "source_index": index,
                "safe_default": source_gate["safe_default"],
                "requires_user_approval": source_gate["requires_user_approval"],
                "status": "blocked" if category in detected_categories else "not-required",
                "approved": False,
                "approval_source": None,
            }
        )
    for category in sorted(detected_categories - matched_categories):
        detection = next(item for item in detections if item["risk_category"] == category)
        gates.append(
            {
                "gate_id": f"gate-synthetic-{category}-{sha8(detection)}",
                "trigger": f"{category} detected by V1 compiler",
                "risk_category": category,
                "source": "compiler-synthetic",
                "source_index": None,
                "safe_default": RISK_SAFE_DEFAULTS[category],
                "requires_user_approval": True,
                "status": "blocked",
                "approved": False,
                "approval_source": None,
            }
        )
    approval_state = {"run_id": run_id, "plan_hash": plan_hash, "risk_policy": "block-all", "gates": gates}
    return gates, [approval_state]


def build_handoff_schemas(plan: dict[str, Any]) -> list[dict[str, Any]]:
    schemas = []
    for index, handoff in enumerate(plan["handoffs"]):
        schemas.append(
            {
                "schema_version": SCHEMA_VERSION,
                "handoff_id": source_handoff_id(index, handoff),
                "source_index": index,
                "from_phase": handoff["from_phase"],
                "to_phase": handoff["to_phase"],
                "artifact": handoff["artifact"],
                "artifact_schema": handoff["artifact_schema"],
            }
        )
    return schemas


def build_phase_context(plan: dict[str, Any], handoff_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases = []
    for phase in plan["phases"]:
        phase_id = phase["id"]
        phases.append(
            {
                "phase_id": phase_id,
                "depends_on": phase["depends_on"],
                "worker_ids": phase["worker_ids"],
                "handoffs_in": [item["handoff_id"] for item in handoff_schemas if item["to_phase"] == phase_id],
                "handoffs_out": [item["handoff_id"] for item in handoff_schemas if item["from_phase"] == phase_id],
                "context_only": True,
            }
        )
    return phases


def build_worker_refs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "worker_id": worker["id"],
            "role": worker["role"],
            "ownership": worker["ownership"],
            "tool_permissions": worker["tool_permissions"],
            "forbidden_actions": worker["forbidden_actions"],
            "context_budget": worker["context_budget"],
            "prompt_contract": worker["prompt_contract"],
            "context_only": True,
        }
        for worker in plan["workers"]
    ]


def build_allowed_tools(plan: dict[str, Any]) -> dict[str, Any]:
    allowed = {"read": False, "write": False, "shell": False, "network": False, "mcp_connectors": [], "requires_escalation_for": []}
    connectors: set[str] = set()
    escalations: set[str] = set()
    for worker in plan["workers"]:
        permissions = worker["tool_permissions"]
        for key in ["read", "write", "shell", "network"]:
            allowed[key] = bool(allowed[key] or permissions[key])
        connectors.update(map(str, permissions["mcp_connectors"]))
        escalations.update(map(str, permissions["requires_escalation_for"]))
    allowed["mcp_connectors"] = sorted(connectors)
    allowed["requires_escalation_for"] = sorted(escalations)
    return allowed


def classify_input(label: str) -> str:
    stripped = label.strip()
    if stripped.startswith("path:"):
        return "path"
    if stripped.startswith("glob:"):
        return "glob"
    if re.match(r"https?://", stripped):
        return "url"
    return "literal"


def path_hash(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() and not path.is_symlink() else None


def snapshot_input(label: str, index: int, plan: dict[str, Any], plan_path: Path) -> dict[str, Any]:
    kind = classify_input(label)
    normalized = label.strip()
    entries: list[dict[str, Any]]
    exists = False
    if label == "workflow.plan.json":
        kind = "path"
        target = plan_path.resolve()
        normalized = rel_or_abs(target)
        exists = target.is_file()
        entries = [{"path": normalized, "exists": exists, "sha256": path_hash(target)}]
    elif label == "blueprint.md" and (plan_path.parent / "blueprint.md").exists():
        kind = "path"
        target = (plan_path.parent / "blueprint.md").resolve()
        normalized = rel_or_abs(target)
        exists = target.exists()
        entries = [{"path": normalized, "exists": exists, "sha256": path_hash(target)}]
    elif label == "original prompt":
        kind = "literal"
        normalized = plan["source_prompt"]
        exists = True
        entries = [{"value": normalized, "sha256": sha256_text(normalized)}]
    elif label == "repository path":
        kind = "path"
        target = ROOT.resolve()
        normalized = rel(target)
        exists = True
        entries = [{"path": normalized, "exists": True, "sha256": None}]
    elif kind == "path":
        target = Path(label.removeprefix("path:").strip())
        target = target if target.is_absolute() else plan_path.parent / target
        normalized = rel_or_abs(target)
        exists = target.exists()
        entries = [{"path": normalized, "exists": exists, "sha256": path_hash(target)}]
    elif kind == "glob":
        pattern = label.removeprefix("glob:").strip()
        matches = sorted(plan_path.parent.glob(pattern))
        entries = []
        for match in matches:
            resolved = match.resolve(strict=False)
            entry_path = rel_or_abs(resolved)
            entries.append({"path": entry_path, "exists": match.exists(), "sha256": path_hash(match)})
        exists = bool(entries)
        normalized = pattern
    else:
        exists = kind in {"literal", "url"}
        entries = [{"value": normalized, "sha256": sha256_text(normalized)}]
    record = {
        "source_index": index,
        "input_label": label,
        "input_kind": kind,
        "normalized_value": normalized,
        "exists_at_compile_time": exists,
        "snapshot_entries": entries,
    }
    input_id = f"input-{index:04d}-{sha8(record)}"
    return {"input_id": input_id, **record, "hash": canonical_hash(record)}


def input_snapshot_hash(input_snapshots: list[dict[str, Any]]) -> str:
    return canonical_hash(sorted(input_snapshots, key=lambda item: item["input_id"]))


def valid_input_snapshot(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    required = {
        "input_id": str,
        "source_index": int,
        "input_label": str,
        "input_kind": str,
        "normalized_value": str,
        "exists_at_compile_time": bool,
        "snapshot_entries": list,
        "hash": str,
    }
    for key, expected_type in required.items():
        if key not in item or not isinstance(item[key], expected_type):
            return False
    return all(isinstance(entry, dict) for entry in item["snapshot_entries"])


def build_packet(
    plan: dict[str, Any],
    plan_path: Path,
    handoff_schemas: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    prompt_hash: str,
) -> dict[str, Any]:
    first_slice = plan["execution_path"]["first_slice"]
    input_snapshots = [snapshot_input(label, index, plan, plan_path) for index, label in enumerate(first_slice["inputs"])]
    blocked_gate_triggers = [gate["trigger"] for gate in gates if gate["status"] == "blocked"]
    forbidden = ordered_unique(first_slice["forbidden_actions"] + [item for worker in plan["workers"] for item in worker["forbidden_actions"]])
    phase_context = build_phase_context(plan, handoff_schemas)
    worker_refs = build_worker_refs(plan)
    packet = {
        "packet_id": PACKET_ID,
        "source_plan_id": plan["plan_id"],
        "source_first_slice": first_slice,
        "objective": plan["objective"],
        "surface_refs": [
            {
                "surface_id": surface["id"],
                "kind": surface["kind"],
                "locator": surface["locator"],
                "access_mode": surface["access_mode"],
            }
            for surface in plan["surfaces"]
        ],
        "phase_context": phase_context,
        "worker_refs": worker_refs,
        "allowed_tools": build_allowed_tools(plan),
        "forbidden_actions": forbidden,
        "risk_gate_refs": [gate["gate_id"] for gate in gates],
        "handoff_refs": [{"handoff_id": item["handoff_id"], "context_only": True} for item in handoff_schemas],
        "verification": plan["verification"],
        "completion_check": first_slice["completion_check"],
        "input_snapshots": input_snapshots,
        "input_snapshot_hash": input_snapshot_hash(input_snapshots),
        "prompt_contract": {
            "inputs": first_slice["inputs"],
            "required_output_schema": first_slice["expected_output"],
            "stop_conditions": ordered_unique(first_slice["forbidden_actions"] + blocked_gate_triggers),
        },
        "prompt_path": "packets/001-first-slice.prompt.md",
        "prompt_hash": prompt_hash,
    }
    return packet


def packet_digest(packet: dict[str, Any]) -> dict[str, Any]:
    return {field: packet[field] for field in DIGEST_FIELDS}


def render_prompt(packet: dict[str, Any], gates: list[dict[str, Any]]) -> str:
    digest = packet_digest(packet)
    lines = [
        "# Packet 001-first-slice",
        "",
        "Prompt SHA-256: {{PROMPT_SHA256}}",
        f"Source plan: {packet['source_plan_id']}",
        "",
        "## Objective",
        packet["objective"],
        "",
        "## Inputs",
    ]
    for item in packet["input_snapshots"]:
        lines.append(f"- `{item['input_id']}` {item['input_label']} ({item['input_kind']}): {item['normalized_value']}")
    lines.extend(["", "## Ownership"])
    for worker in packet["worker_refs"]:
        lines.append(f"- `{worker['worker_id']}`: {worker['role']}; ownership: {', '.join(worker['ownership'])}")
    lines.extend(["", "## Allowed Tools", f"```json\n{canonical_json_text(packet['allowed_tools'])}\n```", "", "## Forbidden Actions"])
    for action in packet["forbidden_actions"]:
        lines.append(f"- {action}")
    lines.extend(["", "## Risk Gates"])
    for gate in gates:
        lines.append(f"- `{gate['gate_id']}` [{gate['status']}]: {gate['trigger']}")
    lines.extend(["", "## Required Output", packet["prompt_contract"]["required_output_schema"], "", "## Verification"])
    for item in packet["verification"]:
        lines.append(f"- {item['claim_or_output']}: {item['falsifier']}")
    lines.extend(
        [
            "",
            "## Handoff Context",
            "```packet_contract_digest",
            canonical_json_text(digest),
            "```",
            "",
            "## Stop Conditions",
        ]
    )
    for condition in packet["prompt_contract"]["stop_conditions"]:
        lines.append(f"- {condition}")
    lines.append(f"- Completion check: {packet['completion_check']}")
    return "\n".join(lines) + "\n"


def parse_prompt_digest(prompt: str) -> dict[str, Any]:
    match = re.search(r"```packet_contract_digest\n(?P<body>.*?)\n```", prompt, re.DOTALL)
    if not match:
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt is missing packet_contract_digest block")
    try:
        data = json.loads(match.group("body"))
    except json.JSONDecodeError as exc:
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", f"prompt digest is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt digest must be an object")
    return data


def verify_prompt_packet(prompt: str, packet: dict[str, Any], gates: list[dict[str, Any]] | None = None) -> None:
    for heading in PROMPT_HEADINGS:
        if heading not in prompt:
            raise CompileError("ERR_PROMPT_PACKET_DRIFT", f"prompt missing heading: {heading}")
    digest = parse_prompt_digest(prompt)
    expected = packet_digest(packet)
    if canonical_json_text(digest) != canonical_json_text(expected):
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt digest does not match packet JSON")
    for gate_id in packet["risk_gate_refs"]:
        if f"`{gate_id}`" not in prompt:
            raise CompileError("ERR_PROMPT_PACKET_DRIFT", f"prompt missing gate ID: {gate_id}")
    if packet["packet_id"] not in prompt or packet["source_plan_id"] not in prompt:
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt missing packet or source plan ID")
    objective = section_body(prompt, "## Objective", "## Inputs")
    if objective != packet["objective"]:
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt objective section does not match packet JSON")
    required_output = section_body(prompt, "## Required Output", "## Verification")
    if required_output != packet["prompt_contract"]["required_output_schema"]:
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt required output section does not match packet JSON")
    if f"Completion check: {packet['completion_check']}" not in section_body(prompt, "## Stop Conditions", ""):
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt completion check does not match packet JSON")
    if gates is not None and prompt != render_prompt(packet, gates):
        raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt sections do not match rendered packet contract")


def section_body(prompt: str, start: str, end: str) -> str:
    if start not in prompt:
        return ""
    after = prompt.split(start, 1)[1]
    if end and end in after:
        after = after.split(end, 1)[0]
    return after.strip()


def gate_snapshot_hash(gates: list[dict[str, Any]]) -> str:
    return canonical_hash([{"gate_id": gate["gate_id"], "approval_hash": canonical_hash(gate)} for gate in gates])


def build_status(
    run_id: str,
    plan_hash: str,
    source_plan_hash: str,
    packet: dict[str, Any],
    handoff_schemas: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    approval_state: dict[str, Any],
    *,
    resume_state: str = "fresh",
    invalidators: list[dict[str, Any]] | None = None,
    checked_at: str | None = None,
    resume_result: str | None = None,
) -> dict[str, Any]:
    packet_hash = canonical_hash(packet)
    packet_status = "blocked-risk-gate" if any(gate["status"] == "blocked" for gate in gates) else "ready"
    if invalidators:
        packet_status = "invalidated"
    gate_hashes = {gate["gate_id"]: canonical_hash(gate) for gate in gates}
    return {
        "run_id": run_id,
        "plan_hash": plan_hash,
        "source_plan_hash": source_plan_hash,
        "resume_state": resume_state,
        "packet_statuses": [
            {
                "packet_id": PACKET_ID,
                "status": packet_status,
                "reason": "blocked by V1 risk gates" if packet_status == "blocked-risk-gate" else ("resume invalidated" if invalidators else "not blocked by V1 checks"),
                "packet_hash": packet_hash,
                "prompt_hash": packet["prompt_hash"],
                "input_snapshot_hash": packet["input_snapshot_hash"],
                "gate_snapshot_hash": gate_snapshot_hash(gates),
            }
        ],
        "handoff_statuses": [
            {"handoff_id": item["handoff_id"], "schema_hash": canonical_hash(item), "source_index": item["source_index"]}
            for item in handoff_schemas
        ],
        "gate_statuses": [
            {
                "gate_id": gate["gate_id"],
                "trigger": gate["trigger"],
                "status": "invalidated" if invalidators else gate["status"],
                "approval_hash": gate_hashes[gate["gate_id"]],
                "source": gate["source"],
                "source_index": gate["source_index"],
                "risk_category": gate["risk_category"],
            }
            for gate in gates
        ],
        "snapshots": {
            "plan_hash": plan_hash,
            "packet_hashes": {PACKET_ID: packet_hash},
            "prompt_hashes": {packet["prompt_path"]: packet["prompt_hash"]},
            "input_snapshot_hashes": {PACKET_ID: packet["input_snapshot_hash"]},
            "handoff_schema_hashes": {item["handoff_id"]: canonical_hash(item) for item in handoff_schemas},
            "approval_state_hash": canonical_hash(approval_state),
            "gate_approval_hashes": gate_hashes,
            "compiler_version": COMPILER_VERSION,
        },
        "invalidators": invalidators or [],
        "last_resume_checked_at": checked_at,
        "last_resume_result": resume_result,
    }


def build_compile_artifacts(plan: dict[str, Any], plan_path: Path, run_id: str, source_plan_hash: str) -> dict[str, Any]:
    plan_hash = canonical_hash(plan)
    handoff_schemas = build_handoff_schemas(plan)
    gates, approval_wrappers = build_gates(plan, plan_hash, run_id)
    approval_state = approval_wrappers[0]
    prompt_hash_placeholder = "0" * 64
    packet = build_packet(plan, plan_path.resolve(strict=False), handoff_schemas, gates, prompt_hash_placeholder)
    prompt = render_prompt(packet, gates)
    prompt_hash = sha256_text(prompt)
    packet = build_packet(plan, plan_path.resolve(strict=False), handoff_schemas, gates, prompt_hash)
    prompt = render_prompt(packet, gates)
    verify_prompt_packet(prompt, packet, gates)
    status = build_status(run_id, plan_hash, source_plan_hash, packet, handoff_schemas, gates, approval_state)
    context_phases = {"schema_version": SCHEMA_VERSION, "source_plan_id": plan["plan_id"], "phases": build_phase_context(plan, handoff_schemas)}
    context_workers = {"schema_version": SCHEMA_VERSION, "source_plan_id": plan["plan_id"], "workers": build_worker_refs(plan)}
    context_parallelism = {"schema_version": SCHEMA_VERSION, "source_plan_id": plan["plan_id"], "parallelism": plan["parallelism"]}
    return {
        "plan_hash": plan_hash,
        "handoffs": handoff_schemas,
        "gates": gates,
        "approval_state": approval_state,
        "packet": packet,
        "prompt": prompt,
        "status": status,
        "contexts": {
            "context/phases.json": context_phases,
            "context/workers.json": context_workers,
            "context/parallelism.json": context_parallelism,
        },
    }


def sentinel_payload(run_id: str, mode: str, run: dict[str, Any] | None = None, status: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": TOOL,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "created_at": now_utc(),
    }
    if run is not None and status is not None:
        payload.update(
            {
                "source_plan_path": run["source_plan_path"],
                "source_plan_hash": run["source_plan_hash"],
                "plan_hash": run["plan_hash"],
                "snapshots": status["snapshots"],
                "packet_statuses": status["packet_statuses"],
                "handoff_statuses": status["handoff_statuses"],
                "gate_statuses": status["gate_statuses"],
            }
        )
    return payload


def anchored_status_sections(sentinel: dict[str, Any], *, invalidated: bool) -> dict[str, Any]:
    packet_statuses = copy.deepcopy(sentinel["packet_statuses"])
    handoff_statuses = copy.deepcopy(sentinel["handoff_statuses"])
    gate_statuses = copy.deepcopy(sentinel["gate_statuses"])
    if invalidated:
        for item in packet_statuses:
            item["status"] = "invalidated"
            item["reason"] = "resume invalidated"
        for item in gate_statuses:
            item["status"] = "invalidated"
    return {
        "packet_statuses": packet_statuses,
        "handoff_statuses": handoff_statuses,
        "gate_statuses": gate_statuses,
    }


def render_readme(status: dict[str, Any], gates: list[dict[str, Any]]) -> str:
    packet_status = status["packet_statuses"][0]["status"]
    blocked = [gate for gate in gates if gate["status"] == "blocked"]
    lines = [
        "# V1 First-Slice Run",
        "",
        "Read `packets/001-first-slice.prompt.md` first.",
        "",
        "V1 compiled this packet only; it did not execute the workflow, spawn agents, run commands, or mark work complete.",
        "",
        f"Packet status: `{packet_status}`.",
        "",
        "## Blocked Gates",
    ]
    if blocked:
        lines.extend(f"- `{gate['gate_id']}`: {gate['trigger']}" for gate in blocked)
        lines.extend(
            [
                "",
                "V1 has no machine approval path for blocked packets. Return to the user or wait for V2 tooling before treating this packet as actionable.",
            ]
        )
    else:
        lines.append("- none")
        lines.extend(["", "Allowed next manual action: inspect the packet prompt and decide whether to execute it outside V1."])
    return "\n".join(lines) + "\n"


def render_resume(status: dict[str, Any], packet: dict[str, Any] | None = None) -> str:
    lines = [
        "# V1 Resume Check",
        "",
        f"Run ID: `{status['run_id']}`",
        f"State: `{status['resume_state']}`",
        f"Last result: `{status['last_resume_result']}`",
        "",
        "V1 only checks whether compiled first-slice files are still trustworthy. It does not resume completed work.",
        "",
        "## Invalidators",
    ]
    if status["invalidators"]:
        for item in status["invalidators"]:
            lines.append(f"- `{item['code']}` {item['kind']} `{item['id']}`: {item['message']}")
    else:
        lines.append("- none")
    if packet:
        directory_inputs = [
            item["input_id"]
            for item in packet["input_snapshots"]
            if any(entry.get("exists") and entry.get("sha256") is None and "path" in entry for entry in item["snapshot_entries"])
        ]
        if directory_inputs:
            lines.extend(["", "## Directory Inputs", "Directories are recorded but not recursively hashed in V1."])
            lines.extend(f"- `{input_id}`" for input_id in directory_inputs)
    return "\n".join(lines) + "\n"


def ensure_replaceable_run_dir(path: Path, run_id: str, mode: str) -> None:
    if not path.exists():
        return
    if path.is_symlink():
        raise CompileError("ERR_OUT_PATH_SYMLINK", "run directory is a symlink", path=path)
    if not path.is_dir():
        raise CompileError("ERR_OUT_PATH_UNSAFE", "output path exists and is not a directory", path=path)
    if not sentinel_matches(path, run_id, mode):
        raise CompileError("ERR_OUT_PATH_NOT_OWNED", "existing run directory is not compiler-owned", path=path)


def publish_owned_tree(staging: Path, out_dir: Path, run_id: str, mode: str) -> None:
    ensure_replaceable_run_dir(out_dir, run_id, mode)
    backup: Path | None = None
    published = False
    try:
        if out_dir.exists():
            backup = out_dir.parent / f".{out_dir.name}.old-{os.getpid()}-{sha8(str(staging))}"
            os.replace(out_dir, backup)
        try:
            os.replace(staging, out_dir)
            published = True
        except BaseException:
            if backup is not None and backup.exists() and not out_dir.exists():
                os.replace(backup, out_dir)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        if published and backup is not None and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def write_compile_tree(out_dir: Path, run: dict[str, Any], artifacts: dict[str, Any], mode: str) -> None:
    status = artifacts["status"]
    packet = artifacts["packet"]
    gates = artifacts["gates"]
    handoff_schemas = artifacts["handoffs"]
    write_json_atomic(out_dir / "run.json", run, root=out_dir)
    write_json_atomic(out_dir / "status.json", status, root=out_dir)
    write_text_atomic(out_dir / "resume.md", render_resume(status, packet), root=out_dir)
    write_text_atomic(out_dir / "README.md", render_readme(status, gates), root=out_dir)
    write_json_atomic(out_dir / "plan.snapshot.json", artifacts["plan"], root=out_dir)
    write_text_atomic(out_dir / "plan.sha256", artifacts["plan_hash"] + "\n", root=out_dir)
    write_json_atomic(out_dir / "packets" / "001-first-slice.packet.json", packet, root=out_dir)
    write_text_atomic(out_dir / "packets" / "001-first-slice.prompt.md", artifacts["prompt"], root=out_dir)
    for handoff in handoff_schemas:
        write_json_atomic(out_dir / "handoffs" / f"{handoff['handoff_id']}.schema.json", handoff, root=out_dir)
    write_json_atomic(out_dir / "gates" / "approval-state.json", artifacts["approval_state"], root=out_dir)
    for gate in gates:
        write_text_atomic(
            out_dir / "gates" / f"{gate['gate_id']}.approval.md",
            f"# Gate {gate['gate_id']}\n\nStatus: {gate['status']}\n\nTrigger: {gate['trigger']}\n\nV1 does not accept Markdown approval as machine approval.\n",
            root=out_dir,
        )
    for rel_path, context in artifacts["contexts"].items():
        write_json_atomic(out_dir / rel_path, context, root=out_dir)
    write_json_atomic(out_dir / SENTINEL, sentinel_payload(run["run_id"], mode, run, status), root=out_dir)


def publish_compile_tree(out_dir: Path, run_id: str, mode: str, run: dict[str, Any], artifacts: dict[str, Any]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_safe_artifact_parent(OUT_ROOT, out_dir.parent / ".publish")
    ensure_replaceable_run_dir(out_dir, run_id, mode)
    staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.", dir=out_dir.parent))
    try:
        write_json_atomic(staging / SENTINEL, sentinel_payload(run_id, mode), root=staging)
        write_compile_tree(staging, run, artifacts, mode)
        publish_owned_tree(staging, out_dir, run_id, mode)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def compile_plan(plan_path: Path, out_dir: Path, *, run_id: str | None = None, mode: str = "compile") -> dict[str, Any]:
    plan_path = plan_path.resolve(strict=False)
    try:
        plan_path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise CompileError("ERR_PLAN_INVALID", "plan path must resolve under the repository root", path=plan_path) from exc
    run_id = run_id or out_dir.name
    out_dir = resolve_v1_out(out_dir)
    plan, source_plan_hash = load_plan(plan_path)
    artifacts = build_compile_artifacts(plan, plan_path, run_id, source_plan_hash)
    artifacts["plan"] = plan
    plan_hash = artifacts["plan_hash"]
    packet_hash = canonical_hash(artifacts["packet"])
    run = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "created_at": now_utc(),
        "source_plan_path": rel_or_abs(plan_path),
        "source_plan_hash": source_plan_hash,
        "plan_hash": plan_hash,
        "compiler_version": COMPILER_VERSION,
        "mode": "compile",
        "risk_policy": "block-all",
        "status_path": "status.json",
        "packet_paths": ["packets/001-first-slice.packet.json"],
        "approval_state_path": "gates/approval-state.json",
    }
    publish_compile_tree(out_dir, run_id, mode, run, artifacts)
    return {
        "run": run,
        "status": artifacts["status"],
        "packet": artifacts["packet"],
        "gates": artifacts["gates"],
        "handoffs": artifacts["handoffs"],
        "contexts": artifacts["contexts"],
        "packet_hash": packet_hash,
        "out_dir": out_dir,
    }


def missing_invalidator(kind: str, artifact_id: str, message: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": artifact_id,
        "code": RESUME_CODES["missing"],
        "expected_hash": None,
        "actual_hash": None,
        "message": message,
    }


def hash_invalidator(kind: str, artifact_id: str, expected: str | None, actual: str | None, message: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": artifact_id,
        "code": RESUME_CODES[kind],
        "expected_hash": expected,
        "actual_hash": actual,
        "message": message,
    }


def read_metadata_json(path: Path, run_dir: Path, label: str) -> dict[str, Any]:
    try:
        ensure_safe_artifact_read(run_dir, path)
    except CompileError as exc:
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"{label} path is unsafe: {exc.message}", path=path) from exc
    if not path.is_file() or path.is_symlink():
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"{label} is missing or symlinked", path=path)
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"{label} JSON is malformed: {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"{label} JSON root must be an object", path=path)
    return data


def require_resume_metadata(sentinel: dict[str, Any], run: dict[str, Any], status: dict[str, Any], run_dir: Path) -> None:
    for key in ["tool", "schema_version", "run_id", "mode"]:
        if not isinstance(sentinel.get(key), str):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel missing string key: {key}", path=run_dir)
    for key in ["run_id", "source_plan_path", "source_plan_hash", "plan_hash", "compiler_version"]:
        if not isinstance(run.get(key), str):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"run.json missing string key: {key}", path=run_dir)
    if not isinstance(status.get("plan_hash"), str) or not isinstance(status.get("source_plan_hash"), str):
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", "status.json missing top-level plan hashes", path=run_dir)
    snapshots = status.get("snapshots")
    if not isinstance(snapshots, dict):
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", "status.json missing snapshots object", path=run_dir)
    for key in ["plan_hash", "approval_state_hash", "compiler_version"]:
        if not isinstance(snapshots.get(key), str):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"status snapshots missing string key: {key}", path=run_dir)
    for key in ["packet_hashes", "prompt_hashes", "input_snapshot_hashes", "handoff_schema_hashes", "gate_approval_hashes"]:
        if not isinstance(snapshots.get(key), dict):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"status snapshots missing object key: {key}", path=run_dir)
    for key in ["source_plan_path", "source_plan_hash", "plan_hash"]:
        if not isinstance(sentinel.get(key), str):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel missing string key: {key}", path=run_dir)
    sentinel_snapshots = sentinel.get("snapshots")
    if not isinstance(sentinel_snapshots, dict):
        raise CompileError("ERR_RESUME_MISSING_ARTIFACT", "sentinel missing snapshots object", path=run_dir)
    for key in ["plan_hash", "approval_state_hash", "compiler_version"]:
        if not isinstance(sentinel_snapshots.get(key), str):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel snapshots missing string key: {key}", path=run_dir)
    for key in ["packet_hashes", "prompt_hashes", "input_snapshot_hashes", "handoff_schema_hashes", "gate_approval_hashes"]:
        if not isinstance(sentinel_snapshots.get(key), dict):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel snapshots missing object key: {key}", path=run_dir)
    for key in ["packet_statuses", "handoff_statuses", "gate_statuses"]:
        if not isinstance(sentinel.get(key), list):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel missing list key: {key}", path=run_dir)
        if not all(isinstance(item, dict) for item in sentinel[key]):
            raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel list contains non-object entries: {key}", path=run_dir)
    sentinel_status_keys = {
        "packet_statuses": {"packet_id", "status", "reason", "packet_hash", "prompt_hash", "input_snapshot_hash", "gate_snapshot_hash"},
        "handoff_statuses": {"handoff_id", "schema_hash", "source_index"},
        "gate_statuses": {"gate_id", "trigger", "status", "approval_hash", "source", "source_index", "risk_category"},
    }
    for section, required_keys in sentinel_status_keys.items():
        for item in sentinel[section]:
            if not required_keys <= set(item):
                raise CompileError("ERR_RESUME_MISSING_ARTIFACT", f"sentinel status entry is malformed: {section}", path=run_dir)


def read_resume_json(path: Path, kind: str, artifact_id: str, invalidators: list[dict[str, Any]], *, root: Path | None = None) -> dict[str, Any] | None:
    try:
        if root is not None:
            ensure_safe_artifact_read(root, path)
    except CompileError:
        invalidators.append(missing_invalidator(kind, artifact_id, "artifact path is missing, unsafe, or symlinked"))
        return None
    if not path.is_file() or path.is_symlink():
        invalidators.append(missing_invalidator(kind, artifact_id, "artifact is missing or symlinked"))
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        invalidators.append(hash_invalidator(kind, artifact_id, None, sha256_text(path.read_text()), "artifact JSON is malformed"))
        return None
    if not isinstance(data, dict):
        invalidators.append(hash_invalidator(kind, artifact_id, None, canonical_hash(data), "artifact JSON root must be an object"))
        return None
    return data


def read_resume_text(path: Path, kind: str, artifact_id: str, invalidators: list[dict[str, Any]], *, root: Path | None = None) -> str | None:
    try:
        if root is not None:
            ensure_safe_artifact_read(root, path)
    except CompileError:
        invalidators.append(missing_invalidator(kind, artifact_id, "artifact path is missing, unsafe, or symlinked"))
        return None
    if not path.is_file() or path.is_symlink():
        invalidators.append(missing_invalidator(kind, artifact_id, "artifact is missing or symlinked"))
        return None
    return path.read_text()


def input_drift_id(stored: list[dict[str, Any]], recomputed: list[dict[str, Any]]) -> str:
    stored_by_position = {item.get("source_index"): item for item in stored}
    for item in recomputed:
        old = stored_by_position.get(item.get("source_index"))
        if old != item:
            return str(old.get("input_id") if isinstance(old, dict) else item.get("input_id"))
    return PACKET_ID


def resume_run(run_dir: Path) -> dict[str, Any]:
    run_dir = resolve_v1_out(run_dir)
    sentinel_path = run_dir / SENTINEL
    run_path = run_dir / "run.json"
    status_path = run_dir / "status.json"
    sentinel = read_metadata_json(sentinel_path, run_dir, "sentinel")
    run = read_metadata_json(run_path, run_dir, "run.json")
    old_status = read_metadata_json(status_path, run_dir, "status.json")
    require_resume_metadata(sentinel, run, old_status, run_dir)
    if (
        sentinel.get("tool") != TOOL
        or sentinel.get("schema_version") != SCHEMA_VERSION
        or sentinel.get("run_id") != run.get("run_id")
        or sentinel.get("mode") not in {"compile", "fixture"}
    ):
        raise CompileError("ERR_OUT_PATH_NOT_OWNED", "resume sentinel does not match run metadata", path=run_dir)
    invalidators: list[dict[str, Any]] = []
    trusted_snapshots = sentinel["snapshots"]
    if sentinel["source_plan_path"] != run["source_plan_path"]:
        invalidators.append(
            hash_invalidator("plan", "run.json.source_plan_path", sentinel["source_plan_path"], run["source_plan_path"], "source plan path changed")
        )
    if sentinel["source_plan_hash"] != run["source_plan_hash"]:
        invalidators.append(
            hash_invalidator("plan", "run.json.source_plan_hash", sentinel["source_plan_hash"], run["source_plan_hash"], "run source plan hash changed")
        )
    if sentinel["plan_hash"] != run["plan_hash"]:
        invalidators.append(hash_invalidator("plan", "run.json.plan_hash", sentinel["plan_hash"], run["plan_hash"], "run plan hash changed"))
    if old_status.get("run_id") != run["run_id"]:
        invalidators.append(hash_invalidator("plan", "status.json.run_id", run["run_id"], str(old_status.get("run_id")), "status run id changed"))
    if old_status["source_plan_hash"] != sentinel["source_plan_hash"]:
        invalidators.append(
            hash_invalidator(
                "plan",
                "status.json.source_plan_hash",
                sentinel["source_plan_hash"],
                old_status["source_plan_hash"],
                "status source plan hash changed",
            )
        )
    if old_status["plan_hash"] != sentinel["plan_hash"]:
        invalidators.append(
            hash_invalidator(
                "plan",
                "status.json.plan_hash",
                sentinel["plan_hash"],
                old_status["plan_hash"],
                "status plan hash changed",
            )
        )
    status_snapshots = old_status["snapshots"]
    for key, kind in [
        ("plan_hash", "plan"),
        ("compiler_version", "compiler"),
        ("approval_state_hash", "gate"),
        ("packet_hashes", "packet"),
        ("prompt_hashes", "prompt"),
        ("input_snapshot_hashes", "input"),
        ("handoff_schema_hashes", "handoff"),
        ("gate_approval_hashes", "gate"),
    ]:
        if status_snapshots.get(key) != trusted_snapshots.get(key):
            invalidators.append(
                hash_invalidator(
                    kind,
                    f"status.json.snapshots.{key}",
                    canonical_hash(trusted_snapshots.get(key)),
                    canonical_hash(status_snapshots.get(key)),
                    f"status snapshot {key} changed",
                )
            )
    try:
        source_plan = safe_resume_source_plan_path(run["source_plan_path"])
    except CompileError:
        source_plan = ROOT / "__unsafe_resume_source_plan__"
        invalidators.append(hash_invalidator("plan", run["source_plan_path"], sentinel["source_plan_hash"], None, "source plan path is unsafe"))
    source_hash = None
    expected_artifacts: dict[str, Any] | None = None
    if not source_plan.is_file() or source_plan.is_symlink():
        invalidators.append(hash_invalidator("plan", str(source_plan), sentinel["source_plan_hash"], None, "source plan is missing"))
        plan = None
    else:
        plan = read_resume_json(source_plan, "plan", run["source_plan_path"], invalidators)
        if isinstance(plan, dict):
            source_hash = canonical_hash(plan)
            if source_hash != sentinel["source_plan_hash"]:
                invalidators.append(hash_invalidator("plan", run["source_plan_path"], sentinel["source_plan_hash"], source_hash, "source plan hash changed"))
            try:
                validate_plan(plan)
            except EvaluationError as exc:
                invalidators.append(hash_invalidator("plan", run["source_plan_path"], sentinel["source_plan_hash"], source_hash, f"source plan is invalid: {exc}"))
                plan = None
            if isinstance(plan, dict) and source_hash == sentinel["source_plan_hash"]:
                expected_artifacts = build_compile_artifacts(plan, source_plan, run["run_id"], sentinel["source_plan_hash"])
                expected_status = expected_artifacts["status"]
                if expected_status["snapshots"] != trusted_snapshots:
                    invalidators.append(
                        hash_invalidator(
                            "plan",
                            "sentinel.snapshots",
                            canonical_hash(expected_status["snapshots"]),
                            canonical_hash(trusted_snapshots),
                            "sentinel snapshots do not match source plan",
                        )
                    )
                for section, kind in [
                    ("packet_statuses", "packet"),
                    ("gate_statuses", "gate"),
                    ("handoff_statuses", "handoff"),
                ]:
                    if sentinel.get(section) != expected_status[section]:
                        invalidators.append(
                            hash_invalidator(
                                kind,
                                f"sentinel.{section}",
                                canonical_hash(expected_status[section]),
                                canonical_hash(sentinel.get(section)),
                                f"sentinel {section} does not match source plan",
                            )
                        )
    snapshot_path = run_dir / "plan.snapshot.json"
    snapshot = read_resume_json(snapshot_path, "plan", "plan.snapshot.json", invalidators, root=run_dir)
    if isinstance(snapshot, dict):
        actual = canonical_hash(snapshot)
        expected = trusted_snapshots["plan_hash"]
        if actual != expected:
            invalidators.append(hash_invalidator("plan", "plan.snapshot.json", expected, actual, "plan snapshot hash changed"))
    packet_path = run_dir / "packets" / "001-first-slice.packet.json"
    packet: dict[str, Any] | None = None
    raw_packet = read_resume_json(packet_path, "packet", PACKET_ID, invalidators, root=run_dir)
    if isinstance(raw_packet, dict):
        required_packet_keys = {"prompt_hash", "input_snapshot_hash", "prompt_path", "input_snapshots"}
        if not required_packet_keys <= set(raw_packet):
            invalidators.append(hash_invalidator("packet", PACKET_ID, trusted_snapshots["packet_hashes"].get(PACKET_ID), canonical_hash(raw_packet), "packet JSON is missing required fields"))
        else:
            packet = raw_packet
    if packet is not None:
        actual = canonical_hash(packet)
        expected = trusted_snapshots["packet_hashes"].get(PACKET_ID)
        if actual != expected:
            invalidators.append(hash_invalidator("packet", PACKET_ID, expected, actual, "packet hash changed"))
        stored_inputs = packet.get("input_snapshots", [])
        if isinstance(stored_inputs, list) and all(valid_input_snapshot(item) for item in stored_inputs):
            input_actual = input_snapshot_hash(stored_inputs)
            input_expected = trusted_snapshots["input_snapshot_hashes"].get(PACKET_ID)
            if input_actual != input_expected:
                invalidators.append(hash_invalidator("input", PACKET_ID, input_expected, input_actual, "input snapshot hash changed"))
        else:
            input_expected = trusted_snapshots["input_snapshot_hashes"].get(PACKET_ID)
            stored_inputs = []
            invalidators.append(hash_invalidator("input", PACKET_ID, input_expected, None, "packet input snapshots are malformed"))
            packet = None
        if expected_artifacts is not None:
            recomputed_inputs = expected_artifacts["packet"]["input_snapshots"]
            recomputed_hash = input_snapshot_hash(recomputed_inputs)
            if recomputed_hash != input_expected:
                invalidators.append(
                    hash_invalidator(
                        "input",
                        input_drift_id(stored_inputs, recomputed_inputs),
                        input_expected,
                        recomputed_hash,
                        "live input snapshot hash changed",
                    )
                )
    prompt_rel = "packets/001-first-slice.prompt.md"
    prompt_path = run_dir / prompt_rel
    prompt_text = read_resume_text(prompt_path, "prompt", prompt_rel, invalidators, root=run_dir)
    if prompt_text is not None:
        actual = sha256_text(prompt_text)
        expected = trusted_snapshots["prompt_hashes"].get(prompt_rel)
        if actual != expected:
            invalidators.append(hash_invalidator("prompt", prompt_rel, expected, actual, "prompt hash changed"))
        if packet is not None:
            try:
                verify_prompt_packet(prompt_text, packet)
            except CompileError:
                invalidators.append(hash_invalidator("prompt", prompt_rel, expected, actual, "prompt and packet contract disagree"))
            if packet.get("prompt_path") != prompt_rel:
                invalidators.append(hash_invalidator("prompt", prompt_rel, prompt_rel, str(packet.get("prompt_path")), "packet prompt path changed"))
            if packet.get("prompt_hash") != actual:
                invalidators.append(hash_invalidator("prompt", prompt_rel, actual, str(packet.get("prompt_hash")), "packet prompt hash changed"))
    handoff_schemas = []
    for handoff_id in old_status["snapshots"].get("handoff_schema_hashes", {}):
        try:
            safe_descendant_path(run_dir / "handoffs", f"{handoff_id}.schema.json")
        except CompileError:
            invalidators.append(missing_invalidator("handoff", str(handoff_id), "handoff snapshot id is unsafe"))
    for handoff_id, expected in trusted_snapshots["handoff_schema_hashes"].items():
        path = run_dir / "handoffs" / f"{handoff_id}.schema.json"
        item = read_resume_json(path, "handoff", handoff_id, invalidators, root=run_dir)
        if not isinstance(item, dict):
            continue
        if item.get("handoff_id") != handoff_id or "source_index" not in item:
            invalidators.append(hash_invalidator("handoff", handoff_id, expected, canonical_hash(item), "handoff schema is malformed"))
            continue
        handoff_schemas.append(item)
        actual = canonical_hash(item)
        if actual != expected:
            invalidators.append(hash_invalidator("handoff", handoff_id, expected, actual, "handoff schema hash changed"))
    approval_path = run_dir / "gates" / "approval-state.json"
    gates = []
    approval_state = {"gates": []}
    raw_approval_state = read_resume_json(approval_path, "gate", "approval-state.json", invalidators, root=run_dir)
    if isinstance(raw_approval_state, dict):
        approval_state = raw_approval_state
        raw_gates = approval_state.get("gates", [])
        if not isinstance(raw_gates, list):
            raw_gates = []
            invalidators.append(hash_invalidator("gate", "approval-state.json", trusted_snapshots["approval_state_hash"], canonical_hash(approval_state), "approval state gates are malformed"))
        actual = canonical_hash(approval_state)
        expected = trusted_snapshots["approval_state_hash"]
        if actual != expected:
            invalidators.append(hash_invalidator("gate", "approval-state.json", expected, actual, "approval state hash changed"))
        gates = []
        for gate in raw_gates:
            required_gate_keys = {"gate_id", "trigger", "status", "source", "source_index", "risk_category"}
            if not isinstance(gate, dict) or not required_gate_keys <= set(gate):
                invalidators.append(hash_invalidator("gate", "approval-state.json", expected, actual, "approval state gate is malformed"))
                continue
            gate_id = gate["gate_id"]
            actual_gate = canonical_hash(gate)
            expected_gate = trusted_snapshots["gate_approval_hashes"].get(gate_id)
            if actual_gate != expected_gate:
                invalidators.append(hash_invalidator("gate", gate_id, expected_gate, actual_gate, "gate approval hash changed"))
            gates.append(gate)
        approval_state = {**approval_state, "gates": gates}
    clean_sections = anchored_status_sections(sentinel, invalidated=False)
    actual_sections = {
        "packet_statuses": old_status.get("packet_statuses"),
        "handoff_statuses": old_status.get("handoff_statuses"),
        "gate_statuses": old_status.get("gate_statuses"),
    }
    allowed_status_shapes = [clean_sections]
    if actual_sections not in allowed_status_shapes:
        for section, kind in [
            ("packet_statuses", "packet"),
            ("gate_statuses", "gate"),
            ("handoff_statuses", "handoff"),
        ]:
            actual_section = old_status.get(section)
            expected_section = clean_sections[section]
            if actual_section == expected_section:
                continue
            invalidators.append(
                hash_invalidator(
                    kind,
                    f"status.json.{section}",
                    canonical_hash(expected_section),
                    canonical_hash(actual_section),
                    f"status {section} changed",
                )
            )
    if run.get("compiler_version") != COMPILER_VERSION:
        invalidators.append(hash_invalidator("compiler", TOOL, run.get("compiler_version"), COMPILER_VERSION, "compiler version changed"))
    if trusted_snapshots.get("compiler_version") != COMPILER_VERSION:
        invalidators.append(
            hash_invalidator("compiler", "sentinel.snapshots.compiler_version", COMPILER_VERSION, trusted_snapshots.get("compiler_version"), "sentinel compiler version changed")
        )
    resume_state = "invalidated" if invalidators else "resumable"
    status_packet = packet
    if status_packet is None and expected_artifacts is not None:
        status_packet = expected_artifacts["packet"]
    if status_packet is None:
        status_packet = {"prompt_hash": "", "input_snapshot_hash": "", "prompt_path": prompt_rel}
    status_handoffs = handoff_schemas if handoff_schemas else (expected_artifacts["handoffs"] if expected_artifacts is not None else [])
    status_gates = gates if gates else (expected_artifacts["gates"] if expected_artifacts is not None else [])
    status_approval_state = approval_state if approval_state.get("gates") else (expected_artifacts["approval_state"] if expected_artifacts is not None else approval_state)
    status = build_status(
        run["run_id"],
        sentinel["plan_hash"],
        sentinel["source_plan_hash"],
        status_packet,
        status_handoffs,
        status_gates,
        status_approval_state,
        resume_state=resume_state,
        invalidators=invalidators,
        checked_at=now_utc(),
        resume_result=resume_state,
    )
    status["snapshots"] = copy.deepcopy(trusted_snapshots)
    status_sections = anchored_status_sections(sentinel, invalidated=bool(invalidators))
    status["packet_statuses"] = status_sections["packet_statuses"]
    status["handoff_statuses"] = status_sections["handoff_statuses"]
    status["gate_statuses"] = status_sections["gate_statuses"]
    write_json_atomic(status_path, status, root=run_dir)
    write_text_atomic(run_dir / "resume.md", render_resume(status, packet or (expected_artifacts["packet"] if expected_artifacts is not None else None)), root=run_dir)
    return status


def mutate_plan(base: dict[str, Any], mutation: dict[str, Any]) -> dict[str, Any]:
    plan = copy.deepcopy(base)
    plan["plan_id"] = mutation.get("plan_id", plan["plan_id"])
    risk = mutation.get("risk")
    if mutation.get("neutral_gate"):
        plan["risk_gates"] = [{"trigger": "manual approval boundary", "safe_default": "stop before writing and ask for approval", "requires_user_approval": True}]
    if risk:
        if not mutation.get("neutral_gate"):
            plan["risk_gates"] = [{"trigger": mutation.get("gate_trigger", risk), "safe_default": RISK_SAFE_DEFAULTS.get(risk, "stop before writing and ask for approval"), "requires_user_approval": True}]
        worker_permissions = plan["workers"][0]["tool_permissions"]
        if mutation.get("neutral_gate"):
            plan["execution_path"]["first_slice"]["forbidden_actions"] = [mutation.get("risk_token", risk)]
        elif risk == "write":
            worker_permissions["write"] = True
        elif risk == "shell-process":
            worker_permissions["shell"] = True
        elif risk == "network":
            worker_permissions["network"] = True
        elif risk == "external-message":
            worker_permissions["mcp_connectors"] = ["github"]
        else:
            plan["execution_path"]["first_slice"]["forbidden_actions"] = [mutation.get("risk_token", risk)]
    if "gate_trigger" in mutation and not risk:
        plan["risk_gates"][0]["trigger"] = mutation["gate_trigger"]
    if "instruction" in mutation:
        plan["execution_path"]["first_slice"]["instruction"] = mutation["instruction"]
    if "expected_output" in mutation:
        plan["execution_path"]["first_slice"]["expected_output"] = mutation["expected_output"]
    if "completion_check" in mutation:
        plan["execution_path"]["first_slice"]["completion_check"] = mutation["completion_check"]
    if "forbidden_actions" in mutation:
        plan["execution_path"]["first_slice"]["forbidden_actions"] = mutation["forbidden_actions"]
    if "inputs" in mutation:
        plan["execution_path"]["first_slice"]["inputs"] = mutation["inputs"]
    if mutation.get("surface_write"):
        plan["surfaces"][0]["access_mode"] = "write-proposed"
    return plan


def write_fixture_plan(temp_root: Path, fixture: dict[str, Any]) -> Path:
    plan_path = ROOT / fixture["plan"]
    plan = read_json(plan_path)
    if fixture.get("mutation"):
        plan = mutate_plan(plan, fixture["mutation"])
        mutated_path = temp_root / f"{fixture['id']}.workflow.plan.json"
        write_json_atomic(mutated_path, plan, root=temp_root)
        if fixture.get("input_symlink_parent"):
            symlink_target = temp_root / f"{fixture['id']}-input-target"
            symlink_target.mkdir(exist_ok=True)
            symlink_path = temp_root / fixture["input_symlink_parent"]
            if not symlink_path.exists():
                symlink_path.symlink_to(symlink_target, target_is_directory=True)
        for entry in fixture.get("input_files", []):
            input_path = safe_descendant_path(temp_root, entry["path"], message="fixture input path escapes fixture plan directory")
            write_text_atomic(input_path, entry["content"], root=temp_root)
        return mutated_path
    return plan_path


def validate_fixture_id(fixture_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", fixture_id) or fixture_id in {".", ".."}:
        raise CompileError("ERR_OUT_PATH_UNSAFE", "fixture ID must be one safe path segment", fixture_id=fixture_id)


def fixture_run_dir(suite_dir: Path, fixture_id: str) -> Path:
    validate_fixture_id(fixture_id)
    path = (suite_dir / fixture_id).resolve(strict=False)
    try:
        path.relative_to(suite_dir.resolve(strict=False))
    except ValueError as exc:
        raise CompileError("ERR_OUT_PATH_UNSAFE", "fixture output escapes suite directory", fixture_id=fixture_id) from exc
    return path


def validate_generated_artifacts(result: dict[str, Any]) -> None:
    out_dir = result["out_dir"]
    packet = result["packet"]
    status = result["status"]
    gates = result["gates"]
    handoffs = result["handoffs"]
    expected_files = {
        SENTINEL,
        "README.md",
        "run.json",
        "status.json",
        "resume.md",
        "plan.snapshot.json",
        "plan.sha256",
        "packets/001-first-slice.packet.json",
        "packets/001-first-slice.prompt.md",
        "gates/approval-state.json",
        "context/phases.json",
        "context/workers.json",
        "context/parallelism.json",
    }
    expected_files.update(f"handoffs/{item['handoff_id']}.schema.json" for item in handoffs)
    expected_files.update(f"gates/{gate['gate_id']}.approval.md" for gate in gates)
    actual_files = {
        path.relative_to(out_dir).as_posix()
        for path in out_dir.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_files != expected_files:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", f"generated file set mismatch: {sorted(actual_files ^ expected_files)}")
    packet_path = out_dir / "packets" / "001-first-slice.packet.json"
    prompt_path = out_dir / "packets" / "001-first-slice.prompt.md"
    approval_path = out_dir / "gates" / "approval-state.json"
    disk_packet = json.loads(packet_path.read_text())
    disk_prompt = prompt_path.read_text()
    disk_status = json.loads((out_dir / "status.json").read_text())
    approval_state = json.loads(approval_path.read_text())
    if disk_status != status:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "disk status does not match compiler status")
    verify_prompt_packet(disk_prompt, disk_packet, gates)
    snapshots = status["snapshots"]
    packet_hash = canonical_hash(disk_packet)
    prompt_hash = sha256_text(disk_prompt)
    input_hash = input_snapshot_hash(disk_packet["input_snapshots"])
    gate_hash = gate_snapshot_hash(gates)
    packet_status = status["packet_statuses"][0]
    if packet_hash != snapshots["packet_hashes"][PACKET_ID]:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "packet hash snapshot mismatch")
    if packet_status["packet_hash"] != packet_hash:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "packet status packet hash mismatch")
    if prompt_hash != snapshots["prompt_hashes"]["packets/001-first-slice.prompt.md"]:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "prompt hash snapshot mismatch")
    if packet_status["prompt_hash"] != prompt_hash:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "packet status prompt hash mismatch")
    if input_hash != snapshots["input_snapshot_hashes"][PACKET_ID]:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "input hash snapshot mismatch")
    if packet_status["input_snapshot_hash"] != input_hash:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "packet status input hash mismatch")
    if packet_status["gate_snapshot_hash"] != gate_hash:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "packet status gate hash mismatch")
    if canonical_hash(approval_state) != snapshots["approval_state_hash"]:
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "approval state hash snapshot mismatch")
    for handoff in handoffs:
        path = out_dir / "handoffs" / f"{handoff['handoff_id']}.schema.json"
        if canonical_hash(json.loads(path.read_text())) != snapshots["handoff_schema_hashes"][handoff["handoff_id"]]:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "handoff schema hash snapshot mismatch")
    for gate in gates:
        if canonical_hash(gate) != snapshots["gate_approval_hashes"][gate["gate_id"]]:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "gate approval hash snapshot mismatch")
    for rel_path, expected in result["contexts"].items():
        actual = json.loads((out_dir / rel_path).read_text())
        if canonical_hash(actual) != canonical_hash(expected):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", f"context artifact hash mismatch: {rel_path}")


def invalidator_signature(record: dict[str, Any]) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    for key in ["code", "kind", "id", "message"]:
        value = record.get(key)
        if not isinstance(value, str):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", f"invalidator missing string key: {key}")
        signature[key] = value
    for key in ["expected_hash", "actual_hash"]:
        value = record.get(key)
        if value is None:
            signature[key] = None
        elif isinstance(value, str):
            signature[key] = value
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", f"invalidator {key} is not a string or null")
    return signature


def restore_bytes(path: Path, before: bytes | None) -> None:
    if before is None:
        if path.exists() or path.is_symlink():
            path.unlink()
    else:
        path.write_bytes(before)


def expected_resume_signatures(fixture: dict[str, Any], plan_path: Path, run_dir: Path) -> list[dict[str, Any]]:
    scratch = run_dir.parent / f".{run_dir.name}.expected-{os.getpid()}-{sha8(fixture['id'])}"
    watched_paths = [plan_path, plan_path.parent / "live-input.txt"]
    before = {path: path.read_bytes() if path.exists() and not path.is_symlink() else None for path in watched_paths}
    try:
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.copytree(run_dir, scratch, symlinks=True)
        mutate_run_artifact(scratch, plan_path, fixture["mutate_artifact"])
        status = resume_run(scratch)
        return [invalidator_signature(item) for item in status["invalidators"]]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        for watched_path, content in before.items():
            restore_bytes(watched_path, content)


def check_fixture_result(fixture: dict[str, Any], result: dict[str, Any]) -> None:
    validate_generated_artifacts(result)
    status = result["status"]["packet_statuses"][0]["status"]
    expected_status = fixture.get("expected_status")
    if expected_status and status != expected_status:
        raise CompileError("ERR_RISK_GATE_BLOCKED", f"expected packet status {expected_status}, got {status}", fixture_id=fixture["id"])
    expected_categories = fixture.get("expected_blocked_categories", [])
    actual_categories = [gate["risk_category"] for gate in result["gates"] if gate["status"] == "blocked"]
    if expected_categories and actual_categories != expected_categories:
        raise CompileError("ERR_RISK_GATE_BLOCKED", f"blocked categories mismatch: {actual_categories}", fixture_id=fixture["id"])
    synthetic = [gate for gate in result["gates"] if gate["source"] == "compiler-synthetic"]
    if "expected_synthetic_count" in fixture and len(synthetic) != fixture["expected_synthetic_count"]:
        raise CompileError("ERR_RISK_GATE_BLOCKED", f"synthetic gate count mismatch: {len(synthetic)}", fixture_id=fixture["id"])
    if fixture.get("check_duplicate_inputs"):
        ids = [item["input_id"] for item in result["packet"]["input_snapshots"]]
        if len(ids) != len(set(ids)):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "duplicate input IDs were not distinct", fixture_id=fixture["id"])


def run_fixture(fixture: dict[str, Any], suite_dir: Path, temp_root: Path, *, suite_id: str | None = None) -> dict[str, Any]:
    fixture_id = fixture["id"]
    suite_label = suite_id or suite_dir.name
    try:
        fixture_type = fixture["type"]
        if fixture_type == "compile":
            plan_path = write_fixture_plan(temp_root, fixture)
            result = compile_plan(plan_path, fixture_run_dir(suite_dir, fixture_id), run_id=f"{suite_label}/{fixture_id}", mode="fixture")
            check_fixture_result(fixture, result)
        elif fixture_type == "error":
            try:
                plan_path = write_fixture_plan(temp_root, fixture)
                out = Path(fixture.get("out_override", fixture_run_dir(suite_dir, fixture_id)))
                if fixture.get("make_symlink"):
                    target = suite_dir / f"{fixture_id}-target"
                    target.mkdir(parents=True, exist_ok=True)
                    link = suite_dir / f"{fixture_id}-link"
                    if not link.exists():
                        link.symlink_to(target, target_is_directory=True)
                    out = link / "run"
                compile_plan(plan_path, out, run_id=f"{suite_label}/{fixture_id}", mode="fixture")
            except CompileError as exc:
                if exc.code != fixture["expected_error"]:
                    raise CompileError("ERR_SELF_TEST_WRONG_REASON", f"expected {fixture['expected_error']}, got {exc.code}", fixture_id=fixture_id) from exc
            else:
                raise CompileError(fixture["expected_error"], "expected fixture failure did not occur", fixture_id=fixture_id)
        elif fixture_type == "drift":
            plan_path = write_fixture_plan(temp_root, fixture)
            result = compile_plan(plan_path, fixture_run_dir(suite_dir, fixture_id), run_id=f"{suite_label}/{fixture_id}", mode="fixture")
            prompt = render_prompt(result["packet"], result["gates"]).replace(result["packet"]["objective"], "changed objective", 1)
            try:
                verify_prompt_packet(prompt, result["packet"], result["gates"])
            except CompileError as exc:
                if exc.code != fixture["expected_error"]:
                    raise
            else:
                raise CompileError("ERR_PROMPT_PACKET_DRIFT", "prompt drift was not detected", fixture_id=fixture_id)
        elif fixture_type == "resume":
            plan_path = write_fixture_plan(temp_root, fixture)
            result = compile_plan(plan_path, fixture_run_dir(suite_dir, fixture_id), run_id=f"{suite_label}/{fixture_id}", mode="fixture")
            run_dir = result["out_dir"]
            expected_signatures = (
                expected_resume_signatures(fixture, plan_path, run_dir)
                if "expected_error" not in fixture and "expected_resume_state" not in fixture
                else []
            )
            mutate_run_artifact(run_dir, plan_path, fixture["mutate_artifact"])
            try:
                status = resume_run(run_dir)
            except CompileError as exc:
                if fixture.get("expected_error") == exc.code:
                    return {"id": fixture_id, "status": "passed"}
                raise
            if "expected_resume_state" in fixture:
                if status["resume_state"] != fixture["expected_resume_state"]:
                    raise CompileError("ERR_SELF_TEST_WRONG_REASON", f"expected resume state {fixture['expected_resume_state']}, got {status['resume_state']}", fixture_id=fixture_id)
                return {"id": fixture_id, "status": "passed"}
            actual_signatures = [invalidator_signature(item) for item in status["invalidators"]]
            if actual_signatures != expected_signatures:
                raise CompileError(
                    "ERR_SELF_TEST_WRONG_REASON",
                    f"expected resume invalidators {expected_signatures}, got {actual_signatures}",
                    fixture_id=fixture_id,
                )
            actual_codes = [item["code"] for item in actual_signatures]
            if "expected_invalidators" in fixture:
                declared_codes = fixture["expected_invalidators"]
            else:
                declared_codes = [fixture["expected_invalidator"]]
            if actual_codes != declared_codes:
                raise CompileError(
                    "ERR_SELF_TEST_WRONG_REASON",
                    f"manifest expected resume invalidators {declared_codes}, got {actual_codes}",
                    fixture_id=fixture_id,
                )
        elif fixture_type == "resume-repair":
            plan_path = write_fixture_plan(temp_root, fixture)
            result = compile_plan(plan_path, fixture_run_dir(suite_dir, fixture_id), run_id=f"{suite_label}/{fixture_id}", mode="fixture")
            run_dir = result["out_dir"]
            prompt_path = run_dir / "packets" / "001-first-slice.prompt.md"
            original_prompt = prompt_path.read_text()
            mutate_run_artifact(run_dir, plan_path, fixture["mutate_artifact"])
            first_status = resume_run(run_dir)
            if first_status["resume_state"] != "invalidated":
                raise CompileError("ERR_SELF_TEST_WRONG_REASON", "first repair resume did not invalidate", fixture_id=fixture_id)
            write_text_atomic(prompt_path, original_prompt, root=run_dir)
            second_status = resume_run(run_dir)
            if second_status["resume_state"] != fixture["expected_resume_state"]:
                raise CompileError(
                    "ERR_SELF_TEST_WRONG_REASON",
                    f"expected repaired resume state {fixture['expected_resume_state']}, got {second_status['resume_state']}",
                    fixture_id=fixture_id,
                )
        else:
            raise CompileError("ERR_PLAN_INVALID", f"unknown fixture type: {fixture_type}", fixture_id=fixture_id)
    except CompileError as exc:
        exc.fixture_id = exc.fixture_id or fixture_id
        return {"id": fixture_id, "status": "failed", "error": exc.to_record()}
    return {"id": fixture_id, "status": "passed"}


def mutate_run_artifact(run_dir: Path, plan_path: Path, mutation: str) -> None:
    if mutation == "none":
        return
    if mutation == "source_plan":
        plan = read_json(plan_path)
        plan["objective"] += " changed"
        write_json_atomic(plan_path, plan)
    elif mutation == "plan_snapshot":
        path = run_dir / "plan.snapshot.json"
        data = json.loads(path.read_text())
        data["objective"] += " changed"
        write_json_atomic(path, data)
    elif mutation == "packet":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        data = json.loads(path.read_text())
        data["objective"] += " changed"
        write_json_atomic(path, data)
    elif mutation == "packet_status_rehash":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        data = json.loads(path.read_text())
        data["objective"] += " changed"
        write_json_atomic(path, data)
        status_path = run_dir / "status.json"
        status = json.loads(status_path.read_text())
        status["snapshots"]["packet_hashes"][PACKET_ID] = canonical_hash(data)
        write_json_atomic(status_path, status)
    elif mutation == "packet_prompt_hash_rehash":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        data = json.loads(path.read_text())
        data["prompt_hash"] = "0" * 64
        write_json_atomic(path, data)
        status_path = run_dir / "status.json"
        status = json.loads(status_path.read_text())
        status["snapshots"]["packet_hashes"][PACKET_ID] = canonical_hash(data)
        write_json_atomic(status_path, status)
    elif mutation == "packet_prompt_path_rehash":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        data = json.loads(path.read_text())
        data["prompt_path"] = "packets/alternate.prompt.md"
        write_json_atomic(path, data)
        status_path = run_dir / "status.json"
        status = json.loads(status_path.read_text())
        status["snapshots"]["packet_hashes"][PACKET_ID] = canonical_hash(data)
        write_json_atomic(status_path, status)
    elif mutation == "coherent_packet_prompt_status":
        packet_path = run_dir / "packets" / "001-first-slice.packet.json"
        prompt_path = run_dir / "packets" / "001-first-slice.prompt.md"
        approval_state = json.loads((run_dir / "gates" / "approval-state.json").read_text())
        packet = json.loads(packet_path.read_text())
        packet["objective"] += " forged"
        packet["prompt_hash"] = "0" * 64
        prompt = render_prompt(packet, approval_state["gates"])
        packet["prompt_hash"] = sha256_text(prompt)
        prompt = render_prompt(packet, approval_state["gates"])
        write_json_atomic(packet_path, packet)
        write_text_atomic(prompt_path, prompt)
        status_path = run_dir / "status.json"
        status = json.loads(status_path.read_text())
        status["snapshots"]["packet_hashes"][PACKET_ID] = canonical_hash(packet)
        status["snapshots"]["prompt_hashes"][packet["prompt_path"]] = sha256_text(prompt)
        status["packet_statuses"][0]["packet_hash"] = canonical_hash(packet)
        status["packet_statuses"][0]["prompt_hash"] = sha256_text(prompt)
        write_json_atomic(status_path, status)
    elif mutation == "malformed_packet":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        write_text_atomic(path, "{not-json\n")
    elif mutation == "packet_array":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        write_text_atomic(path, "[]\n")
    elif mutation == "packet_malformed_inputs":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        data = json.loads(path.read_text())
        data["input_snapshots"] = [{"input_id": "input-0000-malformed"}]
        write_json_atomic(path, data)
    elif mutation == "plan_snapshot_null":
        path = run_dir / "plan.snapshot.json"
        write_text_atomic(path, "null\n")
    elif mutation == "prompt":
        path = run_dir / "packets" / "001-first-slice.prompt.md"
        write_text_atomic(path, path.read_text() + "\nchanged\n")
    elif mutation == "input":
        path = run_dir / "packets" / "001-first-slice.packet.json"
        data = json.loads(path.read_text())
        data["input_snapshots"][0]["normalized_value"] += " changed"
        write_json_atomic(path, data)
    elif mutation == "gate":
        path = run_dir / "gates" / "approval-state.json"
        data = json.loads(path.read_text())
        data["gates"][0]["approved"] = True
        write_json_atomic(path, data)
    elif mutation == "gate_empty_object":
        path = run_dir / "gates" / "approval-state.json"
        write_json_atomic(path, {})
    elif mutation == "status_plan_hash":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["plan_hash"] = "0" * 64
        data["source_plan_hash"] = "1" * 64
        write_json_atomic(path, data)
    elif mutation == "status_packet_status":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["packet_statuses"][0]["status"] = "forged"
        write_json_atomic(path, data)
    elif mutation == "status_gate_status":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["gate_statuses"].append({"gate_id": "forged", "status": "ready"})
        write_json_atomic(path, data)
    elif mutation == "status_run_id":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["run_id"] = "forged-run-id"
        write_json_atomic(path, data)
    elif mutation == "status_snapshot_compiler":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["snapshots"]["compiler_version"] = "0.0.0-forged"
        write_json_atomic(path, data)
    elif mutation == "status_forged_previous_invalidated":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["resume_state"] = "invalidated"
        data["last_resume_result"] = "invalidated"
        data["invalidators"] = [
            hash_invalidator(
                "prompt",
                "packets/001-first-slice.prompt.md",
                "0" * 64,
                "1" * 64,
                "forged prior invalidator",
            )
        ]
        data["packet_statuses"][0]["status"] = "forged"
        write_json_atomic(path, data)
    elif mutation == "status_hybrid_previous_invalidated":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["resume_state"] = "invalidated"
        data["last_resume_result"] = "invalidated"
        data["invalidators"] = [
            hash_invalidator(
                "prompt",
                "packets/001-first-slice.prompt.md",
                "0" * 64,
                "1" * 64,
                "forged prior invalidator",
            )
        ]
        data["packet_statuses"][0]["status"] = "invalidated"
        data["packet_statuses"][0]["reason"] = "resume invalidated"
        write_json_atomic(path, data)
    elif mutation == "status_full_previous_invalidated":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        sentinel = json.loads((run_dir / SENTINEL).read_text())
        sections = anchored_status_sections(sentinel, invalidated=True)
        data["resume_state"] = "invalidated"
        data["last_resume_result"] = "invalidated"
        data["invalidators"] = [
            hash_invalidator(
                "prompt",
                "packets/001-first-slice.prompt.md",
                "0" * 64,
                "1" * 64,
                "forged prior invalidator",
            )
        ]
        data["packet_statuses"] = sections["packet_statuses"]
        data["handoff_statuses"] = sections["handoff_statuses"]
        data["gate_statuses"] = sections["gate_statuses"]
        write_json_atomic(path, data)
    elif mutation == "gate_status_rehash":
        approval_path = run_dir / "gates" / "approval-state.json"
        approval_state = json.loads(approval_path.read_text())
        approval_state["gates"][0]["status"] = "ready"
        approval_state["gates"][0]["approved"] = True
        write_json_atomic(approval_path, approval_state)
        status_path = run_dir / "status.json"
        status = json.loads(status_path.read_text())
        status["snapshots"]["approval_state_hash"] = canonical_hash(approval_state)
        status["snapshots"]["gate_approval_hashes"] = {gate["gate_id"]: canonical_hash(gate) for gate in approval_state["gates"]}
        status["gate_statuses"] = [
            {
                "gate_id": gate["gate_id"],
                "trigger": gate["trigger"],
                "status": gate["status"],
                "approval_hash": canonical_hash(gate),
                "source": gate["source"],
                "source_index": gate["source_index"],
                "risk_category": gate["risk_category"],
            }
            for gate in approval_state["gates"]
        ]
        write_json_atomic(status_path, status)
    elif mutation == "run_source_path_absolute":
        path = run_dir / "run.json"
        data = json.loads(path.read_text())
        data["source_plan_path"] = str((ROOT / "fixtures" / "v1" / "plans" / "ready-readonly.workflow.plan.json").resolve())
        write_json_atomic(path, data)
    elif mutation == "run_source_path_repo_relative_rehash":
        replacement = ROOT / "samples" / "v0.5" / "candidates" / "pos-cross-source-research.workflow.plan.json"
        replacement_plan = read_json(replacement)
        replacement_hash = canonical_hash(replacement_plan)
        path = run_dir / "run.json"
        data = json.loads(path.read_text())
        data["source_plan_path"] = rel(replacement)
        data["source_plan_hash"] = replacement_hash
        data["plan_hash"] = replacement_hash
        write_json_atomic(path, data)
        status_path = run_dir / "status.json"
        status = json.loads(status_path.read_text())
        status["source_plan_hash"] = replacement_hash
        status["plan_hash"] = replacement_hash
        status["snapshots"]["plan_hash"] = replacement_hash
        write_json_atomic(status_path, status)
    elif mutation == "status_handoff_traversal":
        path = run_dir / "status.json"
        data = json.loads(path.read_text())
        data["snapshots"]["handoff_schema_hashes"]["../../outside"] = "0" * 64
        write_json_atomic(path, data)
    elif mutation == "run_array":
        write_text_atomic(run_dir / "run.json", "[]\n")
    elif mutation == "status_array":
        write_text_atomic(run_dir / "status.json", "[]\n")
    elif mutation == "sentinel_array":
        write_text_atomic(run_dir / SENTINEL, "[]\n")
    elif mutation == "sentinel_missing_status_sections":
        path = run_dir / SENTINEL
        data = json.loads(path.read_text())
        data.pop("packet_statuses", None)
        write_json_atomic(path, data)
    elif mutation == "sentinel_malformed_status_sections":
        path = run_dir / SENTINEL
        data = json.loads(path.read_text())
        data["packet_statuses"] = [1]
        write_json_atomic(path, data)
    elif mutation == "sentinel_empty_status_object":
        path = run_dir / SENTINEL
        data = json.loads(path.read_text())
        data["packet_statuses"] = [{}]
        write_json_atomic(path, data)
    elif mutation == "sentinel_invalid_utf8":
        (run_dir / SENTINEL).write_bytes(b"\xff")
    elif mutation == "compiler":
        path = run_dir / "run.json"
        data = json.loads(path.read_text())
        data["compiler_version"] = "0.0.0-stale"
        write_json_atomic(path, data)
    elif mutation == "live_input":
        run = json.loads((run_dir / "run.json").read_text())
        source_plan = run_source_path(run["source_plan_path"])
        write_text_atomic(source_plan.parent / "live-input.txt", "changed\n")
    elif mutation == "approval_symlink":
        path = run_dir / "gates" / "approval-state.json"
        path.unlink()
        path.symlink_to(run_dir / "run.json")
    elif mutation == "packets_dir_symlink":
        original = run_dir / "packets"
        target = run_dir.parent / f"{run_dir.name}-packets-target"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(original, target)
        shutil.rmtree(original)
        original.symlink_to(target, target_is_directory=True)
    elif mutation == "missing_handoff":
        handoffs = sorted((run_dir / "handoffs").glob("*.schema.json"))
        handoffs[0].unlink()


def evaluate_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    suite_id = Path(out_dir).name
    suite_dir = resolve_v1_out(out_dir)
    ensure_safe_artifact_parent(OUT_ROOT, suite_dir.parent / ".publish")
    ensure_replaceable_run_dir(suite_dir, suite_id, "manifest")
    staging = Path(tempfile.mkdtemp(prefix=f".{suite_id}.manifest.", dir=suite_dir.parent))
    write_json_atomic(staging / SENTINEL, sentinel_payload(suite_id, "manifest"), root=staging)
    required = manifest["required_fixture_ids"]
    fixtures = manifest["fixtures"]
    fixture_ids = [fixture["id"] for fixture in fixtures]
    duplicate = sorted({item for item in fixture_ids if fixture_ids.count(item) > 1})
    duplicate_occurrences = [item for item in fixture_ids if item in set(duplicate)]
    failures = []
    passed = 0
    passed_required: set[str] = set()
    invalid_fixture_ids: set[str] = set()
    for fixture_id in fixture_ids:
        try:
            validate_fixture_id(fixture_id)
        except CompileError as exc:
            failures.append(exc.to_record())
            invalid_fixture_ids.add(fixture_id)
    required_duplicates = sorted({item for item in required if required.count(item) > 1})
    required_invalid: set[str] = set()
    for fixture_id in required:
        try:
            validate_fixture_id(fixture_id)
        except CompileError as exc:
            failures.append(exc.to_record())
            required_invalid.add(fixture_id)
    temp_root = staging / "_fixture-plans"
    temp_root.mkdir(parents=True, exist_ok=True)
    for fixture in fixtures:
        if fixture["id"] in invalid_fixture_ids or fixture["id"] in duplicate:
            continue
        result = run_fixture(fixture, staging, temp_root, suite_id=suite_id)
        if result["status"] == "passed":
            passed += 1
            if fixture["id"] in required:
                passed_required.add(fixture["id"])
        else:
            failures.append(result["error"])
    missing = sorted(set(required) - set(fixture_ids))
    for fixture_id in missing:
        failures.append({"code": "ERR_PLAN_INVALID", "message": "required fixture missing", "fixture_id": fixture_id})
    for fixture_id in duplicate_occurrences:
        failures.append({"code": "ERR_PLAN_INVALID", "message": "duplicate fixture ID", "fixture_id": fixture_id})
    for fixture_id in required_duplicates:
        failures.append({"code": "ERR_PLAN_INVALID", "message": "duplicate required fixture ID", "fixture_id": fixture_id})
    skipped_required = set(required) - set(fixture_ids)
    skipped_required.update(set(required) & invalid_fixture_ids)
    skipped_required.update(set(required) & set(duplicate))
    skipped = len(skipped_required)
    required_set = set(required)
    required_failures = [
        failure
        for failure in failures
        if failure.get("fixture_id") in required_set or failure.get("fixture_id") in required_invalid
    ]
    failed = len(failures)
    required_kept = (
        skipped == 0
        and not invalid_fixture_ids
        and not required_duplicates
        and not duplicate
        and not required_invalid
        and required_set <= passed_required
        and not required_failures
    )
    summary = {
        "suite_id": suite_id,
        "fixture_count": len(fixtures),
        "required_fixture_count": len(required),
        "required_passed": len(passed_required),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "decision": "keep" if required_kept else "kill",
        "failures": failures,
    }
    write_json_atomic(staging / "summary.json", summary, root=staging)
    if summary["decision"] == "keep" or not suite_dir.exists():
        publish_owned_tree(staging, suite_dir, suite_id, "manifest")
    if summary["decision"] != "keep":
        shutil.rmtree(staging, ignore_errors=True)
        raise CompileError("ERR_PLAN_INVALID", "manifest decision is kill", path=manifest_path)
    return summary


def self_test() -> None:
    manifest = ROOT / "fixtures" / "v1" / "manifest.json"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compile-workflow-self-test-", dir=OUT_ROOT) as tmp:
        tmp_path = Path(tmp)
        out = tmp_path / "self-test"
        summary = evaluate_manifest(manifest, out)
        base_manifest = read_json(manifest)
        fixtures = {fixture["id"]: fixture for fixture in base_manifest["fixtures"]}
        optional_failure_manifest = {
            "suite_id": "optional-failure",
            "fixtures": [
                fixtures["positive-ready-readonly"],
                {**fixtures["positive-repo-migration"], "expected_status": "blocked-risk-gate"},
            ],
            "required_fixture_ids": ["positive-ready-readonly"],
        }
        optional_manifest_path = tmp_path / "optional-failure-manifest.json"
        write_json_atomic(optional_manifest_path, optional_failure_manifest)
        optional_summary = evaluate_manifest(optional_manifest_path, tmp_path / "optional-failure")
        if (
            optional_summary["decision"] != "keep"
            or optional_summary["fixture_count"] != 2
            or optional_summary["required_fixture_count"] != 1
            or optional_summary["required_passed"] != 1
            or optional_summary["passed"] != 1
            or optional_summary["failed"] != 1
        ):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "optional fixture failure changed required keep decision")
        preserved_out = tmp_path / "preserve-on-kill"
        preserved_summary = evaluate_manifest(optional_manifest_path, preserved_out)
        preserving_kill_manifest = {
            "suite_id": "preserve-on-kill",
            "fixtures": [
                {**fixtures["positive-ready-readonly"], "id": "preserve-duplicate"},
                {**fixtures["positive-ready-readonly"], "id": "preserve-duplicate"},
            ],
            "required_fixture_ids": ["preserve-duplicate"],
        }
        preserving_kill_path = tmp_path / "preserving-kill-manifest.json"
        write_json_atomic(preserving_kill_path, preserving_kill_manifest)
        try:
            evaluate_manifest(preserving_kill_path, preserved_out)
        except CompileError as exc:
            if exc.code != "ERR_PLAN_INVALID":
                raise
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "kill manifest unexpectedly replaced preserved suite")
        if json.loads((preserved_out / "summary.json").read_text()) != preserved_summary:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "kill manifest replaced previous published summary")
        duplicate_optional_manifest = {
            "suite_id": "duplicate-optional",
            "fixtures": [
                fixtures["positive-ready-readonly"],
                {**fixtures["positive-repo-migration"], "id": "duplicate-optional-fixture"},
                {**fixtures["positive-repo-migration"], "id": "duplicate-optional-fixture"},
            ],
            "required_fixture_ids": ["positive-ready-readonly"],
        }
        duplicate_optional_path = tmp_path / "duplicate-optional-manifest.json"
        duplicate_optional_out = tmp_path / "duplicate-optional"
        write_json_atomic(duplicate_optional_path, duplicate_optional_manifest)
        try:
            evaluate_manifest(duplicate_optional_path, duplicate_optional_out)
        except CompileError as exc:
            if exc.code != "ERR_PLAN_INVALID":
                raise
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "duplicate optional fixture ID did not kill manifest")
        duplicate_summary = json.loads((duplicate_optional_out / "summary.json").read_text())
        if (
            duplicate_summary["decision"] != "kill"
            or duplicate_summary["fixture_count"] != 3
            or duplicate_summary["passed"] != 1
            or duplicate_summary["failed"] != 2
            or duplicate_summary["required_passed"] != 1
            or duplicate_summary["skipped"] != 0
        ):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "duplicate optional fixture summary was not fatal and complete")
        with tempfile.TemporaryDirectory(prefix="compile-workflow-external-plan-") as external_tmp:
            external_plan = Path(external_tmp) / "external.workflow.plan.json"
            write_json_atomic(external_plan, read_json(ROOT / "fixtures" / "v1" / "plans" / "ready-readonly.workflow.plan.json"))
            try:
                compile_plan(external_plan, tmp_path / "external-plan", run_id="external-plan", mode="fixture")
            except CompileError as exc:
                if exc.code != "ERR_PLAN_INVALID":
                    raise
            else:
                raise CompileError("ERR_SELF_TEST_WRONG_REASON", "external plan path was not rejected")
        invalid_id_manifest = {
            "suite_id": "invalid-id",
            "fixtures": [fixtures["positive-ready-readonly"], {**fixtures["positive-repo-migration"], "id": "../escape"}],
            "required_fixture_ids": ["positive-ready-readonly"],
        }
        invalid_manifest_path = tmp_path / "invalid-id-manifest.json"
        invalid_out = tmp_path / "invalid-id"
        write_json_atomic(invalid_manifest_path, invalid_id_manifest)
        try:
            evaluate_manifest(invalid_manifest_path, invalid_out)
        except CompileError as exc:
            if exc.code != "ERR_PLAN_INVALID":
                raise
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "invalid fixture ID did not kill manifest")
        invalid_summary = json.loads((invalid_out / "summary.json").read_text())
        if invalid_summary["decision"] != "kill":
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "invalid fixture ID summary did not record kill")
        required_invalid_id_manifest = {
            "suite_id": "required-invalid-id",
            "fixtures": [fixtures["positive-ready-readonly"], {**fixtures["positive-repo-migration"], "id": "../escape"}],
            "required_fixture_ids": ["positive-ready-readonly", "../escape"],
        }
        required_invalid_path = tmp_path / "required-invalid-id-manifest.json"
        required_invalid_out = tmp_path / "required-invalid-id"
        write_json_atomic(required_invalid_path, required_invalid_id_manifest)
        try:
            evaluate_manifest(required_invalid_path, required_invalid_out)
        except CompileError as exc:
            if exc.code != "ERR_PLAN_INVALID":
                raise
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "required invalid fixture ID did not kill manifest")
        required_invalid_summary = json.loads((required_invalid_out / "summary.json").read_text())
        if (
            required_invalid_summary["decision"] != "kill"
            or required_invalid_summary["required_fixture_count"] != 2
            or required_invalid_summary["required_passed"] != 1
            or required_invalid_summary["passed"] != 1
            or required_invalid_summary["skipped"] != 1
        ):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "required invalid fixture summary did not count skipped required fixture")
        required_duplicate_manifest = {
            "suite_id": "required-duplicate",
            "fixtures": [
                {**fixtures["positive-ready-readonly"], "id": "required-duplicate-fixture"},
                {**fixtures["positive-ready-readonly"], "id": "required-duplicate-fixture"},
            ],
            "required_fixture_ids": ["required-duplicate-fixture"],
        }
        required_duplicate_path = tmp_path / "required-duplicate-manifest.json"
        required_duplicate_out = tmp_path / "required-duplicate"
        write_json_atomic(required_duplicate_path, required_duplicate_manifest)
        try:
            evaluate_manifest(required_duplicate_path, required_duplicate_out)
        except CompileError as exc:
            if exc.code != "ERR_PLAN_INVALID":
                raise
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "required duplicate fixture ID did not kill manifest")
        required_duplicate_summary = json.loads((required_duplicate_out / "summary.json").read_text())
        if (
            required_duplicate_summary["decision"] != "kill"
            or required_duplicate_summary["required_fixture_count"] != 1
            or required_duplicate_summary["required_passed"] != 0
            or required_duplicate_summary["passed"] != 0
            or required_duplicate_summary["skipped"] != 1
        ):
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "required duplicate fixture summary did not count skipped required fixture")
        symlink_root = tmp_path / "symlink-write"
        prepare_owned_dir(symlink_root, "symlink-write", "fixture", clear=True)
        symlink_target = symlink_root / "packets-target"
        symlink_target.mkdir()
        (symlink_root / "packets").symlink_to(symlink_target, target_is_directory=True)
        try:
            write_json_atomic(symlink_root / "packets" / "x.json", {}, root=symlink_root)
        except CompileError as exc:
            if exc.code != "ERR_OUT_PATH_SYMLINK":
                raise
        else:
            raise CompileError("ERR_SELF_TEST_WRONG_REASON", "symlinked artifact directory write passed")
    if summary["decision"] != "keep":
        raise CompileError("ERR_SELF_TEST_WRONG_REASON", "self-test manifest did not keep")
    print("compile_workflow self-test: pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan")
    parser.add_argument("--out")
    parser.add_argument("--mode", default="compile", choices=["compile"])
    parser.add_argument("--resume")
    parser.add_argument("--manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.manifest:
            if not args.out:
                raise CompileError("ERR_OUT_PATH_UNSAFE", "--manifest requires --out")
            summary = evaluate_manifest(Path(args.manifest), Path(args.out))
            print(canonical_json_text(summary))
        elif args.resume:
            status = resume_run(Path(args.resume))
            print(canonical_json_text({"resume_state": status["resume_state"], "invalidators": status["invalidators"]}))
            return 0 if status["resume_state"] == "resumable" else 1
        elif args.plan and args.out:
            result = compile_plan(Path(args.plan), Path(args.out), mode=args.mode)
            print(canonical_json_text({"run_id": result["run"]["run_id"], "status": result["status"]["packet_statuses"][0]["status"]}))
        else:
            parser.error("expected --self-test, --manifest, --resume, or --plan with --out")
    except CompileError as exc:
        print(canonical_json_text(exc.to_record()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
