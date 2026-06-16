# V21 Product Shell Spec

Status: implemented first product shell slice in `scripts/dwm.py`.

## Research and Prior Art

DWM has enough internal control-plane pieces to expose a smaller user-facing
surface. The next useful step is not another harness backend. It is a product
shell that makes the common commands memorable while preserving the artifact
truth model.

## Product Position and Non-Goals

V21 starts the product shell:

- `dwm plan` records a plan-only request artifact,
- `dwm run` records a run intent but blocks before live execution,
- `dwm resume` verifies a V21 shell artifact or delegates to existing run
  guidance.

Non-goals:

- do not call a live model,
- do not execute live Codex, Claude, OpenCode, OMO, or shell adapters,
- do not create worktrees, attach sessions, or fan out workers,
- do not mark a product-shell request as completed work.

## Workflow Architecture

The product shell writes repo-local artifacts under `out/v21/<run_id>/`:

- `.dwm_shell-owned.json`,
- `workflow-request.json`,
- `workflow-request.md`,
- `status.json`,
- `resume.md`.

`dwm plan` produces a `plan-only` decision with status `planned`.
`dwm run` produces a `blocked-before-live-execution` decision with status
`blocked` and `ERR_DWM_SHELL_LIVE_EXECUTION_BLOCKED`.

## Execution Model

The first shell slice is intentionally non-executing. It captures the objective,
safe default, next recommended commands, and request hash. `dwm resume` verifies
that `status.json` still matches `workflow-request.json`.

## Safety and Verification Gates

The shell blocks when:

- output escapes `out/v21/`,
- an existing output directory is not shell-owned,
- the objective is empty,
- the request hash is stale,
- a user asks `dwm run` to proceed before live adapter policy exists.

## Evaluation Fixtures

The release contract runs:

- `python scripts/dwm.py plan "V21 shell smoke" --out out/v21/release-plan-smoke --json`,
- `python scripts/dwm.py run "V21 shell smoke" --out out/v21/release-run-smoke --json`,
- `python scripts/dwm.py resume --run out/v21/release-run-smoke --json`,
- `python scripts/dwm.py --self-test`.

## Release Plan

V21 is the first user-facing shell slice. Later slices can replace the blocked
`run` path with approved adapter execution only after role contracts and harness
benchmark gates are implemented.
