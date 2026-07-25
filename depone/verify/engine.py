from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from depone.agent_fabric.capture_bridge import (
    ASSURANCE_A1,
    ASSURANCE_A2,
    CAPTURE_MANIFEST_KIND,
    validate_capture_manifest,
)
from depone.agent_fabric.observer_provenance import (
    validate_trusted_observer_provenance,
)
from depone.verify.adapters.base import EvidenceContext
from depone.verify.evidence_contract import (
    EvidenceContractEntry,
    _read_evidence_contract,
    _health_evidence_substrates,
    validate_advisory_provenance,
    validate_evidence_contract,
)


_ROLE_CAPABILITY_AXES = frozenset({"skill_routing", "tool_calls", "write_scope"})
_ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXIS_UNDECLARED = (
    "ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXIS_UNDECLARED"
)
_ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXES_INVALID = (
    "ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXES_INVALID"
)
_INVALID_EVIDENCE_CONTRACT_CODES = frozenset(
    {
        "ERR_EVIDENCE_CONTRACT_INVALID",
        "ERR_EVIDENCE_CONTRACT_MISSING",
        "ERR_EVIDENCE_CONTRACT_SHADOWED",
    }
)


@dataclass
class GateCheck:
    gate_id: str
    trigger: str
    complied: bool
    evidence_path: str | None = None


@dataclass
class HandoffCheck:
    artifact: str
    expected_hash: str
    actual_hash: str
    exists: bool
    hash_match: bool
    status: Literal["pass", "refuted", "insufficient-evidence"] = "pass"


@dataclass
class AdversarialCheck:
    claim: str
    refuted: bool
    refutation: str | None = None
    ground_truth_source: str = ""


@dataclass
class ClaimEvaluation:
    claim: str
    evaluator: str
    state: str  # supported | refuted | not-evaluated | stale | unsupported-evaluator
    required: bool = True
    detail: str | None = None
    ground_truth_source: str = ""
    advisory: bool = False


@dataclass
class BudgetCheck:
    within_limits: bool
    exceeded: list[str] = field(default_factory=list)


@dataclass
class PhaseVerdict:
    phase_id: str
    status: Literal["passed", "failed", "skipped"] = "skipped"
    gates: list[GateCheck] = field(default_factory=list)
    handoffs: list[HandoffCheck] = field(default_factory=list)
    adversarial: list[AdversarialCheck] = field(default_factory=list)
    budget: BudgetCheck = field(default_factory=BudgetCheck)


@dataclass
class AgentFabricCaptureCheck:
    evidence_path: str
    assurance: str
    decision: str
    valid: bool
    trusted_observer_provenance: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class ReviewSignal:
    evidence_path: str
    provider: str
    finding_count: int
    can_change_evidence_verdict: bool
    axis: str = "review"
    valid: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class RoleCapabilityConformance:
    axis: str
    status: Literal["pass", "fail"]
    evidence_path: str | None = None
    error_code: str | None = None


@dataclass
class PolicyAxisConformance:
    axis: str
    status: Literal["pass", "fail"]
    enforcement: Literal["block", "advisory"]
    blocks_handoff: bool
    error_code: str | None = None
    evidence_path: str | None = None


@dataclass
class PolicyConformance:
    overall: Literal["pass", "fail", "inconclusive"]
    axes: list[PolicyAxisConformance] = field(default_factory=list)


@dataclass
class HealthAxisConformance:
    gate: str
    tool: str
    status: Literal["pass", "fail"]
    enforcement: Literal["block", "advisory"]
    evidence_substrate: Literal["bound", "producer-transcribed"]
    means: str
    blocks_handoff: bool
    error_code: str | None = None
    evidence_path: str | None = None


@dataclass
class HealthConformance:
    overall: Literal["pass", "fail"]
    axes: list[HealthAxisConformance] = field(default_factory=list)


