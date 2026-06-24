# Depone

> Workflow designer + cross-platform evidence verifier for multi-agent AI systems.

[![License: MIT](https://img.shields.io/badge/License-MIT-4F46E5.svg)](LICENSE)
[![Agent skill](https://img.shields.io/badge/agent%20skill-Codex-4F46E5.svg)](SKILL.md)
[![Release](https://img.shields.io/github/v/release/Moonweave-Systems/depone?color=4F46E5)](https://github.com/Moonweave-Systems/depone/releases)
[![Contract](https://img.shields.io/badge/contract-self--tested-059669.svg)](scripts/check_contract.py)

![Depone hero](assets/dwm-hero.svg)

**Depone** designs multi-agent workflows and verifies their execution
evidence. It does not execute agents — it makes runs from other frameworks
(Conductor, LangGraph) trustworthy.

## Quickstart

```bash
# Installation from source. PyPI publishing is not active yet.
git clone https://github.com/Moonweave-Systems/depone
cd depone

# Run the full design → compile → verify cycle
python3 -m depone demo --out out/depone-quickstart

# Or step by step:
python3 -m depone design "audit all API routes for authentication" --surface . --out plan.json
python3 -m depone validate plan.json
python3 -m depone compile plan.json --target conductor --out workflow.yaml
python3 -m depone verify plan.json --evidence ./evidence/ --out report.json --operator-view-out operator-view.md
```

## Installation

```bash
pip install depone
```

No external dependencies required — the core uses Python stdlib only.
Optional extras such as `depone[conductor]` are currently empty placeholders;
they install no additional runtime dependencies.
> **Note:** `pip install depone` is not yet available on PyPI.
> Clone from GitHub and use `python -m depone` for now (V104.1 target).

## What Exists Today
Depone ships the stdlib-only CLI, a strict plan validator, a Conductor YAML
emitter, a generic evidence adapter, and the 4-check verification engine.

Run model: a `slice` is one atomic worker task, a `wave` is a gated group of
one or more slices, and a `run` is one or more waves verified by receipts and
evidence gates.

## Command Reference

| Command | Description |
|---|---|
| `depone design` | Decompose a broad objective into a structured workflow plan |
| `depone validate` | Validate a plan.json against the schema v0.5 |
| `depone compile` | Translate a plan into a target framework format (Conductor YAML) |
| `depone verify` | Verify execution evidence against a plan (4-check engine) |
| `depone validate-contracts` | Validate Agent Fabric contracts and fixtures |
| `depone agent-fabric-smoke` | Export the source-only Agent Fabric lifecycle smoke summary |
| `depone agent-fabric-harness-snapshot` | Export source-only harness capability snapshots |
| `depone demo` | Run a complete design → compile → verify cycle |

### Verify: 4-Check Engine

1. **Gate Compliance** — Were declared risk_gates respected? (write, network, approval gates)
2. **Handoff Integrity** — Do declared handoff artifacts exist with matching SHA-256 hashes?
3. **Adversarial Check** — Can claims be refuted against ground truth?
4. **Budget Adherence** — Did execution stay within max_agents, max_rounds, and budget limits?

## Normal Loop

```
depone design "audit all API routes" --out plan.json
       │
       ▼  compile --target conductor
    workflow.yaml
       │
       ▼  conductor run workflow.yaml     ← NOT Depone (execution)
    ./run-output/
       │
       ▼  verify plan.json --evidence ./run-output/
    verification-report.json              ← Depone (evidence)
```

## Product Thesis

> Depone designs multi-agent workflows and verifies their execution evidence.
> It does not execute agents. It makes runs from other frameworks trustworthy.

- **design**: decompose broad objectives into the workflow plan schema (phases,
  workers, handoffs, gates, budgets).
- **compile**: translate plans into target framework formats (Conductor YAML
  first; LangGraph Python later).
- **verify**: consume raw execution evidence from any framework, check it
  against the plan, produce hash-signed verification reports.

## Safety Model

Depone treats artifacts, not model claims, as the source of truth. A
workflow is trusted only when the relevant plan, packet, prompt, evidence,
review, approval, and status artifacts match their hash ledgers.
Generated `out/` directories are verification evidence, not source of truth.
They are never hand-edited; artifacts and source hashes are the source of truth.

Depone does not claim unrestricted autonomous execution. Destructive actions,
network access, dependency installation, secret access, external messaging,
database migration, production deployment, and history rewrite require explicit
gates with a safe default.

## What Is Still Honest

Depone claims **no direct-agent superiority** — it is a design + verification layer, not an agent runtime.

It does not claim upward performance.
It is not a public benchmark graph.
For that reason, public trend promotion requires real release history and measured improvements over established baselines.
Trend promotion is blocked until release history supports the claim.
The skill is named `depone`.

### Inspection & diagnostics

```bash
# Quickstart demo evidence
python scripts/dwm_demo.py run --out out/demo/quickstart
python scripts/dwm_demo.py inspect --demo out/demo/quickstart

# Operator-state inspection
python scripts/dwm.py status --run out/v9/v32-semantic-dogfood
python scripts/dwm.py next --run out/v9/v32-semantic-dogfood

# Available commands
python scripts/dwm.py commands --kind product
python scripts/dwm.py commands --kind release

# README quality gate
python scripts/check_readme_quality.py README.md
```

## Evidence Graphs

![Dogfood progress](assets/dwm-dogfood-progress.svg)
*Dogfood benchmark progression across attempts.*

![Live benchmark](assets/dwm-live-benchmark.svg)
*Live benchmark history — not a public benchmark graph. Benchmark visuals are source-bound.*

## Quality

All CLI commands include built-in `--self-test`:
```bash
python3 -m depone design --self-test              # 4/4 passed
python3 -m depone compile --self-test             # conductor 4/4, agent_fabric 6/6 passed
python3 -m depone validate --self-test            # 4/4 passed
python3 -m depone verify --self-test              # 7/7 passed
python3 -m depone validate-contracts --self-test  # 22/22 passed
python3 -m depone agent-fabric-smoke --self-test # source-only smoke export passed
python3 -m depone agent-fabric-harness-snapshot --self-test # harness snapshot export passed
python3 -m depone demo --self-test                # full cycle passed
```

Run the release contract before publishing changes:

```bash
python scripts/check_contract.py --tier changed
```

## Position

Depone is not a prompt-only workflow router and not a clone of any one
runtime. It is a design + verification layer above existing execution engines.
DWM Core keeps agentic work inspectable, reproducible, resumable, and honest
about what has actually been executed.

## Documentation

- [`docs/v107-agent-fabric-control-plane-spec.md`](docs/v107-agent-fabric-control-plane-spec.md): Agent Fabric control-plane contract/compiler spec.
- [`docs/v104-product-direction-spec.md`](docs/v104-product-direction-spec.md): V104 product direction and CLI spec.
- [`docs/spec.md`](docs/spec.md): product spec and release criteria.
- [`docs/command-reference.md`](docs/command-reference.md): full command and artifact reference.
- [`docs/release-history.md`](docs/release-history.md): versioned implementation history.
- [`references/workflow-plan-schema.md`](references/workflow-plan-schema.md): plan schema v0.5 reference.
- [`references/workflow-patterns.md`](references/workflow-patterns.md): canonical workflow patterns.
- [`SKILL.md`](SKILL.md): installed agent skill for Codex environments.

## License

MIT. See [`LICENSE`](LICENSE).
