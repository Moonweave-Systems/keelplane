"""Plan schema constants and validation, wrapping existing evaluate_plan.py logic.

During the migration phase, validation is delegated to the existing
scripts/evaluate_plan.py. Once migration is complete, the validation logic
will live here directly.
"""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from typing import Any, Callable

from depone.core.embedded_plan_contract import validate_embedded_contract


# Re-export schema constants from evaluate_plan.
# These are kept here so depone consumers don't need to import scripts/.
SCHEMA_VERSION = "0.5"
REQUIRED_PLAN_FIELDS = [
    "schema_version",
    "plan_id",
    "created_by",
    "source_prompt",
    "activation",
    "objective",
    "surfaces",
    "assumptions",
    "patterns",
    "phases",
    "workers",
    "handoffs",
    "parallelism",
    "verification",
    "risk_gates",
    "budget",
    "resume",
    "execution_path",
]


def load_plan(path: str | Path) -> dict[str, Any]:
    """Load a plan.json from disk."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Plan not found: {path}")
    with open(path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """Lightweight structural validation. Returns list of error messages.

    Checks key presence, schema version, activation decision, and surface
    kind. Does NOT run the strict evaluate_plan contract validation —
    templates and design-time plans typically fail those checks because
    they are intentionally incomplete. Use ``validate_plan_strict()`` for
    full contract validation of completed plans.
    """
    errors: list[str] = []

    # Key presence check
    for field in REQUIRED_PLAN_FIELDS:
        if field not in plan:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Schema version
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Expected schema_version={SCHEMA_VERSION!r}, got {plan.get('schema_version')!r}"
        )

    # Activation
    activation = plan.get("activation", {})
    if activation.get("decision") not in ("activate", "downgrade"):
        errors.append("activation.decision must be 'activate' or 'downgrade'")

    # Surface kinds
    for s in plan.get("surfaces", []):
        if s.get("kind") not in (
            "repo",
            "package",
            "artifact",
            "api",
            "data-source",
            "web-source",
            "document",
        ):
            errors.append(f"Invalid surface kind: {s.get('kind')}")

    return errors


def validate_plan_strict(plan: dict[str, Any]) -> list[str]:
    """Full contract validation delegating to evaluate_plan.validate_plan().

    Use this when validating a completed plan (e.g. via the ``validate``
    CLI command). Returns a list of error message strings.
    """
    errors = validate_plan(plan)
    if errors:
        return errors

    evaluator = _load_repo_evaluator()
    if evaluator is None:
        errors.extend(validate_embedded_contract(plan))
        return errors
    try:
        evaluator(plan)
    except ValueError as exc:
        errors.append(f"evaluate_plan validation: {exc}")

    return errors


def _load_repo_evaluator() -> Callable[[dict[str, Any]], None] | None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_plan.py"
    if not script_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        "_depone_evaluate_plan", script_path
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validate = getattr(module, "validate_plan")
    return validate


def format_errors(errors: list[str]) -> str:
    """Format validation errors as a human-readable string."""
    if not errors:
        return "Plan is valid."
    lines = [f"Plan validation failed: {len(errors)} error(s)"]
    for i, e in enumerate(errors, 1):
        lines.append(f"  {i}. {e}")
    return "\n".join(lines)
