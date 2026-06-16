# V31 Live Receipt Judgment Decision

Decision: keep

Command used to regenerate the V31 summary:

```bash
python scripts/dwm_live_receipt_judge.py --manifest fixtures/v31/manifest.json --out out/live-receipt-judgments/v31-final
```

Generated summary values:

- `suite_id`: `v31-final`
- `fixture_count`: 6
- `required_fixture_count`: 6
- `required_passed`: 6
- `passed`: 6
- `failed`: 0
- `skipped`: 0
- `decision`: `keep`

The accepted V31 suite covers `judgment.json`,
`ERR_LIVE_RECEIPT_JUDGE_ARTIFACT_MISSING`,
`ERR_LIVE_RECEIPT_JUDGE_STALE_RECEIPT`,
`ERR_LIVE_RECEIPT_JUDGE_RECEIPT_NOT_ACCEPTED`, and
`ERR_LIVE_RECEIPT_JUDGE_HASH_MISMATCH`.

This decision covers receipt judgment only. It does not claim live model
execution, live Codex task success, Claude execution, OpenCode/OMO execution,
hosted evaluation, benchmark scoring, or benchmark success.
