# V30 Live Receipt Ingestion Spec

Status: implemented first live receipt ingestion gate in
`scripts/dwm_live_receipt.py`.

## Research and Prior Art

V29 stops at `ready-for-human-run`. V30 accepts a receipt from a human or
external runner and binds it back to the preflight command hash. This gives DWM
execution evidence without granting the system autonomous live execution.

## Product Position and Non-Goals

V30 is a receipt-ingestion gate. It validates that a receipt matches a ready
preflight command and records a ledger. It does not execute the command and does
not claim benchmark success.

Non-goals:

- do not execute live model attempts,
- do not claim live Codex task success,
- do not infer correctness from a zero return code,
- do not accept receipts for skipped or blocked preflights,
- do not accept receipt command hashes that do not match preflight.

## Workflow Architecture

`scripts/dwm_live_receipt.py` reads a V29 preflight directory and a receipt JSON,
then writes:

- `receipt.json`,
- `receipt-ledger.json`,
- `status.json`,
- `summary.json` for manifest suites.

The ledger stores hashes for preflight, receipt, and command.

## Execution Model

```bash
python scripts/dwm_live_receipt.py ingest --preflight out/live-runner-preflight/<preflight_id> --receipt receipt.json --out out/live-receipts/<receipt_id>
python scripts/dwm_live_receipt.py --manifest fixtures/v30/manifest.json --out out/live-receipts/v30-final
```

Every output directory is guarded by a live-receipt ownership sentinel.

## Safety and Verification Gates

The gate blocks:

- `ERR_LIVE_RECEIPT_PREFLIGHT_NOT_READY` when preflight is not
  `ready-for-human-run`,
- `ERR_LIVE_RECEIPT_STALE_PREFLIGHT` when expected preflight hash does not
  match,
- `ERR_LIVE_RECEIPT_COMMAND_MISMATCH` when receipt command hash does not match,
- `ERR_LIVE_RECEIPT_ARTIFACT_MISSING` when required preflight artifacts are
  missing.

## Evaluation Fixtures

`fixtures/v30/manifest.json` covers:

- positive: receipt is accepted for a ready preflight,
- negative: skipped preflight is blocked,
- negative: stale preflight hash is blocked,
- negative: mismatched command hash is blocked,
- negative: missing artifact is blocked.

## Release Plan

V30 preserves the boundary between planning and execution. Later slices can
ingest real Codex receipts and then map accepted receipts into V26-style
attempt ledgers and benchmark scoring.
