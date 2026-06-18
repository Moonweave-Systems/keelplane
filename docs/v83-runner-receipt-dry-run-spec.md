# V83 Runner Receipt Dry-Run Spec

Status: implemented runner receipt dry-run gate in
`scripts/dwm_runner_receipt_dry_run.py`.

V83 proves that DWM can produce a schema-valid execution receipt without
executing the queued command. It consumes the V82 schema and V81 batch, writes a
dry-run receipt, and keeps `executed: false`.

## Inputs

The canonical dry-run consumes:

- `out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json`;
- `out/multi-slice-batches/v81-canonical/multi-slice-batch.json`.

## Outputs

The gate writes `runner-receipt.json`, `runner-receipt.md`, `status.json`, and
manifest `summary.json` under `out/runner-receipt-dry-runs/`.

## Safety

V83 does not execute commands, run live adapters, create worktrees, install
dependencies, use network, read secrets, deploy, delete files, touch databases,
send external messages, or rewrite history. It only creates a receipt-shaped
dry-run artifact. Actual execution remains behind the V84 human gate.

## Release Commands

```bash
python scripts/dwm_runner_receipt_dry_run.py --self-test
python scripts/dwm_runner_receipt_dry_run.py --manifest fixtures/v83/manifest.json --out out/runner-receipt-dry-runs/v83-final
python scripts/dwm_runner_receipt_dry_run.py dry-run --schema out/execution-receipt-schemas/v82-canonical/execution-receipt-schema.json --batch out/multi-slice-batches/v81-canonical/multi-slice-batch.json --out out/runner-receipt-dry-runs/v83-canonical
```
