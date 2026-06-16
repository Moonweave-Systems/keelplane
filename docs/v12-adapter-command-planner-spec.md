# V12 Adapter Command Planner Spec

Status: implemented in `scripts/compile_workflow.py --plan-command`.

## Research And Prior Art

V11 can recommend the next safe action, but it does not produce exact adapter
commands for the inspected run. OMX and similar tools are useful because they
turn intent into executable commands. DWM should first generate precise
commands without executing them.

## Product Position And Non-Goals

V12 adds command planning, not command execution. It should answer: "Given this
trusted run, what exact deterministic adapter command is allowed next?"

Non-goals:

- do not launch Codex CLI,
- do not launch OMX,
- do not create worktrees,
- do not write runner evidence,
- do not approve human gates.

## Workflow Architecture

Add a planning command:

```bash
python scripts/compile_workflow.py --plan-command --resume out/v1/<run_id>
```

The planner writes `adapter-command.json` and `adapter-command.md` inside the
run directory. JSON includes:

- `decision`,
- `adapter`,
- `command`,
- `blocked_by`,
- `risk_codes`,
- `source_hashes`.

`decision` is one of:

- `command_ready`: a Codex command is safe to show for manual execution,
- `blocked`: no command is produced and `blocked_by` explains why.

The default adapter is Codex CLI. Claude and OMX remain optional future adapter
targets and are not runtime dependencies for V12.

The command is intentionally not executed by V12.

The output does not include:

- runner evidence,
- session IDs,
- worktree state,
- `required_inputs`,
- human approval mutation.

## Execution Model

The command planner reads an existing V1 compiled run and first calls the
resume trust checker. It plans only from artifacts whose packet, prompt, input,
gate, source-plan, and compiler snapshots still match the trusted ledger.

For ready read-only packets, the Codex adapter emits a deterministic command
that points at `packets/001-first-slice.prompt.md`.

Unknown adapters raise `ERR_PLAN_COMMAND_UNSUPPORTED_ADAPTER` instead of
guessing. Unknown or stale run states return `decision: "blocked"` with no
command.

## Safety And Verification Gates

The planner must reject untrusted runs, stale hash ledgers, missing status,
outside-`out/v1/` paths, unknown layouts, and human gates without a tracked
approval artifact.

Risky packets do not get commands. The blocked risk set includes write, delete,
network, dependency install, database migration, production deploy, public API
change, external message, paid API, secret access, and history rewrite.

## Evaluation Fixtures

- positive: ready read-only V1 packet returns `decision: "command_ready"` and a
  Codex CLI command,
- negative: write-risk packet returns `decision: "blocked"` and no command,
- negative: stale prompt/source hash drift returns `blocked_by:
  ["resume-invalidated"]`,
- negative: unknown adapter raises `ERR_PLAN_COMMAND_UNSUPPORTED_ADAPTER`.

## Release Plan

1. Keep V12 in `compile_workflow.py` until V13 introduces a runner boundary.
2. Add fixture probes for ready, risk-blocked, stale, and unsupported adapter
   states.
3. Bind output to `docs/v12-decision.md` when promoting the generated evidence.
4. Keep V12 free of live command execution, worktree creation, and session
   attachment.
