# V99 Wave Receipt Spec

Status: implemented wave receipt.

V99 adds `scripts/dwm_wave_receipt.py`, a source-only receipt that connects the
V98-selected `dogfood-evidence-wave` with V61 dogfood acquisition evidence. It
answers whether the selected wave has usable evidence attached without claiming
that a public benchmark graph is ready.

The tool writes `wave-receipt.json`, `wave-receipt.md`, and `status.json` under
`out/wave-receipts/<receipt_id>`.

## Command

```bash
python scripts/dwm_wave_receipt.py --manifest fixtures/v99/manifest.json --out out/wave-receipts/v99-final
python scripts/dwm_wave_receipt.py record --wave out/wave-operators/v98-canonical/wave-operator.json --acquisition out/dogfood-acquisitions/v61-final/summary.json --out out/wave-receipts/v99-canonical
```

## Decision Model

V99 records `wave_receipt_ready` only when:

- the V98 wave operator is `wave_ready`;
- the selected wave is `dogfood-evidence-wave`;
- the dogfood acquisition decision is `keep`;
- required acquisition fixtures passed.

It blocks if the wave is not ready, the selected wave is not dogfood evidence,
or the acquisition evidence is not keep.

## Safety

The wave receipt does not execute commands, create worktrees, use the network,
or publish benchmark claims. It records that evidence acquisition progressed.
Public benchmark graph publication still requires promotion evidence and human
review.

Public benchmark graph publication still requires promotion evidence and human review.

The receipt policy includes:

- `wave_receipt_is_public_benchmark: false`
- `requires_promotion_for_public_graph: true`
- `requires_human_review_for_readme_publication: true`

## Fixtures

`fixtures/v99/manifest.json` covers:

- ready wave receipt;
- blocked wave;
- wrong selected wave;
- blocked acquisition.

## Contract

V99 adds wave receipt validation to the changed-surface contract tier and
product doctor command corpus. Generated `out/` receipt directories remain
verification evidence, not source truth.
