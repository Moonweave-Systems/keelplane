# V125 Direction Check And Forward Roadmap

Status: direction checkpoint written after V124 (Agent Fabric operating-system
contract). Date: 2026-06-24.

> Read this first. This document is the current product-direction source of
> truth for Depone / DWM Core. It records an external evaluation of where the
> project stands against the mid-2026 global consensus on agent team systems and
> agent operating/control planes, and it locks the next roadmap. It supersedes
> the directional framing of `docs/v43-direction-check-roadmap.md` for everything
> after V124.

## 0. How this document was produced

The evaluation behind this roadmap combined a full read of the repository
(`README.md`, `SKILL.md`, `docs/spec.md`, the V104 / V107 / V124 specs, and the
`keelplane-v105-final/docs/*` strategy and audit set) with a seven-dimension
global-consensus research pass (multi-agent orchestration, evals/verification,
agent-ops/observability/governance, interop protocols, provenance/security/
compliance, determinism/context-engineering, and market positioning). Each
research dimension was adversarially fact-checked; stale and fabricated claims
were corrected before being used (see Section 8, Integrity notes).

## 1. Verdict

Narrow hard, and keep the discipline that makes the project credible.

Depone's one structurally defensible bet is correct and arrived before the
market named the category: a **non-executing design + verify plane that treats
artifacts and source hashes as truth and refuses to let agents seal their own
evidence**. That maps onto the verified 2026 consensus (the independent
governance plane, verification asymmetry, the deterministic-scaffold /
stochastic-core architecture), and it is the one slice a hyperscaler cannot
neutrally own, because hyperscalers execute and therefore have a conflict of
interest when grading their own runs.

Everything else is weaker than the milestone count implies:

- The **design** half is a keyword/template scaffold with no real planner, and
  the cross-framework design+verify+control layer is now given away free under
  MIT by Microsoft (Conductor + ASSERT + the Agent Control Stack).
- The **Agent Fabric** (the agent team system) is well-designed but unvalidated
  planning scaffolding aimed at the commoditizing side of the market; after the
  V107-V124 milestones it has only ever processed synthetic seed fixtures.
- The marketed **four-check verify engine** overstates itself. Three checks
  (handoff SHA-256 integrity, gate compliance, budget adherence) are genuine
  deterministic checks. The fourth, the Adversarial Check, is a path-existence
  heuristic (`depone/verify/engine.py`, the adversarial branch), not a claim
  evaluator, and must not be sold as one.

The decisive internal finding: the plumbing to run a real direct-vs-governed
test already exists (`scripts/dwm_live_proof.py` shells out to a live coding
CLI; `scripts/dwm_dogfood_pair.py` has real receipt validation), yet it was
routed into `seed-a` / `seed-b` synthetic fixtures, with a self-authored
`blocked-live-execution-overclaim` audit. The capability to cross the
value-proving threshold was built and then pointed at synthetic data. For a
project whose entire discipline is "never present unrun work as done," that is
the single gap to close first.

## 2. Current state — what is done, real, and overstated

| Area | State | Grade | Note |
|---|---|---|---|
| Non-executing design+verify plane (core bet) | Principle established | A- | Ahead-of-category; the one structural moat. |
| Verify engine: deterministic checks (handoff/gate/budget) | Implemented | B | Genuine, replayable, ground-truthed checks. |
| Verify engine: Adversarial Check | Path-existence heuristic | D | Marketed as claim evaluation; must be demoted to advisory. |
| Design / planner half | Keyword/template scaffold | C- | Commoditized by free MIT tooling; no real planner. |
| Agent Fabric (team system) | Contracts + compiler only, no live run | C | Toolbelt least-privilege is the bright spot; profile taxonomy unearned. |
| Standards / interop alignment | Prose-only in docs | C | Right substrate chosen (in-toto/DSSE/OTel/Sigstore); schemas are bespoke. |
| Evidence trust chain (Runner / assurance) | Runner is fixture/dry-run only | C- | Code emits only A0/A1; capture layer is the unmet load-bearing piece. |
| Value validation / proof | Real plumbing pointed at synthetic seeds | D | n=1 trivial live proof, no external users, no real paired delta. |
| Regulatory / market thesis currency | Partly stale | C | Real demand, but the Aug-2026 forcing function is gone (see 6.2). |
| Engineering surface / auditability | 104 scripts, SemVer 104.0.0 vs V124 | C- | A trust product that is itself hard to audit. |
| Discipline (planned-vs-executed integrity) | The project's biggest asset | B+ | One breach: real capability routed into fixtures, engine over-claimed. |

