# V125 decision

Decision: keep the project, and narrow it. Record the direction evaluation as a
source-only direction checkpoint and lock the forward roadmap; do not treat V125
as a new implemented feature milestone.

Rationale:

- The defensible bet is confirmed: a non-executing design + verify plane whose
  truth is artifacts and source hashes, not model claims. This is aligned with,
  and in one respect ahead of, the mid-2026 consensus, and it is the one slice a
  hyperscaler cannot neutrally own.
- The marketed surface overstates the implemented surface. The Adversarial Check
  is a path-existence heuristic, standards alignment is prose-only, A2/A3 are
  spec-only, and no real direct-vs-governed run has ever been verified — yet the
  plumbing to run one already exists.
- The corrective is not more contract layers. It is one real captured run
  (V126), claim honesty in the verify engine and docs (V127), and a portable,
  audit-grade evidence substrate (V128), in that order.
- The Agent Fabric profile/role/toolbelt taxonomy is demoted to a retire-able
  reference library and frozen for new milestones until V126 shows a measured
  benefit for at least one task class.

Scope and non-claims:

- This is source-only: it does not execute agents, run commands, upgrade trust,
  publish benchmark claims, or rename packages.
- It does not modify `README.md`, `docs/release-history.md`,
  `docs/automation-roadmap.md`, the command reference, or hero assets; the brand
  boundary and roadmap reconciliation surfaces are unchanged.

Source of truth and pointers:

- Roadmap and evaluation: `docs/v125-direction-check-roadmap.md`.
- Concrete specs: `docs/v126-paired-dogfood-evidence-spec.md`,
  `docs/v127-verify-claim-honesty-spec.md`,
  `docs/v128-evidence-substrate-spec.md`.

Verification:

- `python scripts/check_contract.py --tier changed`
- `python scripts/check_release_text.py .`
- `python scripts/check_whitespace.py .`
