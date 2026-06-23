# V104: Keelplane Product Direction — Workflow Designer + Cross-Platform Verifier

Status: Draft (v2)
Date: 2026-06-22

## Why V104

Keelplane built high-quality evidence infrastructure (hash-ledgers, gates,
adversarial verification, scoring) but no user-facing product. Meanwhile,
Microsoft Conductor (May 2026) proved "deterministic multi-agent orchestration"
is a real market — and shipped with a YAML DSL, installer, and web dashboard.

This is not a threat. It reveals the right strategy: **do not build another
execution engine. Build the design + verification layer above existing ones.**

## Product Thesis

> Keelplane designs multi-agent workflows and verifies their execution evidence.
> It does not execute agents. It makes runs from other frameworks trustworthy.

- **design**: decompose broad objectives into the existing `workflow.plan.json`
  schema (phases, workers, handoffs, gates, budgets).
- **compile**: translate plans into target framework formats (Conductor YAML
  first; LangGraph Python later).
- **verify**: consume raw execution evidence from any framework, check it
  against the plan, produce hash-signed verification reports.

## User & Workflow

An AI engineering team using Conductor or LangGraph for agent execution.
They want structured workflow design and tamper-evident verification without
switching execution engines.

```
keelplane design "audit all API routes" --out plan.json
       │
       ▼  compile --target conductor
    workflow.yaml
       │
       ▼  conductor run workflow.yaml     ← execution: not Keelplane
    ./run-output/
       │
       ▼  verify plan.json --evidence ./run-output/
    verification-report.json              ← evidence: Keelplane
```

---

## 1. Design (`keelplane design`)

### Input
- Natural language objective
- Optional `--surface` (repo path, API spec, doc URL)
- Optional `--constraints` (budget rules, forbidden actions)

### Output: `workflow.plan.json`

Reuses the existing **schema v0.5** defined in
`references/workflow-plan-schema.md`. No new schema. The existing fields map
directly:

| Plan Field | Source | Purpose |
|---|---|---|
| `objective` | User input | Desired outcome |
| `surfaces` | `--surface` + discovery | Repos, APIs, docs in scope |
| `assumptions` | LLM inference | Claims that must be verified before trusting the plan |
| `phases` | Decomposition | Ordered stages with entry/exit criteria |
| `workers` | Role assignment | Who does what, with what tools, under what constraints |
| `handoffs` | Phase dependency | Artifacts passed between phases, with schema + validation |
| `parallelism` | Dependency analysis | Fan-out cap, barrier conditions, fan-in rule |
| `verification` | Risk analysis | Falsifiers and required evidence per claim |
| `risk_gates` | Safety analysis | Destructive/costly actions and their safe defaults |
| `budget` | Constraint | Max agents, rounds, retries, wall time, file touches |
| `resume` | Cost analysis | What can be cached and what invalidates a cache |
| `execution_path` | Activation decision | `activate` or `downgrade` with first-slice packet |

The existing `evaluate_plan.py` already validates this schema on fixtures.
`keelplane design` wraps this validation in the CLI.

### Implementation: Thin Wrapper

`keelplane design` does not write a new planner. It invokes the existing DWM
workflow design logic (currently embedded in `SKILL.md` and the keelplane skill)
to produce a `workflow.plan.json`, then runs `evaluate_plan.py` validation on
the output.

---

## 2. Compile (`keelplane compile`)

### Input
- `workflow.plan.json` (schema v0.5)
- `--target` (`conductor` first; `langgraph` post-V104)

### Output: target framework workflow file

The compile step is a **bijection** between the plan schema and the target
framework's native format:

| Plan Concept | Conductor YAML | LangGraph Python (future) |
|---|---|---|
| Phase | Agent node | `StateGraph` node |
| Sequential dependency | Implicit YAML ordering | Edge between nodes |
| Parallel phases | `for_each` / parallel group | `fanout` node |
| Handoff artifact | `input_mapping` + `output` | State schema field |
| Risk gate | Human-in-the-loop step | `interrupt_before` |
| Verification | Script step (exit code routed) | `Command` node |
| Budget | `max_iterations` + `timeout` | Recursion limit |

### Adapter Architecture

```
keelplane compile plan.json --target conductor
    │
    ├── 1. Validate plan.json (schema v0.5 check)
    ├── 2. Map phases → Conductor agent nodes
    ├── 3. Map handoffs → input_mapping / output
    ├── 4. Map gates → human steps
    ├── 5. Map verification → script steps
    └── 6. Emit workflow.yaml
```