@dataclass
class VerificationReport:
    """Verification result.

    A1/A2 assurance is relative to the recorded trust anchor and does not by
    itself establish that the anchor is independent of the executor.
    """

    schema_version: str = "1.0"
    plan_hash: str = ""
    framework: str = "generic"
    run_id: str | None = None
    phases: list[PhaseVerdict] = field(default_factory=list)
    evidence_contract: list[EvidenceContractEntry] = field(default_factory=list)
    evidence_contract_schema_version: str | None = None
    advisory_findings: list[EvidenceContractEntry] = field(default_factory=list)
    decision: Literal["pass", "fail", "inconclusive"] = "pass"
    assurance: str = "A0-claims-only"
    signature_checked: bool = False
    trust_anchor: dict[str, str] | None = None
    agent_fabric_captures: list[AgentFabricCaptureCheck] = field(default_factory=list)
    claim_evaluations: list[ClaimEvaluation] = field(default_factory=list)
    review_signals: list[ReviewSignal] = field(default_factory=list)
    role_capability_conformance: list[RoleCapabilityConformance] = field(
        default_factory=list
    )
    policy_conformance: PolicyConformance | None = None
    health_conformance: HealthConformance | None = None
    verdict: Literal["verified", "refuted", "insufficient-evidence"] = "verified"


def _compute_plan_hash(plan: dict[str, Any]) -> str:
    raw = json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _role_capability_contract_axes(contract: dict[str, Any] | None) -> list[str]:
    if contract is None:
        return []
    axes: list[str] = []
    if isinstance(contract.get("role_capability_tool_calls"), dict):
        axes.append("tool_calls")
    if isinstance(contract.get("role_capability_write_scope"), dict):
        axes.append("write_scope")
    if isinstance(contract.get("role_capability_skill_routing"), dict):
        axes.append("skill_routing")
    return axes


def _is_advisory_skill_routing_entry(
    contract: dict[str, Any] | None,
    entry: EvidenceContractEntry,
) -> bool:
    if entry.code != "ERR_ROLE_CAPABILITY_SKILL_ROUTING_VIOLATION":
        return False
    if contract is None:
        return False
    directive = contract.get("role_capability_skill_routing")
    return isinstance(directive, dict) and directive.get("enforcement") == "advisory"


def _health_entry_matches_gate(
    entry: EvidenceContractEntry,
    gate: dict[str, Any],
) -> bool:
    return (
        entry.code == "ERR_HEALTH_GATE_VIOLATION"
        and gate.get("exit_code_path") == entry.evidence_path
        and entry.health_gate == {
            "gate": gate.get("gate"),
            "tool": gate.get("tool"),
            "enforcement": gate.get("enforcement"),
        }
    )


def _is_advisory_health_entry(
    contract: dict[str, Any] | None,
    entry: EvidenceContractEntry,
    health_substrates: dict[str, str] | None = None,
) -> bool:
    if entry.code != "ERR_HEALTH_GATE_VIOLATION" or contract is None:
        return False
    directive = contract.get("code_health")
    if not isinstance(directive, dict):
        return False
    gates = directive.get("gates")
    if not isinstance(gates, list):
        return False
    matching_gate = next(
        (
            gate
            for gate in gates
            if isinstance(gate, dict) and _health_entry_matches_gate(entry, gate)
        ),
        None,
    )
    if not matching_gate:
        return False
    if health_substrates is not None:
        gate_id = entry.health_gate.get("gate") if entry.health_gate else None
        if health_substrates.get(gate_id) == "producer-transcribed":
            return True
    return matching_gate.get("enforcement") == "advisory"


def _blocking_evidence_contract_entries(
    contract: dict[str, Any] | None,
    evidence_contract: list[EvidenceContractEntry],
    health_substrates: dict[str, str] | None = None,
) -> list[EvidenceContractEntry]:
    return [
        entry
        for entry in evidence_contract
        if not _is_advisory_skill_routing_entry(contract, entry)
        and not _is_advisory_health_entry(contract, entry, health_substrates)
    ]


def _validated_evidence_contract_schema_version(
    contract: dict[str, Any] | None,
    evidence_contract: list[EvidenceContractEntry],
) -> str | None:
    if contract is None or any(
        entry.code in _INVALID_EVIDENCE_CONTRACT_CODES
        for entry in evidence_contract
    ):
        return None
    schema_version = contract.get("schema_version")
    return schema_version if isinstance(schema_version, str) else None


