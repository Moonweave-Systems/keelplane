# V12 Adapter Command Planner Spec

Status: planned; not implemented.

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

Add a read-only command:

```bash
python scripts/dwm.py plan-command --run out/<version>/<run_id> --json
```

The output should include:

- `trusted`,
- `current_status`,
- `selected_phase_ids`,
- `adapter_kind`,
- `planned_command`,
- `required_inputs`,
- `blocked_by`,
- `requires_user_approval`.

## Execution Model

The command planner reads only existing artifacts. It maps trusted status
shapes to known deterministic adapters such as `dispatch_frontier.py`,
`review_frontier_result.py`, `ingest_frontier_review.py`, and
`resolve_human_gate.py`.

Unknown states return `blocked_by: ["adapter-not-mapped"]` instead of guessing.

## Safety And Verification Gates

The planner must reject untrusted runs, stale hash ledgers, missing status,
outside-`out/` paths, unknown layouts, and human gates without a tracked
approval artifact.

## Evaluation Fixtures

- positive: V9 dogfood returns no execution command because it is complete,
- positive: trusted V6 frontier-ready returns a dispatch planning command,
- negative: untrusted hash ledger returns `adapter-not-allowed`,
- negative: human gate returns approval-required without fabricating approval.

## Release Plan

1. Add `plan-command` to `scripts/dwm.py`.
2. Add fixture probes for complete, ready, human-gated, and stale states.
3. Bind output to `docs/v12-decision.md`.
4. Update release checks without changing V10/V11 command counts.
