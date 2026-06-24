# Depone - Agent Context

Depone (engine: **DWM Core**, the Deterministic Workflow Machine) is a
control-plane for large AI-native work: workflow design, packet compilation,
bounded runner gates, review/repair evidence, and scoring artifacts. The tooling
is pure-stdlib Python under `scripts/` plus one `.cjs` reference implementation.
The installed skill is `depone`; the entry doc is `SKILL.md`.

This file exists so Codex Cloud or local Codex agents that clone the repo with
no other context know how to work here. Keep it short and current.

## Current direction (read first)

`docs/v125-direction-check-roadmap.md` is the current product-direction source of
truth (post-V124). Bottom line: keep the non-executing design+verify plane (the
one defensible moat) and narrow hard. The next real milestone is a run, not
another source-only contract layer:

- V126 (`docs/v126-paired-dogfood-evidence-spec.md`): capture one real
  direct-vs-governed run; stop pointing the paired-evidence path at synthetic
  seeds.
- V127 (`docs/v127-verify-claim-honesty-spec.md`): demote the Adversarial Check
  to advisory; a required-but-unevaluated claim must be `inconclusive`, never
  `pass`; correct "hash-signed" wording and the stale regulatory thesis.
- V128 (`docs/v128-evidence-substrate-spec.md`): emit evidence as in-toto/DSSE
  plus OTel GenAI shapes, stdlib-only.

Do not add another `vNNN` source-only meta layer instead of executing V126. New
Agent Fabric profile/role/toolbelt milestones are frozen until V126 shows a
measured benefit for at least one task class.

## Verify after any change

Run before claiming work is done or opening a PR:

```bash
python scripts/check_contract.py --tier changed   # release contract (changed tier)
python scripts/dwm.py doctor                       # operator-state sanity
python scripts/check_readme_quality.py README.md   # only if README changed
```

Full contract sweep: `python scripts/check_contract.py`. Many scripts also carry
a `--self-test`; run the one for any script you touch.

## Invariants

- **No external dependencies.** Scripts use the Python standard library only.
  Never add a third-party package, a requirements/pyproject file at the root, or
  a new runtime to make something work.
- Type hints on all new function signatures; prefer `str | None` over
  `Optional[str]`. Use f-strings, not `.format()` or `%`.
- Artifacts and source hashes are the source of truth. Never hand-edit generated
  files under `out/` or fixtures under `fixtures/` to make a check pass.
- Keep planned work and executed work separate - never present an unrun step as
  done. This is the core discipline the tool enforces; respect it in your own
  changes.

## Commit style

Imperative subject focused on *why*, not what. One commit per logical change.
Do not amend existing commits.