def _plan_required_role_capability_axes(
    plan: dict[str, Any],
) -> tuple[list[str], bool]:
    if "required_role_capability_axes" not in plan:
        return [], False
    required = plan["required_role_capability_axes"]
    if not isinstance(required, list):
        return [], True
    invalid = any(
        not isinstance(axis, str) or axis not in _ROLE_CAPABILITY_AXES
        for axis in required
    )
    axes = [
        axis
        for axis in required
        if isinstance(axis, str) and axis in _ROLE_CAPABILITY_AXES
    ]
    return list(dict.fromkeys(axes)), invalid


def _role_capability_conformance(
    plan: dict[str, Any],
    contract: dict[str, Any] | None,
    evidence_contract: list[EvidenceContractEntry],
) -> list[RoleCapabilityConformance]:
    axes = _role_capability_contract_axes(contract)
    required_axes, required_axes_invalid = _plan_required_role_capability_axes(plan)
    if not axes and not required_axes and not required_axes_invalid:
        return []

    results: list[RoleCapabilityConformance] = []
    for axis in axes:
        if axis == "tool_calls":
            prefixes = ("ERR_ROLE_CAPABILITY_TOOL_",)
        elif axis == "write_scope":
            prefixes = (
                "ERR_ROLE_CAPABILITY_WRITE_SCOPE",
                "ERR_ROLE_CAPABILITY_OBSERVATION_",
            )
        else:
            prefixes = (
                "ERR_ROLE_CAPABILITY_SKILL_ROUTING_",
                "ERR_ROLE_CAPABILITY_OBSERVATION_",
            )
        failure = next(
            (
                entry
                for entry in evidence_contract
                if entry.code.startswith(prefixes)
                or entry.code.startswith("ERR_ROLE_CAPABILITY_RUN_INTENT_")
                or entry.code.startswith("ERR_ROLE_CAPABILITY_SIGNATURE_")
                or entry.code == "ERR_ROLE_CAPABILITY_TRUST_ANCHOR_MISSING"
                or entry.code == "ERR_EVIDENCE_CONTRACT_INVALID"
            ),
            None,
        )
        if failure is None:
            results.append(RoleCapabilityConformance(axis=axis, status="pass"))
            continue
        results.append(
            RoleCapabilityConformance(
                axis=axis,
                status="fail",
                evidence_path=failure.evidence_path,
                error_code=failure.code,
            )
        )
    for axis in required_axes:
        if axis in axes:
            continue
        results.append(
            RoleCapabilityConformance(
                axis=axis,
                status="fail",
                evidence_path="evidence-contract.json",
                error_code=_ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXIS_UNDECLARED,
            )
        )
    if required_axes_invalid:
        results.append(
            RoleCapabilityConformance(
                axis="required_role_capability_axes",
                status="fail",
                error_code=_ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXES_INVALID,
            )
        )
    return results


def _policy_conformance(
    role_capability_conformance: list[RoleCapabilityConformance],
    contract: dict[str, Any] | None,
) -> PolicyConformance | None:
    if not role_capability_conformance:
        return None

    axes: list[PolicyAxisConformance] = []
    for entry in role_capability_conformance:
        enforcement: Literal["block", "advisory"] = "block"
        if entry.axis == "skill_routing" and contract is not None:
            directive = contract.get("role_capability_skill_routing")
            if (
                isinstance(directive, dict)
                and directive.get("enforcement") == "advisory"
            ):
                enforcement = "advisory"
        advisory_violation = (
            entry.error_code == "ERR_ROLE_CAPABILITY_SKILL_ROUTING_VIOLATION"
            and enforcement == "advisory"
        )
        axes.append(
            PolicyAxisConformance(
                axis=entry.axis,
                status=entry.status,
                enforcement=enforcement,
                blocks_handoff=entry.status == "fail" and not advisory_violation,
                error_code=entry.error_code,
                evidence_path=entry.evidence_path,
            )
        )

    if any(
        axis.error_code
        in {
            _ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXIS_UNDECLARED,
            _ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXES_INVALID,
        }
        for axis in axes
    ):
        overall: Literal["pass", "fail", "inconclusive"] = "inconclusive"
    elif any(axis.status == "fail" for axis in axes):
        overall = "fail"
    else:
        overall = "pass"
    return PolicyConformance(overall=overall, axes=axes)


