# V98 Decision

Decision: keep.

Command:

```bash
python scripts/dwm_wave_operator.py --manifest fixtures/v98/manifest.json --out out/wave-operators/v98-final
```

Expected summary:

- `suite_id`: `v98-wave-operator`
- `fixture_count`: 4
- `required_passed`: 4
- `decision`: `keep`

The canonical select command is:

```bash
python scripts/dwm_wave_operator.py select --readiness out/benchmark-readiness/v97-canonical/benchmark-readiness.json --activation out/workflow-activations/v90-canonical/workflow-activation.json --out out/wave-operators/v98-canonical
```

V98 selects `dogfood-evidence-wave` while public benchmark publication remains
blocked. Public benchmark graph publication still requires promotion evidence
and human review, and the wave operator does not execute commands.