Each target is a separate Python module under `keelplane/compile/targets/`.
Dependencies specific to a target are imported only when that target is used.

---

## 3. Verify (`keelplane verify`)

### Input
- `workflow.plan.json`
- `--evidence <path>` — directory with execution output
- `--adapter <name>` — how to interpret the evidence (conductor, generic)

### Output: `verification-report.json`

The verification performs four checks, in order:

### 3.1 Gate Compliance Check

Did the execution respect every declared `risk_gate` in the plan?

| Gate Claim | Verification |
|---|---|
| "Phase 1 is read-only" | Check evidence for no write operations |
| "Phase 2 has no network" | Check evidence for no network calls |
| "Approval was obtained at gate X" | Check approval artifact exists |

If any gate was violated with no evidence of approval → **FAIL**.

### 3.2 Handoff Integrity Check

Does every declared handoff artifact exist, at the right location, with the
right hash?

For each `handoff` in the plan:
1. Locate artifact in evidence directory
2. Compute SHA-256
3. Compare with declared hash (if any)
4. Validate against `artifact_schema.required_fields`

If any handoff is missing or hash-mismatched → **FAIL**.

### 3.3 Adversarial Check (Against Ground Truth)

For each `verification.claim_or_output` in the plan, an independent verifier
reads the actual source/data/artifact and tries to *refute* the claim.

The existing pattern from `references/workflow-patterns.md` applies directly:

> The verifier must be independent of the producer. The verifier tries to refute
> the finding, not rubber-stamp it. Verify against GROUND TRUTH, not the
> producer's claims: read the actual source, data, or artifact and cite it.
> Default to refuted/flagged when the ground truth does not support the claim.

If any claim is refuted → **FAIL**.

### 3.4 Budget Adherence Check

Did execution stay within `budget` limits?

- `max_agents`: number of distinct agent invocations
- `max_rounds`: loop iterations per phase
- `max_retries`: retry count per action
- `max_time`: wall clock time
- `max_file_touches`: files created or modified

If any limit exceeded → **FAIL**.

### Verdict

All four checks pass → `"verified"`. Any fail → `"refuted"` with specific
evidence citations.

### Evidence Protocol Data Model

```python
# verification-report.json schema
@dataclass
class VerificationReport:
    schema_version: str = "1.0"
    plan_hash: str                     # SHA-256 of plan.json
    framework: str                     # "conductor" | "generic"
    run_id: str | None
    phases: list[PhaseVerdict]
    verdict: Literal["verified", "refuted", "insufficient-evidence"]

@dataclass
class PhaseVerdict:
    phase_id: str
    status: Literal["passed", "failed", "skipped"]
    gates: list[GateCheck]
    handoffs: list[HandoffCheck]
    adversarial: AdversarialCheck | None
    budget: BudgetCheck

@dataclass
class GateCheck:
    gate_id: str
    trigger: str
    complied: bool           # False = gate was violated
    evidence_path: str | None

@dataclass
class HandoffCheck:
    artifact: str
    expected_hash: str
    actual_hash: str
    exists: bool
    hash_match: bool

@dataclass
class AdversarialCheck:
    claim: str
    refuted: bool            # True = verifier refuted the claim
    refutation: str | None    # Only if refuted: "file:line" citation
    ground_truth_source: str

@dataclass
class BudgetCheck:
    within_limits: bool
    exceeded: list[str]      # e.g. ["max_time: 30m > 15m budget"]
```

---

## 4. CLI Surface

The entire product is three commands:

```bash
keelplane design "objective" [--out plan.json] [--surface <path>]
keelplane compile plan.json --target conductor [--out workflow.yaml]
keelplane verify plan.json --evidence <dir> [--adapter conductor] [--out report.json]
```

Plus two auxiliary commands:

```bash
keelplane demo                     # runs a complete design→compile→verify cycle
keelplane validate plan.json       # validate a plan without designing it
```

### Demo Flow (`keelplane demo`)

```
1. keelplane design "summarize the README" --surface . --out /tmp/demo/plan.json
   → produces valid plan.json using local directory as surface

2. keelplane compile /tmp/demo/plan.json --target conductor --out /tmp/demo/workflow.yaml
   → produces runnable Conductor YAML

3. [Run via Conductor if available, else simulate with local shell adapter]

4. keelplane verify /tmp/demo/plan.json --evidence /tmp/demo/evidence/ --out /tmp/demo/report.json
   → produces verification report
```

