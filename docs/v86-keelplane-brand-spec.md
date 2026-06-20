# V86 Keelplane Brand Spec

Status: implemented first Keelplane brand decision in `README.md`,
`docs/dwm-branding.md`, and `assets/dwm-hero.svg`.

V86 set the public product brand to **Keelplane** while preserving DWM Core as
the internal deterministic engine name. The deliberate migration gate has now
made `keelplane` the installed Codex skill name.

## Decision

- Public product brand: `Keelplane`.
- Internal engine name: `DWM Core`.
- Expanded internal name: `Deterministic Workflow Machine`.
- Skill name: `keelplane`.
- Repository slug: `dwm` until a dedicated migration gate changes it.

## Rationale

Keelplane keeps the useful "keel" meaning: centerline, stability, and direction
control. It also reads naturally next to "control-plane", which matches the
product's actual architecture. Lightweight npm, PyPI, DNS, and web checks found
less collision risk for `keelplane` than for `keel`, `helm`, `vector`,
`northstar`, or `forge`.

## Non-Goals

- Do not rename CLI commands, fixture IDs, schema fields, or generated artifact
  names in this slice.
- Do not rename the `dwm_*.py` file prefix in this slice.
- Do not move the GitHub repository or package slugs.
- Do not claim autonomous execution, agent superiority, or benchmark uplift
  from a branding change.

## Reader-Facing Copy

```text
Keelplane
A deterministic control-plane for large AI-native work.
```

Secondary copy:

```text
Keelplane is powered by DWM Core, the deterministic workflow engine behind its
plans, packets, gates, evidence, reviews, and resume state.
```

## Verification

V86 is complete when:

- README first screen says `Keelplane`;
- `docs/dwm-branding.md` names Keelplane as the public product brand;
- `assets/dwm-hero.svg` renders `Keelplane` and `Powered by DWM Core`;
- release text, README quality, whitespace, skill validation, and contract
  checks still pass.
