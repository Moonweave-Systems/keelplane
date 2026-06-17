# V65 Decision

Decision: keep.

Command used to verify reviewed local dogfood chart rendering:

```bash
python scripts/dwm_dogfood_chart_render.py --manifest fixtures/v65/manifest.json --out out/dogfood-chart-renders/v65-final
```

The accepted suite covers `chart-render.json`, `chart-render.svg`,
`chart-render.md`, approved local render creation, stale review blocking,
overclaim review blocking, and stale candidate blocking.

This decision does not claim README graph promotion, public benchmark readiness,
external benchmark authority, direct-agent superiority, or generated `out/`
directories as source truth.
