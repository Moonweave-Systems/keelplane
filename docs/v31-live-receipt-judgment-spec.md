# V31 Live Receipt Judgment Spec

Status: implemented first live receipt judgment gate in
`scripts/dwm_live_receipt_judge.py`.

## Research and Prior Art

V30 accepts a receipt and binds it to a V29 preflight command hash. V31 adds the
next control-plane boundary: it judges whether the accepted receipt is internally
consistent and records the runner return-code outcome without treating it as a
benchmark score.

## Product Position and Non-Goals

V31 is a receipt judgment gate. It converts an accepted receipt into a
`judgment.json` artifact and separates runner outcome from benchmark success.

Non-goals:

- do not execute live model attempts,
- do not infer task correctness from a zero return code,
- do not claim benchmark success,
- do not accept stale receipt ledgers,
- do not score model quality.

## Workflow Architecture

`scripts/dwm_live_receipt_judge.py` reads a V30 receipt directory containing
`receipt.json`, `receipt-ledger.json`, and `status.json`, then writes:

- `judgment.json`,
- `status.json`,
- `summary.json` for manifest suites.

The judgment stores hashes for the receipt, ledger, and inherited V30 sources.

## Execution Model

```bash
python scripts/dwm_live_receipt_judge.py judge --receipt-dir out/live-receipts/<receipt_id> --out out/live-receipt-judgments/<judgment_id>
python scripts/dwm_live_receipt_judge.py --manifest fixtures/v31/manifest.json --out out/live-receipt-judgments/v31-final
```

Every output directory is guarded by a live-receipt-judgment ownership sentinel.

## Safety and Verification Gates

The gate blocks:

- `ERR_LIVE_RECEIPT_JUDGE_ARTIFACT_MISSING` when required receipt artifacts are
  missing,
- `ERR_LIVE_RECEIPT_JUDGE_STALE_RECEIPT` when receipt status and ledger drift
  or expected receipt hash does not match,
- `ERR_LIVE_RECEIPT_JUDGE_RECEIPT_NOT_ACCEPTED` when V30 did not accept the
  receipt,
- `ERR_LIVE_RECEIPT_JUDGE_HASH_MISMATCH` when the receipt hash no longer
  matches the ledger.

## Evaluation Fixtures

`fixtures/v31/manifest.json` covers:

- positive: zero returncode receipt is judged,
- positive: nonzero returncode receipt is judged as nonzero evidence,
- negative: stale receipt hash is blocked,
- negative: receipt not accepted is blocked,
- negative: receipt hash mismatch is blocked,
- negative: missing receipt artifact is blocked.

## Release Plan

V31 keeps live evidence adjudication separate from scoring. Later slices can map
`judgment.json` into benchmark scoring only after an explicit verifier compares
task-specific outputs against expected artifacts.
