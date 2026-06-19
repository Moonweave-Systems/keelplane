# V95 Decision

Decision: keep.

Commands used to verify Control Deck score history:

- `python scripts/dwm_control_deck_score_history.py --self-test`
- `python scripts/dwm_control_deck_score_history.py --manifest fixtures/v95/manifest.json --out out/control-deck-score-history/v95-final`

Fixture evidence:

- `suite_id`: `v95-control-deck-score-history`
- `fixture_count`: 4
- `required_passed`: 4
- `decision`: `keep`

Covered blockers:

- Unsafe public benchmark claim blocks.
- Unsafe upward trend claim blocks.
- Duplicate labels block.

The V95 score history is operator readiness history. It is not a public benchmark graph and does not claim upward product quality.
