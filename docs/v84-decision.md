# V84 Decision

Decision: keep.

V84 keeps the installed surface audit because it turns the current update
question into deterministic evidence. The active Codex session can be checked
against the repo-backed `SKILL.md`, copied installs can be detected, and stale
copies block instead of being silently treated as current.

## Evidence

- `python scripts/dwm_installed_surface_audit.py --self-test`
- `python scripts/dwm_installed_surface_audit.py --manifest fixtures/v84/manifest.json --out out/installed-surface-audits/v84-final`
- `python scripts/dwm_installed_surface_audit.py audit --active-skill SKILL.md --out out/installed-surface-audits/v84-canonical`

Manifest result:

- `suite_id`: `v84-installed-surface-audit`
- `fixture_count`: 4
- `required_passed`: 4
- `decision`: `keep`

Canonical result:

- `decision`: `installed_copy_synced`
- `~/.codex/skills/depone/SKILL.md` resolves through a symlink to the repo `SKILL.md`
- stale copied installs would be `blocked`

This does not claim automatic package update behavior. It only proves the
current active local skill path is repo-backed, the detected installed skill
surface resolves to the same repo, and copied install drift is detectable before
execution.
