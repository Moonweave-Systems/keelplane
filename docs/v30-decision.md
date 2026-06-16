# V30 Live Receipt Ingestion Decision

Decision: keep

Command used to regenerate the V30 summary:

```bash
python scripts/dwm_live_receipt.py --manifest fixtures/v30/manifest.json --out out/live-receipts/v30-final
```

Generated summary values:

- `suite_id`: `v30-final`
- `fixture_count`: 5
- `required_fixture_count`: 5
- `required_passed`: 5
- `passed`: 5
- `failed`: 0
- `skipped`: 0
- `decision`: `keep`

The accepted V30 suite covers `receipt.json`, `receipt-ledger.json`,
`ERR_LIVE_RECEIPT_PREFLIGHT_NOT_READY`, `ERR_LIVE_RECEIPT_STALE_PREFLIGHT`,
`ERR_LIVE_RECEIPT_COMMAND_MISMATCH`, and
`ERR_LIVE_RECEIPT_ARTIFACT_MISSING`.

This decision covers receipt ingestion only. It does not claim live model
execution, live Codex task success, Claude execution, OpenCode/OMO execution,
hosted evaluation, or benchmark success.
