# V84 Installed Surface Audit Spec

Status: implemented installed surface audit gate in
`scripts/dwm_installed_surface_audit.py`.

V84 answers whether the workflow designer currently used by Codex is reading
the repo-backed `SKILL.md`, and whether any copied install surface is stale. It
does not install, update, execute adapters, create worktrees, or use network.

## Inputs

The canonical audit consumes:

- active skill path: `SKILL.md`;
- optional install candidates under `~/.codex/skills` and `~/.agents/skills`;
- source files for `source_hashes`: `SKILL.md`, `README.md`, and
  `scripts/dwm.py`.

## Outputs

The gate writes `installed-surface-audit.json`,
`installed-surface-audit.md`, `status.json`, and manifest `summary.json` under
`out/installed-surface-audits/`.

The JSON decision is one of:

- `repo_backed_active_surface`: the active session reads the repo `SKILL.md`
  and no copied install was detected;
- `installed_copy_synced`: copied install candidates exist and match the repo
  `SKILL.md` hash, including symlinked install surfaces that resolve back to
  the repo;
- `blocked`: the active skill is missing, the active skill drifts from the repo
  `SKILL.md`, or a copied install candidate is stale.

## Safety

V84 is audit-only. It does not modify installed skills, run queued commands,
attach sessions, create worktrees, execute live adapters, deploy, delete files,
read secrets, or rewrite history. A stale copied install is reported as a
blocker instead of being repaired automatically.

## Release Commands

```bash
python scripts/dwm_installed_surface_audit.py --self-test
python scripts/dwm_installed_surface_audit.py --manifest fixtures/v84/manifest.json --out out/installed-surface-audits/v84-final
python scripts/dwm_installed_surface_audit.py audit --active-skill SKILL.md --out out/installed-surface-audits/v84-canonical
```
