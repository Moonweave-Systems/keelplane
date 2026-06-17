# V65 Dogfood Chart Render Spec

Status: implemented reviewed local dogfood chart rendering in
`scripts/dwm_dogfood_chart_render.py`.

## Research and Prior Art

V64 can produce a clean pair root that V58 accepts as graph-ready. V59 can turn
that series into a chart candidate, and V60 can approve the candidate with a
human review receipt. V65 renders only after that review exists.

## Product Position and Non-Goals

V65 is a local render step for reviewed dogfood chart candidates. It is not a
README promotion step and does not make public benchmark claims.

Non-goals:

- do not render unreviewed chart candidates,
- do not publish README graph assets,
- do not mark `public_readme_ready` true,
- do not ignore stale review or candidate hashes,
- do not claim external benchmark authority.

## Workflow Architecture

The command is:

```bash
python scripts/dwm_dogfood_chart_render.py render --review out/dogfood-chart-reviews/<review_id> --out out/dogfood-chart-renders/<render_id>
```

It reads:

- `chart-review.json`,
- matching review `status.json`,
- the hash-bound `chart-candidate.json`.

It writes:

- `chart-render.json`,
- `chart-render.svg`,
- `chart-render.md`,
- `status.json`.

## Execution Model

The renderer validates the review, verifies the reviewed candidate hash, and
then renders a deterministic SVG bar chart of local delta seconds. The SVG
states that it is local evidence only and that README promotion remains gated.

## Safety and Verification Gates

The gate blocks:

- `ERR_DOGFOOD_CHART_RENDER_STALE_REVIEW`,
- `ERR_DOGFOOD_CHART_RENDER_OVERCLAIM`,
- `ERR_DOGFOOD_CHART_RENDER_STALE_CANDIDATE`,
- missing review or candidate artifacts,
- unsafe output, traversal, and symlink paths.

## Evaluation Fixtures

`fixtures/v65/manifest.json` covers:

- approved local render,
- stale review blocking,
- overclaim review blocking,
- stale candidate blocking.

## Release Plan

V65 creates the first reviewed local chart render artifact. README promotion
remains a later gate that should require explicit asset promotion and copy review.
