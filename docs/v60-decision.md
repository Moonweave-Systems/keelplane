# V60 Decision

Decision: keep.

Command used to verify the local dogfood chart review gate:

```bash
python scripts/dwm_dogfood_chart_review.py --manifest fixtures/v60/manifest.json --out out/dogfood-chart-reviews/v60-final
```

The accepted suite covers `chart-review.json`, `chart-review.md`, missing
receipt blocking, rejected receipt blocking, stale receipt blocking, and
overclaim blocking.

This decision does not claim README graph promotion, graph rendering, public
benchmark readiness, external benchmark authority, direct-agent superiority, or
generated `out/` directories as source truth.
