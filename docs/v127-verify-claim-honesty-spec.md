# V127 Verify-Claim Honesty Spec

Status: spec for the next real milestone. Not yet implemented.
Date: 2026-06-24.

Parent direction: `docs/v125-direction-check-roadmap.md` (Section 6.1-6.2, "now").

## 1. Research and prior art

Depone markets a "4-Check Engine" (README): Gate Compliance, Handoff Integrity,
Adversarial Check, Budget Adherence. Three are genuine deterministic checks. The
fourth is not:

- `depone/verify/engine.py::check_adversarial` is, by its own docstring, a
  "heuristic stub." It flags a claim only when the declared `ground_truth` file
  path is absent from the evidence file set. It does not read ground truth and
  cannot determine whether a claim is actually refuted by it. A semantically
  valid-but-wrong claim with a present ground-truth path passes.
- `depone/verify/engine.py::check_budget_adherence` infers `agent_count` from
  filenames containing "agent", rather than from invocation records.

The repository's own `keelplane-v105-final/docs/upstream-gap-map.md` flags both
as critical and proposes `ClaimEvaluation` states
(`supported`, `refuted`, `not-evaluated`, `stale`, `unsupported-evaluator`), with
the rule: a required non-supported claim yields `inconclusive`, except `refuted`
which yields `fail`. The mid-2026 eval consensus (V125 Sections 3-4) is
unambiguous: deterministic checks are the pass/fail authority; LLM-judge and
heuristic signals are advisory and must never override deterministic checks; raw
judge-agreement numbers are a known trap and must be chance-corrected.

Two adjacent honesty problems are corrected in the same milestone:

- README says "hash-signed verification reports." SHA-256 content-addressing
  detects accidental change; it is not a signature and provides no
  non-repudiation. A2/A3 assurance is spec-only; code emits A0/A1.
- The V104 regulatory thesis is stale (EU AI Act high-risk postponed to late
  2027 / 2028; Colorado repealed/replaced to early 2027; the six-month log
  retention floor is EU AI Act Article 19, not Article 12; GPAI obligations are
  in force since 2025-08).

## 2. Product position and non-goals

Position: make the verify engine and the user-facing claims tell the truth about
what is deterministically checked, so the one asset that matters — trust — is not
eroded by over-claiming. This strengthens, not weakens, the product: an honest
"inconclusive" is more valuable to an audit/procurement buyer than a false
"verified."

Non-goals:

- Do not build a real adversarial verifier in this milestone (that is a later
  item, kept strictly advisory). V127 only stops the over-claim and makes a
  required-but-unevaluated claim resolve safely.
- Do not change the three real deterministic checks' behavior.
- Do not add cryptographic signing here; only stop calling content-addressing
  "signing" and label A2/A3 as not yet implemented.

## 3. Workflow architecture

```text
plan.verification[*]  (claim_or_output, ground_truth, falsifier, evaluator?)
  |
  v
claim evaluation:
  - if no real evaluator is bound        -> not-evaluated
  - if ground-truth presence check only  -> not-evaluated (advisory note: present/absent)
  - if a deterministic evaluator runs    -> supported | refuted
  - if bound snapshot is stale           -> stale
  |
  v
decision rollup:
  - any required claim refuted           -> fail
  - any required claim not-evaluated/stale/unsupported-evaluator -> inconclusive
  - all required claims supported + deterministic checks pass     -> pass
  |
  v
report: decision (pass|fail|inconclusive) + assurance (A0..A3),
        per-claim state with stable issue codes, advisory signals labeled advisory
```

The current `check_adversarial` becomes an advisory "ground-truth presence
check" feeding the `not-evaluated` path, never the `supported` path. It may
annotate a claim as "ground truth present/absent" but cannot mark it supported.

## 4. Execution model

1. Add a `ClaimEvaluation` state enum and per-claim records:
   `supported`, `refuted`, `not-evaluated`, `stale`, `unsupported-evaluator`,
   each with a stable issue code and a source evidence reference.
2. A claim is `supported` only when a deterministic evaluator (command exit code,
   hash match, exact-match check) returns success against a current snapshot.
   The ground-truth presence heuristic alone produces `not-evaluated` plus an
   advisory note.
3. Roll up: a required `refuted` yields `fail`; any required claim in
   `not-evaluated` / `stale` / `unsupported-evaluator` yields `inconclusive`;
   only all-required-`supported` plus passing deterministic checks yields `pass`.
   Keep the legacy `verified` / `refuted` / `insufficient-evidence` strings as a
   compatibility rendering only; the new decision + assurance fields are
   authoritative.
4. Count budget invocations from invocation/manifest records, not filenames.
5. README/SKILL correction: describe "verify" as the three deterministic checks
   (gate compliance, handoff SHA-256 integrity, budget adherence) plus an
   advisory ground-truth presence signal; remove "hash-signed" where it means
   content-addressing; label A2/A3 assurance as not yet implemented.
6. Regulatory correction: update `docs/v104-product-direction-spec.md` risk
   framing and any positioning text to the live anchors (GPAI in force since
   2025-08; EU AI Act Article 12 logging plus Article 19 six-month retention;
   ISO/IEC 42001 plus procurement diligence) and note the high-risk postponement
   and Colorado repeal. Message 2026 demand as voluntary/procurement-driven.

Note on contract surfaces: README, the command reference, release history, and
hero assets are guarded by the V87 brand boundary audit and `check_readme_quality.py`.
Any wording change to those surfaces in step 5 must keep those gates green; make
the minimal change and re-run the gates.

## 5. Safety and verification gates

- Fail closed: an unknown or missing evaluator must never produce `pass`. The
  first regression fixture (from the gap-map) is: a plan has a required claim and
  an existing ground-truth path but no evaluator result; expected decision is
  `inconclusive`, never `pass`.
- Advisory signals (ground-truth presence, any future judge) are rendered with an
  explicit `advisory` flag and never change a deterministic `fail`/`pass`.
- No raw agreement numbers in any report or contract field.

## 6. Evaluation fixtures

- required claim, ground-truth present, no evaluator -> `inconclusive`;
- required claim, deterministic evaluator success -> `supported` -> `pass`;
- required claim, deterministic evaluator failure -> `refuted` -> `fail`;
- required claim bound to a stale snapshot -> `stale` -> `inconclusive`;
- budget invocation count derived from invocation records, not filenames, across
  a fixture where filename-based counting would have given a different number;
- a README/claims fixture (or doc check) asserting the engine description names
  three deterministic checks plus an advisory signal, and that "hash-signed" is
  not used for content-addressing.

## 7. Implementation plan

- Phase 1: claim-evaluation states + fail-closed rollup + budget-from-invocations,
  with regression fixtures. This is the semantic-safety change the V105 audit and
  the gap-map both put first.
- Phase 2: demote `check_adversarial` to an advisory ground-truth presence check;
  keep the function and its output but route it to `not-evaluated` plus an
  advisory note.
- Phase 3: README/SKILL claim correction and the regulatory thesis correction,
  keeping brand-boundary and readme-quality gates green.
- Phase 4: write `docs/v127-decision.md` recording the false-pass path closure
  and the corrected claims.

Done means: a required-but-unevaluated claim can no longer produce `pass`; the
engine description and assurance language match what the code actually does; the
regulatory framing is current; and all existing contract checks still pass.

Required verification:

- `python scripts/check_contract.py --tier changed`
- `PYTHONPATH=. python3 -m depone verify --self-test`
- `python scripts/check_readme_quality.py README.md` (only if README changed)
- `python scripts/check_release_text.py .` and `python scripts/check_whitespace.py .`
