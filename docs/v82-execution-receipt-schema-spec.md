# V82 Execution Receipt Schema Spec

Status: implemented execution receipt schema preflight in
`scripts/dwm_execution_receipt_schema.py`.

V82 defines the receipt contract required before DWM can move toward actual
queued command execution. It is schema-only. It does not execute queued
commands, run live adapters, create worktrees, install dependencies, use
network, read secrets, deploy, delete files, touch databases, send external
messages, or rewrite history.

## Inputs

The canonical preflight consumes
`out/multi-slice-batches/v81-canonical/multi-slice-batch.json`.

## Outputs

The preflight writes `execution-receipt-schema.json`,
`execution-receipt-schema.md`, `sample-receipt.json`, `status.json`, and
manifest `summary.json` under `out/execution-receipt-schemas/`.

## Receipt Contract

Required fields include `receipt_id`, `status`, `execution_mode`, `adapter`,
`command`, `executed`, `exit_code`, `artifacts`, `verification`, `risk_codes`,
`blocked_by`, and `source_hashes`.

Dry-run receipts must use `executed: false`. A receipt cannot claim success
without evidence, public benchmark status, model superiority, or execution by
claim. Actual execution remains behind the V84 human gate.

## Release Commands

```bash
python scripts/dwm_execution_receipt_schema.py --self-test
python scripts/dwm_execution_receipt_schema.py --manifest fixtures/v82/manifest.json --out out/execution-receipt-schemas/v82-final
python scripts/dwm_execution_receipt_schema.py preflight --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/execution-receipt-schemas/v82-canonical
```
