# V20 1.0 Release Hardening Decision

Decision: keep

Command used to regenerate the V20 summary:

```bash
python scripts/dwm_release.py --manifest fixtures/v20/manifest.json --out out/release/v20-final
```

Generated summary values:

- `suite_id`: `v20-final`
- `fixture_count`: 5
- `required_fixture_count`: 5
- `required_passed`: 5
- `passed`: 5
- `failed`: 0
- `skipped`: 0
- `decision`: `keep`

This decision covers 1.0 release-candidate hardening gates only. It does not
claim hosted distribution, live Codex execution, live Claude execution, OMX
support, production deployment, or autonomous execution without gates.
