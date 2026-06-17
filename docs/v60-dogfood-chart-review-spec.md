# V60 Dogfood Chart Review Spec

Status: implemented first local dogfood chart review gate in
`scripts/dwm_dogfood_chart_review.py`.

## Research and Prior Art

V59 creates local chart candidate data from a graph-ready dogfood pair series.
That is still not enough to render or publish a README graph. V60 adds a
human-review receipt gate with source hashes, so a later renderer can consume
only reviewed candidates.

## Product Position and Non-Goals

V60 is a review gate. It approves local chart candidates for later rendering,
not for public README promotion.

Non-goals:

- do not render a graph,
- do not publish README benchmark graphs,
- do not approve public README readiness,
- do not accept missing review receipts,
- do not accept stale chart candidate hashes,
- do not accept superiority or external benchmark claims.

## Workflow Architecture

The command is:

```bash
python scripts/dwm_dogfood_chart_review.py review --candidate out/dogfood-chart-candidates/<chart_id> --receipt review-receipt.json --out out/dogfood-chart-reviews/<review_id>
```

It reads `chart-candidate.json`, `status.json`, and a human review receipt.

It writes:

- `chart-review.json`,
- `chart-review.md`,
- `status.json`.

## Execution Model

The command does not run adapters, render graphs, edit README, or perform public
promotion. It verifies source hashes and records a local approval artifact.

## Safety and Verification Gates

The gate blocks:

- `ERR_DOGFOOD_CHART_REVIEW_RECEIPT_MISSING` when the review receipt is absent,
- `ERR_DOGFOOD_CHART_REVIEW_REJECTED` when the receipt is not approved,
- `ERR_DOGFOOD_CHART_REVIEW_STALE_RECEIPT` when the receipt hash no longer
  matches `chart-candidate.json`,
- `ERR_DOGFOOD_CHART_REVIEW_OVERCLAIM` when the receipt claims public README
  readiness or external superiority.

## Evaluation Fixtures

`fixtures/v60/manifest.json` covers:

- positive: approved receipt records a chart review,
- negative: missing receipt is blocked,
- negative: rejected receipt is blocked,
- negative: stale receipt is blocked,
- negative: overclaiming receipt is blocked.

## Release Plan

V60 creates the handoff artifact for a future local chart renderer. Public
README graph promotion still requires a later promotion gate.
