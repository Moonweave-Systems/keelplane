# V67 Dogfood Progress Asset Promotion Spec

Status: implemented README process-progress asset promotion bundle in
`scripts/dwm_dogfood_progress_asset_promotion.py`.

## Research and Prior Art

V66 creates a process graph that can update even when there is no honest upward
benchmark trend. The missing product step is a controlled README asset bundle
for that process graph, separate from the benchmark promotion path.

## Product Position and Non-Goals

V67 promotes process-progress evidence only. It is not the benchmark trend
pipeline and it must not claim direct-agent superiority.

Non-goals:

- do not edit tracked README assets,
- do not publish upward benchmark claims,
- do not treat process progress as model or adapter superiority,
- do not accept stale `dogfood-progress.json` or `status.json`,
- do not accept SVGs missing process/non-benchmark claim text.

## Workflow Architecture

The command is:

```bash
python scripts/dwm_dogfood_progress_asset_promotion.py promote --progress out/dogfood-progress/<progress_id> --out out/dogfood-progress-asset-promotions/<promotion_id>
```

It reads:

- `dogfood-progress.json`,
- `status.json`,
- `dogfood-progress.svg`.

It writes:

- `asset-promotion.json`,
- `status.json`,
- `dwm-dogfood-progress.svg`,
- `dwm-dogfood-progress.json`,
- `README-snippet.md`,
- `asset-diff.md`.

## Execution Model

The bundle proposes tracked targets under `assets/` but writes only to
`out/dogfood-progress-asset-promotions/`. A later human-reviewed copy step may
use the bundle to update README-visible process progress assets.

## Safety and Verification Gates

The gate blocks:

- `ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_STALE_PROGRESS`,
- `ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_ASSET_MISSING`,
- `ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_HASH_MISMATCH`,
- `ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_OVERCLAIM`,
- `ERR_DOGFOOD_PROGRESS_ASSET_PROMOTION_PROGRESS_NOT_READY`.

The SVG must include "Process completion, not upward performance claim" and
"not a public benchmark graph".

## Evaluation Fixtures

`fixtures/v67/manifest.json` covers:

- promotion-ready process asset bundle,
- stale progress blocking,
- missing SVG blocking,
- hash drift blocking,
- overclaim blocking,
- not-ready progress blocking.

## Release Plan

V67 creates a reviewable process-graph promotion bundle. It does not edit
tracked assets. The next release slice can copy the reviewed bundle into
`assets/` and update README if the user wants the process graph visible on the
GitHub page.