def _health_conformance(
    contract: dict[str, Any] | None,
    evidence_contract: list[EvidenceContractEntry],
    health_substrates: dict[str, str] | None = None,
) -> HealthConformance | None:
    if contract is None:
        return None
    directive = contract.get("code_health")
    if not isinstance(directive, dict):
        return None
    gates = directive.get("gates")
    if not isinstance(gates, list):
        return None

    axes: list[HealthAxisConformance] = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        gate_id = gate.get("gate")
        tool = gate.get("tool")
        enforcement = gate.get("enforcement")
        exit_code_path = gate.get("exit_code_path")
        if (
            not isinstance(gate_id, str)
            or not isinstance(tool, str)
            or enforcement not in {"block", "advisory"}
            or not isinstance(exit_code_path, str)
        ):
            continue
        failure = next(
            (
                entry
                for entry in evidence_contract
                if _health_entry_matches_gate(entry, gate)
            ),
            None,
        )
        status: Literal["pass", "fail"] = "fail" if failure else "pass"
        substrate: Literal["bound", "producer-transcribed"] = (
            "bound"
            if health_substrates is not None
            and health_substrates.get(gate_id) == "bound"
            else "producer-transcribed"
        )
        axes.append(
            HealthAxisConformance(
                gate=gate_id,
                tool=tool,
                status=status,
                enforcement=enforcement,
                evidence_substrate=substrate,
                means=(
                    "bundle-subject-verified gate artifacts"
                    if substrate == "bound"
                    else "producer-reported exit code; not bundle-bound"
                ),
                blocks_handoff=(
                    status == "fail"
                    and enforcement == "block"
                    and substrate == "bound"
                ),
                error_code=failure.code if failure else None,
                evidence_path=failure.evidence_path if failure else None,
            )
        )

    overall: Literal["pass", "fail"] = (
        "fail" if any(axis.status == "fail" for axis in axes) else "pass"
    )
    return HealthConformance(overall=overall, axes=axes)


def _resolve_handoff_path(
    handoff: dict[str, Any],
    evidence_map: dict[str, Any],
) -> str | None:
    """Resolve a handoff to an evidence file path.

    Priority: (a) explicit ``evidence_path``; (b) ``artifact`` if it is a
    path that exists in the evidence directory.  Returns ``None`` when no
    evidence file can be matched.
    """
    path = handoff.get("evidence_path")
    if path and path in evidence_map:
        return path
    candidate = handoff.get("artifact", "")
    if candidate in evidence_map:
        return candidate
    return None


def check_gate_compliance(
    plan: dict[str, Any], evidence: EvidenceContext
) -> list[GateCheck]:
    results: list[GateCheck] = []
    risk_gates = plan.get("risk_gates", [])
    if not risk_gates:
        return results
    known_files = {f.path for f in evidence.files}
    for gate in risk_gates:
        gid = gate.get("trigger", "unknown")
        approval_path = f"gates/{gid}/approved"
        denial_path = f"gates/{gid}/denied"
        if approval_path in known_files:
            results.append(
                GateCheck(
                    gate_id=gid, trigger=gid, complied=True, evidence_path=approval_path
                )
            )
        elif denial_path in known_files:
            results.append(
                GateCheck(
                    gate_id=gid, trigger=gid, complied=False, evidence_path=denial_path
                )
            )
        else:
            results.append(GateCheck(gate_id=gid, trigger=gid, complied=False))
    return results


def check_handoff_integrity(
    plan: dict[str, Any], evidence: EvidenceContext
) -> list[HandoffCheck]:
    """Check 2: Do declared handoff artifacts exist with matching hashes?

    Resolution priority:
      1. ``evidence_path`` on the handoff entry.
      2. ``artifact`` if it matches a real evidence file path.

    Verdict per handoff:
      - resolved + hash matches (or no expected hash) → pass
      - resolved + hash mismatches → refuted
      - cannot resolve + expected_hash set → refuted
      - cannot resolve + no expected_hash → insufficient-evidence
    """
    results: list[HandoffCheck] = []
    handoffs = plan.get("handoffs", [])
    evidence_map = {f.path: f for f in evidence.files}

    for h in handoffs:
        artifact = h.get("artifact", "")
        expected_sha = h.get("expected_hash", "")

        resolved_path = _resolve_handoff_path(h, evidence_map)

        if resolved_path is not None:
            ef = evidence_map[resolved_path]
            actual_sha = ef.sha256
            exists = True
            hash_match = not expected_sha or actual_sha == expected_sha
        else:
            exists = False
            actual_sha = ""
            hash_match = False

        if resolved_path is not None and hash_match:
            st: Literal["pass", "refuted", "insufficient-evidence"] = "pass"
        elif resolved_path is not None and not hash_match:
            st = "refuted"
        elif expected_sha:
            st = "refuted"
        else:
            st = "insufficient-evidence"

        results.append(
            HandoffCheck(
                artifact=artifact,
                expected_hash=expected_sha,
                actual_hash=actual_sha,
                exists=exists,
                hash_match=hash_match,
                status=st,
            )
        )

    return results


