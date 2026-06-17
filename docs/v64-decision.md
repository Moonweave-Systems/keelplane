# V64 Decision

Decision: keep.

Command used to verify clean pair-root selection:

```bash
python scripts/dwm_dogfood_pair_select.py --manifest fixtures/v64/manifest.json --out out/dogfood-pair-selections/v64-final
```

The accepted suite covers `pair-selection.json`, `pair-selection.md`, clean pair
root generation, V58 series generation, duplicate rejection recording, stale
pair blocking, unsafe clean root blocking, and insufficient unique task blocking.

This decision does not claim source pair deletion, live Codex execution, README
graph promotion, public benchmark readiness, or generated `out/` directories as
source truth.
