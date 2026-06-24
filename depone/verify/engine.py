from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from depone.agent_fabric.capture_bridge import (
    ASSURANCE_A1,
    CAPTURE_MANIFEST_KIND,
    validate_capture_manifest,
)
from depone.verify.adapters.base import EvidenceContext
from depone.verify.evidence_contract import (
    EvidenceContractEntry,
    validate_evidence_contract,
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
    errors: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    schema_version: str = "1.0"
    plan_hash: str = ""
    framework: str = "generic"
    run_id: str | None = None
    phases: list[PhaseVerdict] = field(default_factory=list)
    evidence_contract: list[EvidenceContractEntry] = field(default_factory=list)
    decision: Literal["pass", "fail", "inconclusive"] = "pass"
    assurance: str = "A0-claims-only"
    agent_fabric_captures: list[AgentFabricCaptureCheck] = field(
        default_factory=list
    )
    claim_evaluations: list[ClaimEvaluation] = field(default_factory=list)
    verdict: Literal["verified", "refuted", "insufficient-evidence"] = "verified"


def _compute_plan_hash(plan: dict[str, Any]) -> str:
    raw = json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


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
        note = "present" if ground_truth and ground_truth in evidence_map else "absent or undeclared"
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
        captures.append(
            AgentFabricCaptureCheck(
                evidence_path=evidence_file.path,
                assurance=str(parsed.get("assurance", "A0-claims-only")),
                decision=str(parsed.get("decision", "unknown")),
                valid=not errors,
                errors=errors,
            )
        )
    return captures


def _assurance_for_report(captures: list[AgentFabricCaptureCheck]) -> str:
    if any(
        capture.valid and capture.assurance == ASSURANCE_A1 for capture in captures
    ):
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
    evidence_contract = validate_evidence_contract(evidence)
    agent_fabric_captures = _read_agent_fabric_captures(evidence)
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

    if evidence_contract:
        any_refuted = True
    if any(not capture.valid for capture in agent_fabric_captures):
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

    return VerificationReport(
        plan_hash=plan_hash,
        framework=framework,
        run_id=evidence.run_id,
        phases=phase_verdicts,
        evidence_contract=evidence_contract,
        decision=_decision_for_verdict(overall),
        assurance=_assurance_for_report(agent_fabric_captures),
        agent_fabric_captures=agent_fabric_captures,
        claim_evaluations=claim_evals,
        verdict=overall,
    )