CLAIM_EVALUATORS = frozenset({"ground-truth-exists", "ground-truth-contains"})
_INCONCLUSIVE_CLAIM_STATES = frozenset(
    {"not-evaluated", "stale", "unsupported-evaluator"}
)


def _evaluate_one_claim(
    item: dict[str, Any], evidence_map: dict[str, Any]
) -> ClaimEvaluation:
    """Evaluate one verification claim with a declared deterministic evaluator.

    Fail-closed (V127): a claim is ``supported`` only when a declared
    deterministic evaluator runs and succeeds. A claim with no declared
    evaluator stays ``not-evaluated`` (an advisory ground-truth presence note is
    recorded but never upgrades the claim to supported). A required claim that
    is not supported never yields a pass; only a deterministic refutation fails.
    """
    claim = str(item.get("claim_or_output", ""))
    required = bool(item.get("required", True))
    evaluator = item.get("evaluator")
    ground_truth = str(item.get("ground_truth", ""))

    if not evaluator:
        note = (
            "present"
            if ground_truth and ground_truth in evidence_map
            else "absent or undeclared"
        )
        return ClaimEvaluation(
            claim=claim,
            evaluator="(none)",
            state="not-evaluated",
            required=required,
            detail=f"no evaluator declared; ground truth {note} (advisory only)",
            ground_truth_source=ground_truth,
            advisory=True,
        )

    if evaluator not in CLAIM_EVALUATORS:
        return ClaimEvaluation(
            claim=claim,
            evaluator=str(evaluator),
            state="unsupported-evaluator",
            required=required,
            detail=f"unknown evaluator: {evaluator}",
            ground_truth_source=ground_truth,
        )

    if not ground_truth or ground_truth not in evidence_map:
        return ClaimEvaluation(
            claim=claim,
            evaluator=str(evaluator),
            state="refuted",
            required=required,
            detail=f"ground truth source not found: {ground_truth or '(undeclared)'}",
            ground_truth_source=ground_truth,
        )

    if evaluator == "ground-truth-exists":
        return ClaimEvaluation(
            claim=claim,
            evaluator=str(evaluator),
            state="supported",
            required=required,
            detail=f"ground truth present: {ground_truth}",
            ground_truth_source=ground_truth,
        )

    # ground-truth-contains: deterministic substring check against ground truth.
    expected = str(item.get("expected", ""))
    content = getattr(evidence_map[ground_truth], "content", "") or ""
    if expected and expected in content:
        return ClaimEvaluation(
            claim=claim,
            evaluator=str(evaluator),
            state="supported",
            required=required,
            detail=f"ground truth contains expected text: {expected!r}",
            ground_truth_source=ground_truth,
        )
    return ClaimEvaluation(
        claim=claim,
        evaluator=str(evaluator),
        state="refuted",
        required=required,
        detail=f"expected text not found in ground truth: {expected!r}",
        ground_truth_source=ground_truth,
    )


def evaluate_claims(
    plan: dict[str, Any], evidence: EvidenceContext
) -> list[ClaimEvaluation]:
    """Check 3 (V127): deterministic, fail-closed claim evaluation.

    Replaces the V104 path-existence heuristic. A claim is supported only when a
    declared deterministic evaluator succeeds; an unevaluated required claim
    contributes ``inconclusive``, never ``pass``.
    """
    verification = plan.get("verification", [])
    evidence_map = {f.path: f for f in evidence.files}
    return [
        _evaluate_one_claim(item, evidence_map)
        for item in verification
        if isinstance(item, dict)
    ]


