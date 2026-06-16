# DWM

> Deterministic Workflow Machine: a local control-plane for agentic work that
> turns large goals into hashed plans, packets, evidence, reviews, gates, and
> resumable runtime state.

[![License: MIT](https://img.shields.io/badge/License-MIT-4F46E5.svg)](LICENSE)
[![Agent skill](https://img.shields.io/badge/agent%20skill-Codex-4F46E5.svg)](SKILL.md)
[![Release](https://img.shields.io/github/v/release/Moonweave-Systems/dwm?color=4F46E5)](https://github.com/Moonweave-Systems/dwm/releases)
[![Contract](https://img.shields.io/badge/contract-self--tested-059669.svg)](scripts/check_contract.py)

![DWM hero](assets/dwm-hero.svg)

**DWM** is a deterministic workflow control-plane for Codex-era agentic work.
The installed skill remains named `dynamic-workflow-designer` for compatibility,
but this repository now provides a broader product surface: workflow design,
packet compilation, bounded runner gates, review/repair evidence, live scoring
artifacts, and release checks.

## Quickstart

Use the skill when a task is too large or risky for one normal agent turn:

```text
Use $dynamic-workflow-designer to design a workflow for auditing every route for missing authorization.
```

Inspect the product surface:

```bash
python scripts/dwm.py status --run out/v9/v32-semantic-dogfood
python scripts/dwm.py next --run out/v9/v32-semantic-dogfood
python scripts/dwm.py doctor
python scripts/dwm.py commands --kind product
```

Run the release contract:

```bash
python scripts/check_contract.py
```

For the full release command corpus, use:

```bash
python scripts/dwm.py commands --kind release
```

## Current Surface

| Layer | Capability |
| --- | --- |
| Design | Converts broad objectives into phases, workers, handoffs, gates, budgets, and verification plans. |
| Compile | Emits first-slice packets, prompts, status, resume files, and hash ledgers. |
| Run | Executes approved read-only or pre-isolated packets through bounded adapters. |
| Review | Records review findings, repair prompts, retry state, and verification evidence. |
| Fanout | Runs bounded multi-worker slices with deterministic fan-in. |
| HUD | Produces read-only status views and hash-bound approval artifacts. |
| Live evidence | Plans adapter commands, preflights them, ingests receipts, judges receipts, scores verified evidence, and reports graph-ready metrics. |
| Packaging | Validates repo-local install metadata, adapter registries, compatibility, and release evidence. |

## Safety Model

DWM treats artifacts, not model claims, as the source of truth. A workflow is
trusted only when the relevant plan, packet, prompt, evidence, review, approval,
and status artifacts match their hash ledgers.

DWM does not claim unrestricted autonomous execution. Destructive actions,
network access, dependency installation, secret access, external messaging,
database migration, production deployment, and history rewrite require explicit
gates with a safe default.

## Live Scoring

![DWM live benchmark evidence](assets/dwm-live-benchmark.svg)

The live benchmark path is intentionally staged:

```text
V28 command plan
  -> V29 runner preflight
  -> V30 receipt ingestion
  -> V31 receipt judgment
  -> V32 score verification
  -> V33 score aggregation
  -> V34 adversarial review
  -> V35 benchmark report
  -> V36 README graph artifacts
```

The README graph pipeline is source-bound. Benchmark visuals read
`report.json.graph_metrics`, not terminal output, generated prose, or manually
copied numbers. The tracked README image in `assets/dwm-live-benchmark.svg` is a
published snapshot of the V36 graph artifact and keeps its source hash in
`assets/dwm-live-benchmark.json`.

Generate graph artifacts with:

```bash
python scripts/dwm_readme_benchmark_graph.py generate --report out/live-reports/<report_id> --out out/readme-benchmark-graphs/<graph_id>
```

This writes:

- `benchmark-graph.json`
- `benchmark-graph.svg`
- `README-snippet.md`

## Common Commands

Product shell:

```bash
python scripts/dwm.py plan "<objective>" --out out/v21/<run_id>
python scripts/dwm.py run "<objective>" --out out/v21/<run_id>
python scripts/dwm.py resume --run out/v21/<run_id>
```

Benchmark and live evidence:

```bash
python scripts/dwm_benchmark.py corpus
python scripts/dwm_benchmark.py claim --min-margin 8
python scripts/dwm_live_benchmark.py capture --out out/benchmarks-live/<capture_id>
python scripts/dwm_live_attempt_plan.py plan --adapter-command codex --task-id failing-test-fix --out out/live-attempt-plans/<plan_id>
python scripts/dwm_live_runner_preflight.py preflight --plan out/live-attempt-plans/<plan_id> --out out/live-runner-preflight/<preflight_id>
python scripts/dwm_live_receipt.py ingest --preflight out/live-runner-preflight/<preflight_id> --receipt receipt.json --out out/live-receipts/<receipt_id>
python scripts/dwm_live_report.py publish --review out/live-score-reviews/<review_id> --out out/live-reports/<report_id>
```

Role, HUD, install, adapter, and release checks:

```bash
python scripts/dwm_roles.py registry
python scripts/dwm_hud.py approve --hud out/hud/<hud_id> --out out/hud/<approval_id> --approver <name>
python scripts/dwm_install.py validate
python scripts/dwm_adapters.py registry
python scripts/dwm_release.py status --out out/release/<release_id>
```

## Repository Map

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Codex skill entrypoint and workflow design contract. |
| `scripts/dwm.py` | Product CLI for status, next actions, doctor, and command discovery. |
| `scripts/check_contract.py` | Release contract smoke and documentation consistency check. |
| `scripts/compile_workflow.py` | First-slice packet compiler. |
| `scripts/dwm_runner.py` | Runner, session/worktree, review/repair, and fanout surfaces. |
| `scripts/dwm_live_*.py` | Live evidence, receipt, score, review, report, and graph gates. |
| `docs/automation-roadmap.md` | Implementation roadmap and completed slices. |
| `docs/v32-to-v35-live-scoring-workflow.md` | Live scoring workflow design. |
| `docs/v36-readme-benchmark-graph-spec.md` | README benchmark graph artifact contract. |
| `fixtures/` | Deterministic manifests used by release gates. |
| `assets/` | Tracked README visuals and published benchmark graph snapshots. |

## Key Docs

- [`docs/spec.md`](docs/spec.md): product spec and release criteria.
- [`docs/automation-roadmap.md`](docs/automation-roadmap.md): staged roadmap.
- [`docs/github-research.md`](docs/github-research.md): prior-art survey.
- [`docs/v12-to-v20-final-roadmap.md`](docs/v12-to-v20-final-roadmap.md): final-product roadmap.
- [`docs/v23-harness-benchmark-spec.md`](docs/v23-harness-benchmark-spec.md): benchmark corpus contract.
- [`docs/v35-live-report-spec.md`](docs/v35-live-report-spec.md): live benchmark report gate.
- [`docs/v36-readme-benchmark-graph-spec.md`](docs/v36-readme-benchmark-graph-spec.md): README graph artifact generator.
- [`docs/v37-readme-public-page-spec.md`](docs/v37-readme-public-page-spec.md): README public page and graph publish gate.

Generated `out/` directories are verification evidence, not source of truth.

## Position

DWM is not a prompt-only workflow router and not a clone of any one runtime.
DWM is a deterministic control-plane above agent CLIs, local harnesses, and
bounded adapter surfaces. The goal is to make agentic work inspectable,
reproducible, resumable, and honest about what has actually been executed.

## License

MIT. See [`LICENSE`](LICENSE).
