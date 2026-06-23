# V106 Decision

Decision: keep for optional multi-wave execution-path validation.

Command used to verify the fixture suite:

```bash
python scripts/v106_multi_wave.py --self-test
```

Recorded deterministic suite:

- `suite_id`: `v106-multi-wave`
- `fixture_count`: 6
- `required_passed`: 6
- `v105_wave_1_cases`: 4
- `decision`: `keep`

V106 keeps `first_slice` compatibility while adding validated optional
`first_wave` and `waves` fields for bounded multi-wave handoff contracts. The
canonical `wave-1` receipt is backed by V105 cases `missing-test-log`,
`forbidden-file-touch`, `test-weakened`, and `good`; `wave-2` unlocks only after
those verified/refuted verdicts and evidence-contract codes match expectations.
