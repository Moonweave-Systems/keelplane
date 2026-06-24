# Depone Branding

Depone is the public product brand for this repository's agent workflow
control-plane.

DWM Core stands for **Deterministic Workflow Machine**. It is the internal
engine name for the deterministic plan, packet, gate, evidence, review, and
resume-state machinery behind Depone.

The Codex skill name is `depone`. The `dwm_*.py` script prefix remains
legacy/internal. The GitHub repository slug remains `keelplane` and is
intentionally deferred until a separate migration gate proves that changing
commands, remotes, paths, or install surfaces will not break users.

## Position

Depone is not an unchecked agent launcher. It is a deterministic
control-plane for large AI-assisted work:

```text
goal
-> workflow plan
-> packet
-> dispatch
-> result evidence
-> review
-> ingestion
-> next frontier
```

The defining rule is that artifacts and verification state are the source of
truth, not model claims.

## Short Description

Depone is a deterministic control-plane for large AI-native work. It turns
large goals into hashed plans, packets, dispatches, evidence, reviews, and
resumable runtime state without losing control of what has actually happened.

## Naming Rules

- Use **Depone** for the product and public-facing brand.
- Use **DWM Core** for the internal deterministic workflow engine.
- Use **Deterministic Workflow Machine** when expanding DWM Core in formal
  docs.
- Use `keelplane` for the GitHub repository slug until a dedicated migration gate
  changes it.
- Use `depone` for the Codex skill name and `created_by`
  contract values.
- Keep the `dwm_*.py` file prefix and GitHub repository slug as deferred
  legacy/internal surfaces.
- Do not rename existing fixture IDs or `workflow.plan.json` schema fields just
  for branding.
- Do not claim autonomous execution, agent superiority, or benchmark uplift
  from branding changes.
