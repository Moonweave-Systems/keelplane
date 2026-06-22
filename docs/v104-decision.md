# V104 Decision

Decision: **proceed with V104 product direction** — reposition Keelplane from
"control-plane above agent CLIs" to "workflow designer + cross-platform
evidence verifier."

## Rationale

1. **Conductor validated the market.** Microsoft proved deterministic
   multi-agent orchestration is real, not just theoretical.
2. **Conductor opened a distribution channel.** Every Conductor user needs
   verification. Keelplane can be that layer.
3. **The evidence gap is acknowledged.** LangGraph, Semantic Kernel, and CrewAI
   communities all have live threads asking for auditable evidence receipts.
4. **The differentiation is real.** No tool in the evidence-governance niche
   (GATE, StepProof, Agentic Evidence Suite) does workflow design. No workflow
   designer (Dify, LangGraph) does evidence verification.
5. **Window is finite (6-12 months).** LangGraph may add evidence receipts.
   Ship the CLI, then open source.

## What We Stop Doing

- Building an execution engine (Conductor, LangGraph, Temporal already win)
- Writing more `dwm_*.py` scripts as standalone entry points
- Filling `out/` with self-referential evidence artifacts

## What We Start Doing

- `keelplane` CLI: 3 commands replacing 102 scripts
- Conductor adapter: compile to YAML + verify execution evidence
- Demo that works with `pip install keelplane && keelplane demo`
- Ship first, open source later

## Evidence That This Direction Is Correct

See `docs/v104-product-direction-spec.md` sections 11 (Non-Goals) and 12
(Risks). The competitive research (v104-research) confirms the gap exists, the
timing is right (EU AI Act Aug 2026), and the distribution channel exists
(Conductor).

## Next Action

Create `keelplane/` package skeleton wrapping existing DWM Core, then build
`keelplane design` and `keelplane demo`.