def _adversarial_from_claims(
    claim_evals: list[ClaimEvaluation],
) -> list[AdversarialCheck]:
    """Derive the legacy advisory adversarial view from claim evaluations."""
    checks: list[AdversarialCheck] = []
    for evaluation in claim_evals:
        refuted = evaluation.state == "refuted"
        checks.append(
            AdversarialCheck(
                claim=evaluation.claim,
                refuted=refuted,
                refutation=evaluation.detail if refuted else None,
                ground_truth_source=evaluation.ground_truth_source,
            )
        )
    return checks


def check_budget_adherence(
    plan: dict[str, Any], evidence: EvidenceContext
) -> BudgetCheck:
    budget = plan.get("budget", {})
    exceeded: list[str] = []
    metadata = evidence.raw.get("metadata", {})

    max_agents = budget.get("max_agents", 0)
    if max_agents > 0:
        # V127: count agent invocations from observed records, not filenames.
        invocations = metadata.get("invocations")
        if isinstance(invocations, list):
            agent_count = len(invocations)
        elif isinstance(metadata.get("num_agents"), int):
            agent_count = metadata["num_agents"]
        else:
            agent_count = 0  # unobserved; do not infer from filenames
        if agent_count > max_agents:
            exceeded.append(f"max_agents: {agent_count} > {max_agents}")

    if metadata:
        num_rounds = metadata.get("num_rounds", 0)
        max_rounds = budget.get("max_rounds", 0)
        if max_rounds > 0 and num_rounds > max_rounds:
            exceeded.append(f"max_rounds: {num_rounds} > {max_rounds}")

    return BudgetCheck(within_limits=len(exceeded) == 0, exceeded=exceeded)


def _handoffs_for_phase(
    handoff_checks: list[HandoffCheck],
    handoffs_spec: list[dict[str, Any]],
    phase_id: str,
) -> list[HandoffCheck]:
    """Return only the handoff checks whose target phase matches *phase_id*."""
    spec_map = {s.get("artifact"): s.get("to_phase", "") for s in handoffs_spec}
    matching = [a for a, to in spec_map.items() if to == phase_id]
    if not matching:
        return []
    return [hc for hc in handoff_checks if hc.artifact in matching]


def _read_agent_fabric_captures(
    evidence: EvidenceContext,
    verified_signature_anchors_by_assurance: dict[str, set[str]],
) -> list[AgentFabricCaptureCheck]:
    captures: list[AgentFabricCaptureCheck] = []
    for evidence_file in evidence.files:
        try:
            parsed = json.loads(evidence_file.content)
        except json.JSONDecodeError:
            continue

        if not isinstance(parsed, dict):
            continue
        if parsed.get("kind") != CAPTURE_MANIFEST_KIND:
            continue

        errors = validate_capture_manifest(parsed)
        provenance_errors: list[str] = []
        trusted_provenance = False
        assurance = str(parsed.get("assurance", "A0-claims-only"))
        if not errors and assurance in (ASSURANCE_A1, ASSURANCE_A2):
            capture_signature_anchors: set[str] = set()
            provenance_errors = validate_trusted_observer_provenance(
                parsed,
                evidence_path=evidence_file.path,
                provenance=evidence.raw.get("trusted_observer_provenance"),
                key=evidence.raw.get("trusted_observer_seal_key"),
                public_key_path=evidence.raw.get(
                    "trusted_observer_public_key_file"
                ),
                verified_signature_anchors=capture_signature_anchors,
            )
            errors.extend(provenance_errors)
            trusted_provenance = not provenance_errors
            if trusted_provenance and capture_signature_anchors:
                verified_signature_anchors_by_assurance.setdefault(
                    assurance,
                    set(),
                ).update(capture_signature_anchors)
        captures.append(
            AgentFabricCaptureCheck(
                evidence_path=evidence_file.path,
                assurance=assurance,
                decision=str(parsed.get("decision", "unknown")),
                valid=not errors,
                trusted_observer_provenance=trusted_provenance,
                errors=errors,
            )
        )
    return captures


