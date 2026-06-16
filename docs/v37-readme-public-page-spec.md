# V37 README Public Page Spec

Status: implemented first README public page polish in `README.md` and
`assets/dwm-live-benchmark.svg`.

## Research and Prior Art

Strong project landing pages lead with the product name, the shortest useful
value statement, a quickstart, proof that the thing works, and links to deeper
docs. They avoid making the first screen a competitor comparison or a generated
roadmap dump.

V36 already generated source-bound benchmark graph artifacts from
`report.json.graph_metrics`. V37 promotes one generated graph snapshot into a
tracked README asset so the GitHub landing page shows evidence directly.

## Product Position and Non-Goals

V37 keeps the README centered on DWM itself:

- DWM as a deterministic workflow control-plane,
- real commands that run locally,
- safety gates and source-bound evidence,
- benchmark visuals that point back to hash-bound artifacts.

Non-goals:

- do not present benchmark visuals as external benchmark authority,
- do not manually invent graph values,
- do not make the README a competitor matrix,
- do not move ignored `out/` evidence into source without a tracked publish
  record.

## Workflow Architecture

The README public page now embeds `assets/dwm-live-benchmark.svg`. The paired
`assets/dwm-live-benchmark.json` records the promoted source artifact and V35
report hash.

The source truth remains the generated V36 graph artifact:

```text
out/readme-benchmark-graphs/v36-final/readme-graph-published-report/benchmark-graph.json
```

## Safety and Verification Gates

The gate checks:

- README no longer names optional competitor runtimes in its Position section,
- README embeds a tracked graph asset instead of ignored `out/` output,
- the graph JSON records `source: report.json.graph_metrics`,
- release text, whitespace, skill validation, and contract checks still pass.

## Release Plan

V37 is complete when the README page is concise, self-contained on GitHub, and
the published graph asset has a source-hash record.
