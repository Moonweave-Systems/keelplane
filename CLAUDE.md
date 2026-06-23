# Depone — Agent Context

Depone (engine: **DWM Core**, the Deterministic Workflow Machine) is a
control-plane for large AI-native work: workflow design, packet compilation,
bounded runner gates, review/repair evidence, and scoring artifacts. The tooling
is pure-stdlib Python under `scripts/` plus one `.cjs` reference implementation.
The installed skill is `depone`; the entry doc is `SKILL.md`.

This file exists so a cloud agent that clones the repo with no other context
knows how to work here. Keep it short and current.

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
- Keep planned work and executed work separate — never present an unrun step as
  done. This is the core discipline the tool enforces; respect it in your own
  changes.

## Commit style

Imperative subject focused on *why*, not what. One commit per logical change.
Do not amend existing commits.
