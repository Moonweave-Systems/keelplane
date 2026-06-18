# V83 Runner Receipt Dry-Run Decision

Decision: keep

Command used:

```bash
python scripts/dwm_runner_receipt_dry_run.py --manifest fixtures/v83/manifest.json --out out/runner-receipt-dry-runs/v83-final
```

Generated values:

- `suite_id`: `v83-runner-receipt-dry-run`
- `fixture_count`: 3
- `required_fixture_count`: 3
- `required_passed`: 3
- `passed`: 3
- `failed`: 0
- `decision`: `keep`

V83 creates a schema-valid dry-run receipt with `executed: false`. It does not
run queued commands or live adapters. V84 remains the first human gate for
actual execution.
