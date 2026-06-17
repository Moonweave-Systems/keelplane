# V64 Dogfood Pair Select Spec

Status: implemented clean pair-root selector in
`scripts/dwm_dogfood_pair_select.py`.

## Research and Prior Art

V63 correctly blocks graph-ready recommendation when a pair root contains
duplicate task pairs. The next useful step is not deleting evidence, but creating
a clean pair root that selects one pair per task and can be independently checked
by V58 series readiness.

## Product Position and Non-Goals

V64 is a source-preserving selector. It copies selected pairs into a clean pair
root and builds a V58 series from that root.

Non-goals:

- do not delete source pairs,
- do not rewrite source pair artifacts,
- do not use symlinks,
- do not run live Codex,
- do not promote README benchmark graphs.

## Workflow Architecture

The command is:

```bash
python scripts/dwm_dogfood_pair_select.py select --pair-root out/dogfood-pairs --out out/dogfood-pair-selections/<selection_id>
```

It writes:

- `pair-selection.json`,
- `pair-selection.md`,
- `status.json`,
- a clean pair root under `out/dogfood-pairs/<selection_id>-clean`,
- a V58 series under `out/dogfood-pair-series/<selection_id>-series`.

## Execution Model

The selector validates each source pair, groups by `task_id`, and applies the
deterministic `lexicographic-last` policy. Rejected duplicates are recorded with
their source hash and reason. The clean root is selection-owned and may be safely
recreated by the same selection id.

## Safety and Verification Gates

The gate blocks:

- `ERR_DOGFOOD_PAIR_SELECT_STALE_PAIR` when pair status and artifact differ,
- `ERR_DOGFOOD_PAIR_SELECT_CLEAN_ROOT_UNSAFE` when clean root equals source root
  or is not selector-owned,
- unsafe traversal and symlink paths,
- unsupported selection policies.

## Evaluation Fixtures

`fixtures/v64/manifest.json` covers:

- positive: duplicate task pairs are selected into a graph-ready clean root,
- positive: insufficient unique tasks remain blocked by V58 readiness,
- negative: stale pair is blocked,
- negative: unsafe clean root is blocked.

## Release Plan

V64 makes the local dogfood evidence graphable without deleting old evidence.
The next step is chart candidate generation from the clean-root series and
review before any README promotion.
