# V86 Depone Brand Spec

Status: implemented first Depone brand decision in `README.md`,
`docs/dwm-branding.md`, and `assets/dwm-hero.svg`.

V86 set the public product brand to **Depone** while preserving DWM Core as
the internal deterministic engine name. The deliberate migration gate has now
made `depone` the installed Codex skill name.

## Decision

- Public product brand: `Depone`.
- Internal engine name: `DWM Core`.
- Expanded internal name: `Deterministic Workflow Machine`.
- Skill name: `depone`.
- Repository slug: `dwm` until a dedicated migration gate changes it.

## Rationale

Depone keeps the control-plane association while avoiding stale public naming
that conflicts with the current product direction. It reads as a product layer
above DWM Core rather than a replacement for the deterministic engine.

## Non-Goals

- Do not rename CLI commands, fixture IDs, schema fields, or generated artifact
  names in this slice.
- Do not rename the `dwm_*.py` file prefix in this slice.
- Do not move the GitHub repository or package slugs.
- Do not claim autonomous execution, agent superiority, or benchmark uplift
  from a branding change.

## Reader-Facing Copy

```text
Depone
A deterministic control-plane for large AI-native work.
```

Secondary copy:

```text
Depone is powered by DWM Core, the deterministic workflow engine behind its
plans, packets, gates, evidence, reviews, and resume state.
```

## Verification

V86 is complete when:

- README first screen says `Depone`;
- `docs/dwm-branding.md` names Depone as the public product brand;
- `assets/dwm-hero.svg` renders `Depone` and `Powered by DWM Core`;
- release text, README quality, whitespace, skill validation, and contract
  checks still pass.
