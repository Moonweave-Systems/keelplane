# dynamic-workflow-designer

> Design ultracode-style, situation-aware multi-agent workflows for large tasks before execution starts.

[![License: MIT](https://img.shields.io/badge/License-MIT-4F46E5.svg)](LICENSE)
[![Agent skill](https://img.shields.io/badge/agent%20skill-Codex-4F46E5.svg)](SKILL.md)

`dynamic-workflow-designer` is a Codex skill for designing large workflows:
phases, workers, parallelism, handoffs, verification gates, risk gates, budgets,
and resume strategy.

It is deliberately not the same as `workflow-router`. The router chooses the
smallest suitable workflow. This skill designs a larger workflow when the task
itself needs dynamic orchestration.

## Why

Claude Code Dynamic Workflows changed the useful abstraction: for large work,
the plan can live outside the chat as an inspectable workflow. Codex does not
currently have the same native workflow runtime in this environment, so this
repo starts with the part we can make reliable now: workflow design.

The first slice is a skill that produces high-quality workflow blueprints and
specs. A plugin or runtime can follow once the design layer proves useful.

## Use

Example prompts:

```text
Use $dynamic-workflow-designer to design a workflow for auditing every route for missing authorization.
```

```text
Use $dynamic-workflow-designer to plan a 500-file migration with verification gates and rollback boundaries.
```

## Repository layout

```text
.
├── SKILL.md                         # Runtime skill instructions
├── scripts/check_contract.py         # Release contract smoke check
├── scripts/evaluate_plan.py          # V0.5 schema and benchmark evaluator
├── references/workflow-patterns.md  # Pattern guide for workflow designs
├── references/workflow-plan-schema.md
│                                      # workflow.plan.json contract
├── fixtures/v0.5/manifest.json       # Benchmark fixture manifest
├── samples/v0.5/                     # Deterministic candidate/baseline samples
├── docs/fixture-smoke/v0-smoke.md    # Auditable fixture smoke results
├── docs/v0.5-plan-schema-evaluator-spec.md
│                                      # V0.5 evaluator spec
├── docs/v0.5-decision.md             # Keep/kill decision
├── docs/github-research.md          # Prior-art survey and import decisions
├── docs/spec.md                     # Product spec and release criteria
├── agents/openai.yaml               # UI metadata
├── LICENSE
└── README.md
```

## Prior Art

The initial survey looked at:

- `lxcong/awesome-claude-dynamic-workflows`
- `peymanvahidi/awesome-claude-dynamic-workflows`
- `Timmy6942025/opencode-dynamic-workflows`
- `scasella/claude-dynamic-workflows-codex`
- `andrueandersoncs/open-workflows`
- local `claude-skills/engineering/agent-workflow-designer`
- local `claude-skills/orchestration/ORCHESTRATION.md`

See [`docs/github-research.md`](docs/github-research.md) for what to reuse and
what not to vendor.

## Releasing

Run from the repository root:

```bash
uv run python "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" .
python scripts/check_contract.py
python scripts/check_contract.py --self-test
python scripts/evaluate_plan.py --self-test
python scripts/evaluate_plan.py --manifest fixtures/v0.5/manifest.json --out out/v0.5
git diff --check "$(git hash-object -t tree /dev/null)" HEAD
rg -n --pcre2 "(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}|-----BEGIN (RSA|OPENSSH) PRIVATE KEY-----" --glob '!LICENSE' .; test $? -eq 1
rg -n "T[O]DO|T[B]D|PLACE[H]OLDER|FIX[M]E" --glob '*.md' .; test $? -eq 1
```

The contract check requires passing fixture records under
[`docs/fixture-smoke/`](docs/fixture-smoke/).

The V0.5 evaluator regenerates `out/v0.5/` from tracked fixtures and samples.
That directory is verification evidence, not source of truth.

The V0.5 keep/kill decision is
[`docs/v0.5-decision.md`](docs/v0.5-decision.md).

## License

[MIT](LICENSE)
