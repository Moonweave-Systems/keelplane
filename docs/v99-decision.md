# V99 Decision

Decision: keep.

Command:

```bash
python scripts/dwm_wave_receipt.py --manifest fixtures/v99/manifest.json --out out/wave-receipts/v99-final
```

Expected summary:

- `suite_id`: `v99-wave-receipt`
- `fixture_count`: 4
- `required_passed`: 4
- `decision`: `keep`

The canonical record command is:

```bash
python scripts/dwm_wave_receipt.py record --wave out/wave-operators/v98-canonical/wave-operator.json --acquisition out/dogfood-acquisitions/v61-final/summary.json --out out/wave-receipts/v99-canonical
```

V99 keeps the next step grounded in real dogfood acquisition evidence. It does
not execute commands or publish benchmark claims, and public benchmark graph
publication still requires promotion evidence and human review.

The V99 wave receipt does not execute commands.
