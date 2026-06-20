# GitHub And Local Prior Art

Status: researched on 2026-06-14 from local workspace files, GitHub metadata,
and project READMEs.

## Official Baseline

Claude Code Dynamic Workflows are JavaScript orchestration scripts written by
Claude and executed by a workflow runtime. They are intended for codebase audits,
large migrations, and cross-checked research where the plan should live outside
the chat context. The official docs describe workflows as distinct from skills,
subagents, and agent teams because the script decides what runs next and stores
intermediate results.

Relevant docs:

- https://code.claude.com/docs/en/workflows
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/plugins

## External GitHub Repositories

### `lxcong/awesome-claude-dynamic-workflows`

URL: https://github.com/lxcong/awesome-claude-dynamic-workflows

Observed signal:

- Community-curated list of real Claude Code Dynamic Workflow examples.
- Documents Claude workflow installation via `~/.claude/workflows/` or
  project `.claude/workflows/`.
- Currently strongest value is distribution convention and example taxonomy,
  not reusable Codex implementation.

Decision:

- Reuse as reference for workflow categories and saved-command distribution.
- Do not vendor content.

### `peymanvahidi/awesome-claude-dynamic-workflows`

URL: https://github.com/peymanvahidi/awesome-claude-dynamic-workflows

Observed signal:

- Educational breakdown of a collected dynamic workflow skill.
- Highlights runtime primitives such as metadata, phases, `agent()`,
  `pipeline()`, `parallel()`, budgets, and resume semantics.

Decision:

- Reuse concepts in the spec: pipeline-over-barrier, adversarial verification,
  explicit opt-in, and resumability.
- Do not treat as authoritative; it is unofficial analysis.

### `Timmy6942025/opencode-dynamic-workflows`

URL: https://github.com/Timmy6942025/opencode-dynamic-workflows

Observed signal:

- OpenCode implementation inspired by Claude Dynamic Workflows.
- Planner writes custom JavaScript harnesses.
- Runtime exposes primitives such as `spawn`, `wait`, `parallel`,
  `synthesize`, `adversarial`, `tournament`, `loop`, `shell`, and `ask`.

Decision:

- Good prior art for a future runtime API.
- Do not import code for v0; this repo starts as a Codex skill/spec.

### `scasella/claude-dynamic-workflows-codex`

URL: https://github.com/scasella/claude-dynamic-workflows-codex

Observed signal:

- Attempts the closest target: Claude-authored dynamic workflows run on a Codex
  backend with runner, viewer, fleet supervision, journals, and sessionful
  workers.
- Has a full CLI/runtime product surface and likely overlaps with any future
  Codex workflow runtime.

Decision:

- Treat as the strongest implementation reference before building a runtime.
- For v0, avoid copying the product. Instead design a narrower Codex-native
  workflow designer that can later decide whether to interoperate, wrap, or
  build a smaller runtime.

### `andrueandersoncs/open-workflows`

URL: https://github.com/andrueandersoncs/open-workflows

Observed signal:

- Agent-agnostic workflow system using an algebraic DSL, graph interpreter,
  durable engine, MCP server, SQLite resumability, and viewer.
- Separates graph rendering from execution.

Decision:

- Strong architectural reference for a future MCP/runtime layer.
- Not suitable to vendor into the skill repo because it is a larger TypeScript
  system with its own DSL and runtime assumptions.

## Local Workspace Assets

### `claude-skills/engineering/agent-workflow-designer`

Path:
`/Users/choemun-yeong/workspace/projects/agent-tools/ai-skills-dev/claude-skills/engineering/agent-workflow-designer`

Observed signal:

- Existing local Claude skill for multi-agent workflow design.
- Includes `workflow_scaffolder.py` and `references/workflow-patterns.md`.
- Patterns: sequential, parallel, router, orchestrator, evaluator.

Decision:

- Reuse the pattern vocabulary.
- Do not copy the scaffolder as-is. The current product needs a spec-first
  dynamic workflow designer, not a simple JSON skeleton generator.

### `claude-skills/orchestration/ORCHESTRATION.md`

Observed signal:

- Lightweight persona/skill/task-agent orchestration protocol.
- Useful for phase handoff language and context-carrying discipline.

Decision:

- Reuse concepts around objective, phase, handoff, and artifact carry-forward.
- Do not make personas central to this Codex skill.

## Product Implication

The correct first repo is not a fork of any GitHub runtime. It should start as
a Codex skill package named `keelplane` with a clear spec and
evaluation fixtures. A plugin or runtime can be added after the skill proves it
can consistently produce useful workflow designs.