If Conductor CLI is not installed, step 3 uses a local shell adapter that
invokes basic commands instead. The demo must complete without any external
dependency beyond Python stdlib + `pip install keelplane`.

---

## 5. Implementation: 102 Scripts → 1 Package

### Strategy: Wrap First, Refactor Later

**Do NOT rewrite DWM Core. It works. Wrap it.**

The 102 `scripts/dwm_*.py` files fall into two categories:

| Category | Count | Approach |
|---|---|---|
| **Core logic** (plan, compile, evidence, gate, hash) | ~30 | Import as-is into `keelplane.core.*` |
| **Product shell** (CLI, demo, release commands) | ~30 | Replace with `keelplane.cli.*` commands |
| **Fixtures & self-tests** (check_contract, --self-test) | ~30 | Keep in `scripts/` for testing |
| **Dead/stale** (not referenced by any active flow) | ~12 | Archive to `scripts/archive/` |

### Package Structure

```
keelplane/                          # installable package (pip)
├── __init__.py
├── __main__.py                     # "python -m keelplane"
├── cli/
│   ├── design.py                   # wraps existing plan logic
│   ├── compile.py                  # compiler registry
│   ├── verify.py                   # evidence verification engine
│   ├── validate.py                 # plan schema validation
│   └── demo.py                     # demo runner
├── core/
│   ├── plan_schema.py              # existing plan schema (from evaluate_plan.py)
│   ├── hash_ledger.py              # existing hash verification logic
│   ├── gate.py                     # existing gate models
│   └── evidence_oracle.py          # existing evidence oracle
├── compile/
│   ├── __init__.py
│   ├── base.py                     # abstract compiler interface
│   └── targets/
│       ├── conductor.py            # → Conductor YAML
│       └── langgraph.py            # → LangGraph Python (future)
└── verify/
    ├── __init__.py
    ├── engine.py                   # orchestrates the 4 checks
    └── adapters/
        ├── base.py                 # abstract evidence reader
        ├── conductor.py            # reads Conductor execution output
        └── generic.py              # reads generic directory evidence

scripts/                            # retained for testing
├── check_contract.py               # full contract test (unchanged)
├── dwm_demo.py                     # ← replaced by keelplane.cli.demo
├── archive/                        # dead scripts moved here
└── ...                             # other test/fixture scripts kept
```

### Migration Sequence

```
Step 1: Create keelplane/ package skeleton that imports existing scripts
        CLI calls existing dwm_*.py functions directly
        → No logic change. CLI works day 1.

Step 2: Move core logic into keelplane.core.* one module at a time
        Existing scripts become thin wrappers that import from keelplane
        → Both paths work during transition.

Step 3: When all callers use keelplane.*, remove script wrappers
        → Clean final state.
```

---

## 6. Dependency Policy

| Module | Dependencies | Policy |
|---|---|---|
| `keelplane.cli.design` | stdlib only | Zero deps. Pure schema generation. |
| `keelplane.cli.verify` | stdlib only | Zero deps. Reads files, computes hashes, writes JSON. |
| `keelplane.compile.targets.conductor` | Conductor SDK (optional) | Imported only when `--target conductor` used. |
| `keelplane.compile.targets.langgraph` | langgraph (optional) | Imported only when `--target langgraph` used. |
| `keelplane.cli.demo` | None (stdlib) or optional conductor | Falls back to local shell adapter if conductor not installed. |
| `scripts/check_contract.py` | stdlib only | Unchanged. |

Install: `pip install keelplane` (stdlib only, ~200KB).
With compile targets: `pip install "keelplane[conductor]"` or `pip install "keelplane[all]"`.

---

## 7. Testing Strategy

### Preserve Existing Tests

The existing tests (`--self-test` on every script, `check_contract.py` tiers)
remain in `scripts/` and must continue passing.

### New Tests

| Test | Location | What It Verifies |
|---|---|---|
| `keelplane design --self-test` | `keelplane/cli/design.py` | Generates valid plan.json from fixture objective |
| `keelplane compile --self-test` | `keelplane/cli/compile.py` | Conductor YAML output matches expected |
| `keelplane verify --self-test` | `keelplane/cli/verify.py` | Known-good evidence → verified; tampered evidence → refuted |
| `keelplane demo --self-test` | `keelplane/cli/demo.py` | Full cycle completes without external tools |

### CI Gates (when repo is public)

