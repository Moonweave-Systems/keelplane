# V95 Control Deck Score History Spec

Status: implemented operator-readiness history in
`scripts/dwm_control_deck_score_history.py`.

## Research and Prior Art

V94 produced one Control Deck readiness score. V95 turns those score artifacts
into a small history ledger so DWM can show readiness movement over time without
pretending it has a public benchmark trend.

## Product Position and Non-Goals

V95 is an internal readiness-history layer. It is useful for operator status,
workflow continuity, and future visual inspection. It is not a public benchmark
graph, an external score, or a model-superiority claim.

Non-goals:

- do not publish benchmark performance,
- do not claim upward product quality,
- do not score model quality,
- do not execute commands,
- do not create worktrees or sessions,
- do not bypass V94 claim policy.

## Workflow Architecture

`scripts/dwm_control_deck_score_history.py` reads one or more V94
`control-deck-score.json` directories and emits:

- `control-deck-score-history.json`,
- `control-deck-score-history.md`,
- `control-deck-score-history.svg`,
- `status.json`.

Each entry records the score id, decision, readiness percent, blocker count,
source path, and source hash. The history also records a readiness delta, but
the claim policy keeps `is_public_benchmark: false` and
`is_upward_trend_claim: false`.

## Execution Model

Run fixture coverage:

```bash
python scripts/dwm_control_deck_score_history.py --self-test
python scripts/dwm_control_deck_score_history.py --manifest fixtures/v95/manifest.json --out out/control-deck-score-history/v95-final
```

Run canonical history:

```bash
python scripts/dwm_control_deck_score_history.py build --score out/control-deck-scores/v94-canonical --out out/control-deck-score-history/v95-canonical
```

## Safety and Verification Gates

V95 blocks when:

- a score artifact is missing or stale against `status.json`,
- a score claims public benchmark status,
- a score claims upward trend status,
- labels are duplicated,
- numeric score fields are invalid.

## Evaluation Fixtures

`fixtures/v95/manifest.json` covers:

- ready history over two score records,
- unsafe public benchmark claim,
- unsafe upward trend claim,
- duplicate labels.

## Release Plan

V95 adds readiness-history generation to the changed-surface contract tier. It
can feed an internal graph, but public benchmark graph promotion remains gated
by the older benchmark-specific promotion path.