def _read_review_signals(evidence: EvidenceContext) -> list[ReviewSignal]:
    signals: list[ReviewSignal] = []
    for evidence_file in evidence.files:
        try:
            parsed = json.loads(evidence_file.content)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("kind") != "moonweave-review-receipt":
            continue

        errors: list[str] = []
        provider = parsed.get("provider")
        if not isinstance(provider, str) or not provider:
            errors.append("review receipt provider must be non-empty")
            provider = "unknown"
        axis = parsed.get("axis", "review")
        if axis != "review":
            errors.append("review receipt axis must be review")
        can_change = parsed.get("can_change_evidence_verdict")
        if can_change is not False:
            errors.append("review receipt must not change evidence verdict")
        findings = parsed.get("findings")
        if not isinstance(findings, list):
            errors.append("review receipt findings must be a list")
            findings = []
        signals.append(
            ReviewSignal(
                evidence_path=evidence_file.path,
                provider=str(provider),
                finding_count=len(findings),
                can_change_evidence_verdict=bool(can_change),
                valid=not errors,
                errors=errors,
            )
        )
    return signals


def _assurance_for_report(captures: list[AgentFabricCaptureCheck]) -> str:
    if any(capture.valid and capture.assurance == ASSURANCE_A2 for capture in captures):
        return ASSURANCE_A2
    if any(capture.valid and capture.assurance == ASSURANCE_A1 for capture in captures):
        return ASSURANCE_A1
    return "A0-claims-only"


def _decision_for_verdict(
    verdict: Literal["verified", "refuted", "insufficient-evidence"],
) -> Literal["pass", "fail", "inconclusive"]:
    if verdict == "verified":
        return "pass"
    if verdict == "refuted":
        return "fail"
    return "inconclusive"


def _trust_anchor_for_assurance(
    assurance: str,
    evidence: EvidenceContext,
    captures: list[AgentFabricCaptureCheck],
    observer_signature_anchors: set[str],
) -> dict[str, str] | None:
    if assurance not in (ASSURANCE_A1, ASSURANCE_A2):
        return None
    if observer_signature_anchors:
        public_key_path = sorted(observer_signature_anchors)[0]
        anchor = {
            "kind": "public_key",
            "public_key_path": public_key_path,
        }
        try:
            anchor["public_key_sha256"] = hashlib.sha256(
                Path(public_key_path).read_bytes()
            ).hexdigest()
        except OSError:
            pass
        return anchor
    seal_key = evidence.raw.get("trusted_observer_seal_key")
    if (
        isinstance(seal_key, bytes)
        and seal_key
        and any(
            capture.valid
            and capture.trusted_observer_provenance
            and capture.assurance == assurance
            for capture in captures
        )
    ):
        return {
            "kind": "shared_seal_key",
            "key_sha256": hashlib.sha256(seal_key).hexdigest(),
        }
    return None


