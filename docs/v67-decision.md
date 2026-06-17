# V67 Decision

Decision: keep.

Command used to verify dogfood process progress asset promotion:

```bash
python scripts/dwm_dogfood_progress_asset_promotion.py --manifest fixtures/v67/manifest.json --out out/dogfood-progress-asset-promotions/v67-final
```

The accepted suite covers `asset-promotion.json`, `asset-diff.md`,
`README-snippet.md`, `dwm-dogfood-progress.svg`, stale progress blocking,
missing SVG blocking, hash drift blocking, overclaim blocking, and not-ready
progress blocking.

This decision does not edit tracked README assets, claim upward benchmark
performance, claim model superiority, or treat process progress as benchmark
evidence.