```bash
keelplane demo --self-test          # 10s - must pass
python scripts/check_contract.py    # existing - must pass
pytest tests/                       # new unit tests
```

---

## 8. Decision Gates

### V104.0 → V104.1 (Month 1 → 2)

| Gate | Criteria | Pass/Fail |
|---|---|---|
| CLI ship | `pip install keelplane && keelplane demo` works on a clean machine | |
| Plan reuse | `keelplane design` output passes `evaluate_plan.py` validation | |
| Conductor compile | `keelplane compile --target conductor` produces valid YAML (validated by `conductor validate`) | |
| Verify | `keelplane verify` correctly distinguishes known-good from tampered evidence | |
| Self-test | `keelplane demo --self-test` and `scripts/check_contract.py` both pass | |

### V104.1 → V104.2 (Month 2 → 3)

| Gate | Criteria | Pass/Fail |
|---|---|---|
| Repo public | GitHub repo public, README clean | |
| PyPI | `pip install keelplane` works from PyPI | |
| CI | GitHub Actions passing on main | |
| SNIFF test | 1-2 external users completed the demo without assistance | |

### V104.2 → Post-V104 (Month 4+)

| Gate | Criteria | Pass/Fail |
|---|---|---|
| Community | GitHub Discussions has active threads | |
| LangGraph target | `keelplane compile --target langgraph` works | |
| Re-evaluate | Have 3+ external users verified real workflows? If no → wind down. | |

---

## 9. Success Criteria

| Criterion | V104.0 | V104.1 | V104.2 | Post-V104 |
|---|---|---|---|---|
| Installation | `pip install keelplane` | PyPI + Homebrew | Same | Same |
| Demo | `keelplane demo` < 10s | Same | Same | Same |
| Design | Valid plan.json | Same | Same | Same |
| Compile | Conductor YAML | Same | + LangGraph | + Temporal |
| Verify | 4 checks pass on known data | Same | + real Conductor run | + real LangGraph run |
| Users | 0 (internal) | 1-2 | 3+ external | 10+ external |
| Community | None | GitHub Issues | Discussions | Active contributors |

## 10. Community & Feedback Strategy

### Principle: Ship First, Then Open Source

No community forms around a tool nobody can install. Sequence:

1. **V104.0:** Build CLI. No public repo. No community.
2. **V104.1:** Repo public on GitHub + PyPI + CI. README with the new positioning.
   GitHub Issues enabled for bug reports.
3. **V104.2:** GitHub Discussions enabled. Targeted outreach to Conductor
   community (267 GitHub stars, Microsoft official).

### Outreach Target (V104.2)

| Channel | Message | Priority |
|---|---|---|
| **Conductor GitHub Issues** | "We built a verification layer for Conductor workflows — `keelplane verify` produces tamper-evident evidence reports" | Primary |
| **Conductor Discord/Community** | Same message, demo link | Primary |
| **LangGraph GitHub Discussions** | "Keelplane can design and verify LangGraph workflows too" | Secondary |
| **Hacker News** | "Show HN: Keelplane — design + verify agent workflows without running them" | Launch only |

### What NOT to Do

- Do not open source before CLI ships. Premature = no feedback.
- Do not post on HN/Reddit before it's installable.
- Do not build community features (Discussions, CONTRIBUTING.md, governance)
  until at least 1 external user exists.

## 11. Non-Goals (Reaffirmed)

- Do **not** build an execution engine. Conductor, LangGraph, Temporal already win.
- Do **not** compete with Conductor's YAML DSL. Compile *to* it.
- Do **not** rewrite DWM Core. Wrap it.
- Do **not** add a web dashboard before CLI works.
- Do **not** build community before the product works.
- Do **not** support every agent framework at once. Conductor first, then LangGraph.

---

## 12. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Conductor adds verification features | Medium | Move fast (6 months). Keelplane's adversarial verification against GROUND TRUTH is deeper than any built-in check. |
| LangGraph adds signed receipts | Medium | If they do before V104.2 ships, pivot to workflow-design-only. |
| Nobody needs evidence verification | Low | EU AI Act (Aug 2026) and Colorado AI Act (Jun 2026) create regulatory demand. But enterprise sales cycle is slow. |
| 102→1 consolidation breaks something | Medium | Wrap-first strategy: existing scripts and tests keep passing during migration. |
| Conductor ecosystem doesn't grow | Low | Conductor is Microsoft-backed, 267 stars in 2 months. If it stalls, pivot to LangGraph adapter first. |