The independently confirmed contradiction worth carrying forward: the
`keelplane-v105-final` self-audit (2026-06-23) explicitly said to **stop adding
one-script-per-concept meta layers, finish one vertical `plan -> capture ->
verify -> report` loop, then run a paired evaluation**, and to defer dashboards,
extra personas, extra compiler targets, and extra readiness/meta scores. The
V107-V124 work then added source-only Agent Fabric contract layers — the exact
pattern that audit said to stop. This roadmap honors the V105 audit, not the
treadmill that followed it.

## 3. Where the global consensus is heading (agent teams)

Sources are listed in Section 9. Confidence is high unless noted.

- **Multi-agent helps or hurts by domain; nobody "won."** Orchestrator-worker
  fan-out demonstrably helps breadth-first, read-heavy, parallelizable work (the
  Anthropic research system reports a large lift over a single agent, at roughly
  an order of magnitude more tokens). It hurts decision-coupled work with shared
  evolving state. Anthropic itself states multi-agent is a poor fit for most
  coding tasks and for domains where agents must share one context.
- **Direct-by-default is the consensus default**, not a compromise: prefer the
  simplest structure; prefer deterministic workflows over autonomous agents; add
  agents only when they demonstrably improve outcomes.
- **Teams stay small** (about three to five focused workers; "three focused
  teammates often outperform five scattered ones"). Every major framework
  (OpenAI Agents SDK, LangGraph, CrewAI, Microsoft Agent Framework, Google ADK,
  Amazon Bedrock) ships a supervisor/orchestrator + specialized-worker backbone.
- **"More agents = better" is hype.** A distilled single agent can match a
  multi-agent system at a fraction of the compute and latency; topology matters
  less than calibration. Per-persona role assignment, beyond clean task
  decomposition and tool/context isolation, is not established to help.
- **Least-privilege per role is the durable team-design win**, and doing it as a
  compile-time artifact (rather than runtime prompt restriction) is ahead of
  most frameworks.

Implication for Depone: "direct-by-default, route to a team only when task shape
justifies it" and "agents may not seal evidence" are squarely correct. But a
**coding** control plane that elaborates a fixed five-profile / ten-role
taxonomy is aiming at the area where multi-agent is least valuable and where the
bitter-lesson risk is highest. Keep the toolbelt least-privilege model; demote
the taxonomy to retire-able config.

## 4. Where the global consensus is heading (operating / control plane)

- **An independent governance plane is crystallizing above execution**, defined
  as needing to sit outside both build and orchestration. Depone's non-executing
  posture is exactly this plane, and predates the naming.
- **The trust hierarchy for "did the run succeed" has converged**: deterministic,
  held-out, ground-truthed checks (tests, typecheck, CI, exact-match) are the
  pass/fail authority; LLM-as-judge is advisory only and must be
  chance-corrected (raw agreement numbers are a known trap). Trajectory/path
  evidence, not just outcome artifacts, is how spec-gaming is caught; graders and
  reference material must be held out of agent reach.
- **Telemetry has a de facto wire format**: OpenTelemetry GenAI semantic
  conventions (`gen_ai.*` spans, `invoke_agent` / `execute_tool`) plus
  OpenInference.
- **Interop is settled at the top tier**: MCP for agent-to-tool, A2A for
  agent-to-agent, both under neutral Linux Foundation governance. Multi-hop /
  recursive delegation attribution remains genuinely unsolved — no deployed
  standard.
- **Provenance substrate is mature and regulator-accepted**: in-toto/ITE-6
  Statements, DSSE envelopes, Sigstore, SLSA, extending to AI artifacts and
  agent identity.
- **Determinism belongs to the scaffold, not the model.** "Deterministic
  scaffold + stochastic core" is the durable architecture; a non-executing plane
  sidesteps the inference-determinism throughput tax entirely. The "deterministic
  workflow machine" framing is aligned with the field only if determinism is
  scoped to orchestration, contracts, provenance, replay, and scoring — and is
  explicitly not claimed for model reasoning.
- **The design+verify+control layer is commoditizing toward free standards and
  hyperscaler distribution.** The durable buyer for evidence is procurement /
  CISO / risk / compliance in regulated contexts, not a deadline-forced one.

Implication for Depone: be the neutral evidence layer **on top of** the
converging standards, not a competitor to them. Today those standards are
prose-only in the docs while the schemas are bespoke — that is the gap that
makes evidence non-portable and non-audit-grade.

## 5. Two-system evaluation (keep / change / add)

### 5.1 Agent team system (Agent Fabric)

Verdict: well-designed, unvalidated, aimed at the commoditizing side. Demote to a
thin, explicitly retire-able reference profile library subordinate to the verify
wedge. Freeze new Fabric milestones until a measured benefit is shown.

- Keep: direct-by-default routing; the toolbelt least-privilege model
  (zero-tools-start, role-scoped allowlist, honest `approximated` /
  `unsupported-critical` labels); removal of the evidence-curator role; risk
  gates as first-class design constructs.
- Change: subordinate the profile/role taxonomy to the verify wedge and wire the
  retirement rule to a real measurement loop; stop implying "hard allowlist
  where supported" is enforced for harnesses where execution collapses to a
  shell and render/smoke/status are prompt-approximated; reframe the Fabric as
  planning scaffold that does not execute.
- Add: one real direct-vs-governed paired dogfood (V126); compile-time MCP
  tool-definition pinning/hashing for over-privilege and tool-poisoning; a static
  multi-hop delegation-chain invariant checker.

### 5.2 Operating system (DWM control plane)

Verdict: the layered non-executing decomposition and bounded packet loop are
sound and ahead-of-category, but the Runner-as-independent-observer is the
load-bearing component and is currently fixture/dry-run only, while standards
alignment exists only as prose. A non-executing verifier inherits the trust
level of its capture layer: without an independent observer, every verdict is A0
and the chain is theater.

- Keep: the layered non-executing control plane and bounded packet loop;
  determinism scoped to the control plane; the A0->A3 assurance ladder
  (no self-upgrade); artifacts/source-hashes as the single source of truth.
- Change: replace the bespoke `kind`/SHA-256 evidence format with in-toto/ITE-6
  Statements in DSSE envelopes and map fields to OTel GenAI semconv (V128); stop
  the "hash-signed"/"tamper-evident" language for what is SHA-256
  content-addressing; demote the Adversarial Check to advisory and make a
  required-but-unevaluated claim yield inconclusive, never pass (V127); decouple
  package SemVer from the internal milestone count, collapse the script sprawl to
  the promised small surface, make the package the single schema authority, and
  publish to PyPI.
- Add: promote the Runner to a genuine independent observer producing A1+
  evidence (transcripts, diffs, test output, command receipts captured outside
  agent reach); define A3 concretely as a DSSE-wrapped in-toto attestation signed
  via Sigstore; consume static signable protocol artifacts (A2A Signed Agent
  Cards, MCP tool manifests, delegation claims) as offline-checkable verifier
  inputs; crosswalk evidence to live regulatory anchors.

## 6. Forward roadmap

The ordering principle: the next real milestone is a **run**, not a document.
V126 must produce real captured evidence before V127-V129 are treated as more
than specs.

### 6.1 Now

- **V126 — Real paired dogfood evidence.** Spec: `docs/v126-paired-dogfood-evidence-spec.md`.
  Run one localized coding task once directly under a harness and once through an
  Agent Fabric profile; capture both; run capture -> verify on the real
  artifacts; record escaped-defect / review-precision / missing-evidence /
  elapsed deltas, even at n=1. Replace the inline-fabricated dogfood input in the
  paired-evidence self-test with this captured fixture. Requires zero change to
  "Core does not execute": a human or harness runs the agent; Depone verifies the
  capture.
- **V127 — Verify-claim honesty.** Spec: `docs/v127-verify-claim-honesty-spec.md`.
  Demote the Adversarial Check to an advisory, calibrated signal (or rename it a
  ground-truth presence check); implement claim-evaluation states so a
  required-but-unevaluated claim yields inconclusive; correct README/SKILL so
  "verify" means the three deterministic checks; stop "hash-signed" language for
  content-addressing; correct the regulatory thesis (see 6.2).

### 6.2 Now (documentation correction folded into V127)

The V104 regulatory forcing function is stale and must be corrected everywhere it
appears. The EU AI Act high-risk obligations were postponed (Annex III to late
2027, Annex I to 2028) and the Colorado AI Act was repealed/replaced and pushed
to early 2027. The live anchors are GPAI obligations (in force since 2025-08),
EU AI Act Article 12 logging plus Article 19 six-month retention (Article 19, not
Article 12, carries the retention floor), and ISO/IEC 42001 plus procurement
diligence. Message 2026 demand as a voluntary/procurement-driven pull, not a
deadline sprint.

### 6.3 Next

- **V128 — Consensus evidence substrate.** Spec:
  `docs/v128-evidence-substrate-spec.md`. Map A0-A3 and the capture manifest to
  in-toto/ITE-6 Statements in DSSE envelopes (Sigstore/Rekor-able), and add OTel
  GenAI `gen_ai.*` span fields to the evidence/scoring schema. Stay stdlib-only by
  emitting the JSON shapes; do not add a dependency.
- **V129 — Runner as independent observer.** (Spec to be written when V126/V128
  land.) Promote the Runner to capture A1+ evidence outside agent reach, and make
  every report state which component produced each observation. This is what turns
  "A0 until observed" from a limitation into the product's core value.
- **Consolidation (no new number required).** Execute the unmet V104 promise:
  collapse the 100+ scripts to the small command surface, decouple package SemVer
  from the milestone count, make the package the single schema authority, and
  publish to PyPI.

### 6.4 Later

- Define A3 as a DSSE-wrapped in-toto attestation signed via Sigstore (Fulcio
  keyless + Rekor transparency log).
- Build the static multi-hop / recursive delegation-chain invariant checker
  (who authorized which agent for which action at which hop) — a differentiator
  precisely because runtime protocols cannot yet prove it.
- Compile-time MCP tool-definition pinning/over-privilege flagging.
- Strengthen the Adversarial Check toward an independent ground-truth refutation
  protocol, kept strictly advisory and never overriding deterministic checks.

### 6.5 Frozen until measured benefit

New Agent Fabric profile/role/toolbelt milestones (no further gate-on-gate work)
are frozen until V126 produces a measured benefit for at least one task class.
The Fabric's own agent-team-spec already says profiles are retired when benefit
is absent; honor that by gating investment on measurement.

## 7. Meta-discipline (for the next agent)

Do not let this roadmap become more scaffolding. If you are an agent reading this
and you are about to write `docs/v130-*-spec.md` instead of executing V126,
stop. The project does not need another contract layer; it needs one real
captured run that tests whether governed beats direct. Source-only milestones
that "add no execution and no trust upgrade" are the failure mode this document
exists to break.

A new milestone is justified only if it increases one of: real runs captured as
evidence, portability/audit-grade of that evidence, fewer over-claims in
user-facing text, or honest assurance. It is drift if it mostly adds names,
gates, reports, or version numbers without making a real run easier to execute,
verify, or trust.

## 8. Integrity notes (limits of this evaluation)

- One of the seven research dimensions ("orchestration-patterns") initially
  failed silently and returned fixture content; it was re-researched from real,
  resolvable sources before Section 3 was written.
- Adversarial fact-checking flagged a fabricated standard ("NIST AI RMF 1.1, Mar
  2026") which was excluded, and corrected the EU AI Act / Colorado dates and the
  Article 12 vs 19 attribution used in Section 6.2.
- The "governance blocks deals like SOC 2" procurement-gate claim is
  vendor-sourced and is treated as a directional signal only, not analyst-grade
  fact.
- Market-sizing and adoption percentages in the underlying research are
  vendor/analyst estimates; this roadmap does not depend on any of them.

## 9. Source index

Agent teams / orchestration:

- Anthropic, "Building Effective Agents" (2024-12-19):
  <https://www.anthropic.com/engineering/building-effective-agents>
- Anthropic, "How we built our multi-agent research system" (2025-06-13):
  <https://www.anthropic.com/engineering/multi-agent-research-system>
- Cognition (Walden Yan), "Don't Build Multi-Agents" (2025-06-12):
  <https://cognition.com/blog/dont-build-multi-agents>
- Anthropic, "Effective context engineering for AI agents" (2025-09-29):
  <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- OpenAI Agents SDK multi-agent orchestration:
  <https://openai.github.io/openai-agents-python/multi_agent/>
- LangGraph multi-agent architectures:
  <https://www.langchain.com/blog/benchmarking-multi-agent-architectures>
- CrewAI processes (sequential vs hierarchical):
  <https://docs.crewai.com/en/concepts/processes>
- Microsoft Agent Framework overview:
  <https://learn.microsoft.com/en-us/agent-framework/overview/>
- Google ADK multi-agent:
  <https://developers.googleblog.com/en/agent-development-kit-easy-to-build-multi-agent-applications/>
- Anthropic Claude Code subagents and agent teams:
  <https://code.claude.com/docs/en/sub-agents>

Evals / verification:

- Jason Wei, "Asymmetry of verification and verifier's law" (2025-07):
  <https://www.jasonwei.net/blog/asymmetry-of-verification-and-verifiers-law>

Agent-ops / observability / interop / provenance:

- OpenTelemetry GenAI semantic conventions:
  <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- Model Context Protocol: <https://modelcontextprotocol.io/>
- in-toto attestation framework: <https://github.com/in-toto/attestation>
- SLSA provenance: <https://slsa.dev/spec/v1.1/provenance>
- Sigstore: <https://www.sigstore.dev/>
- OWASP GenAI / Agentic security: <https://genai.owasp.org/>

Determinism:

- Thinking Machines Lab, "Defeating Nondeterminism in LLM Inference"
  (2025-09-10): <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>

Regulation:

- EU AI Act (Article 12 record-keeping, Article 19 log retention):
  <https://artificialintelligenceact.eu/>
- ISO/IEC 42001: <https://www.iso.org/standard/42001>

Competitive (named, analyst-sourced where no free canonical URL exists):

- Microsoft Conductor, ASSERT, and the Agent Control Stack (MIT-licensed
  cross-framework design+verify+control tooling), and the Forrester "agent
  control plane" / Govern-plane category (2025-12) are referenced from the
  evaluation research; treat the analyst framing as directional.