def run_verification(
    plan: dict[str, Any],
    evidence: EvidenceContext,
    framework: str = "generic",
) -> VerificationReport:
    plan_hash = _compute_plan_hash(plan)
    phase_ids = [p.get("id", p.get("name", "unknown")) for p in plan.get("phases", [])]
    if not phase_ids:
        phase_ids = ["default"]

    # Compute each check ONCE (P1-5)
    gates = check_gate_compliance(plan, evidence)
    all_handoffs = check_handoff_integrity(plan, evidence)
    claim_evals = evaluate_claims(plan, evidence)
    adv_checks = _adversarial_from_claims(claim_evals)
    budget = check_budget_adherence(plan, evidence)
    contract_signature_anchors: set[str] = set()
    contract, _ = _read_evidence_contract(evidence)
    evidence_contract = validate_evidence_contract(
        evidence,
        verified_signature_anchors=contract_signature_anchors,
    )
    health_substrates, _health_binding_errors = (
        _health_evidence_substrates(evidence, contract)
        if contract is not None
        else ({}, [])
    )
    evidence_contract_schema_version = _validated_evidence_contract_schema_version(
        contract,
        evidence_contract,
    )
    advisory_findings = (
        validate_advisory_provenance(evidence, contract)
        if contract is not None
        and isinstance(contract.get("advisory_provenance"), dict)
        else []
    )
    role_capability_conformance = _role_capability_conformance(
        plan,
        contract,
        evidence_contract,
    )
    observer_signature_anchors_by_assurance: dict[str, set[str]] = {}
    agent_fabric_captures = _read_agent_fabric_captures(
        evidence,
        observer_signature_anchors_by_assurance,
    )
    review_signals = _read_review_signals(evidence)
    handoffs_spec = plan.get("handoffs", [])

    any_refuted = False
    any_insufficient = False
    phase_verdicts: list[PhaseVerdict] = []

    for pid in phase_ids:
        phase_handoffs = _handoffs_for_phase(all_handoffs, handoffs_spec, pid)
        # P1-5: no fallback — a phase with no incoming handoffs gets an
        # empty list so it is not failed by another phase's handoff.

        phase_gates = gates  # same gates for every phase (gates are plan-level)

        phase_adv = adv_checks  # adversarial checks are plan-level

        # Phase-level pass/fail logic
        handoff_refuted = any(h.status == "refuted" for h in phase_handoffs)
        handoff_insufficient = any(
            h.status == "insufficient-evidence" for h in phase_handoffs
        )
        adv_refuted = any(a.refuted for a in phase_adv)
        gate_refuted = any(
            (not g.complied) and g.evidence_path is not None for g in phase_gates
        )
        gate_insufficient = any(
            (not g.complied) and g.evidence_path is None for g in phase_gates
        )
        budget_exceeded = not budget.within_limits

        if gate_refuted or handoff_refuted or adv_refuted or budget_exceeded:
            st: Literal["passed", "failed", "skipped"] = "failed"
            any_refuted = True
        elif gate_insufficient or handoff_insufficient:
            st = "passed"  # phase itself is OK, but evidence is incomplete
            any_insufficient = True
        else:
            st = "passed"

        phase_verdicts.append(
            PhaseVerdict(
                phase_id=pid,
                status=st,
                gates=phase_gates,
                handoffs=phase_handoffs,
                adversarial=phase_adv,
                budget=budget,
            )
        )

    if _blocking_evidence_contract_entries(
        contract, evidence_contract, health_substrates
    ):
        any_refuted = True
    if any(
        entry.error_code
        in {
            _ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXIS_UNDECLARED,
            _ERR_ROLE_CAPABILITY_PLAN_REQUIRED_AXES_INVALID,
        }
        for entry in role_capability_conformance
    ):
        any_insufficient = True
    if any(not capture.valid for capture in agent_fabric_captures):
        any_refuted = True

    # A handoff whose to_phase is unknown or missing is never attributed to any
    # phase, so without this it would silently vanish from the verdict. Fail
    # closed: an orphan handoff refutes the report.
    known_phases = set(phase_ids)
    if any(
        isinstance(handoff, dict) and handoff.get("to_phase") not in known_phases
        for handoff in handoffs_spec
    ):
        any_refuted = True

    # V127: deterministic claim evaluation drives the verdict, fail-closed.
    if any(ce.required and ce.state == "refuted" for ce in claim_evals):
        any_refuted = True
    if any(
        ce.required and ce.state in _INCONCLUSIVE_CLAIM_STATES for ce in claim_evals
    ):
        any_insufficient = True

    if any_refuted:
        overall: Literal["verified", "refuted", "insufficient-evidence"] = "refuted"
    elif any_insufficient:
        overall = "insufficient-evidence"
    else:
        overall = "verified"

    assurance = _assurance_for_report(agent_fabric_captures)
    observer_signature_anchors = observer_signature_anchors_by_assurance.get(
        assurance,
        set(),
    )
    return VerificationReport(
        plan_hash=plan_hash,
        framework=framework,
        run_id=evidence.run_id,
        phases=phase_verdicts,
        evidence_contract=evidence_contract,
        evidence_contract_schema_version=evidence_contract_schema_version,
        advisory_findings=advisory_findings,
        decision=_decision_for_verdict(overall),
        assurance=assurance,
        signature_checked=bool(
            contract_signature_anchors
            or any(observer_signature_anchors_by_assurance.values())
        ),
        trust_anchor=_trust_anchor_for_assurance(
            assurance,
            evidence,
            agent_fabric_captures,
            observer_signature_anchors,
        ),
        agent_fabric_captures=agent_fabric_captures,
        claim_evaluations=claim_evals,
        review_signals=review_signals,
        role_capability_conformance=role_capability_conformance,
        policy_conformance=_policy_conformance(role_capability_conformance, contract),
        health_conformance=_health_conformance(
            contract, evidence_contract, health_substrates
        ),
        verdict=overall,
    )
