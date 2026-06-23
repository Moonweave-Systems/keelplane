# V87 Brand Boundary Audit Spec

Status: implemented brand boundary audit in `scripts/dwm_brand_boundary_audit.py`.

## Objective

Protect the V86 Depone brand decision from drifting back into ambiguous
public DWM naming while enforcing the single current skill identity.

## Product Boundary

- Public product brand: `Depone`.
- Internal engine name: `DWM Core`.
- Skill name: `depone`.
- Repository slug remains `dwm`.
- Existing CLI commands and artifact paths are not renamed in V87.

## Audit Rules

The audit reads public source surfaces and emits `brand-boundary-audit.json`,
`brand-boundary-audit.md`, and `status.json`.

It blocks when:

- README does not lead with `# Depone`.
- Public docs regress to `# DWM` or `# DWM Branding` headings.
- The skill name is dropped from the brand boundary.
- The internal `DWM Core` engine name is dropped.
- The copy claims autonomous execution or live command execution.

## Execution Policy

V87 is audit-only. It does not rename package paths, does not execute adapter
commands, does not create worktrees, and does not claim autonomous execution.

## Verification

- `python scripts/dwm_brand_boundary_audit.py --self-test`
- `python scripts/dwm_brand_boundary_audit.py --manifest fixtures/v87/manifest.json --out out/brand-boundary-audits/v87-final`
- `python scripts/dwm_brand_boundary_audit.py audit --out out/brand-boundary-audits/v87-canonical`
