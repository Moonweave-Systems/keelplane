# V15 Multi-Worker Fanout Spec

Status: planned; not implemented.

## Research And Prior Art

Claude Dynamic Workflows and OMX both show that large tasks benefit from
parallel workers. DWM should add fanout only after sessions and worktrees are
durable enough to preserve evidence per worker.

## Product Position And Non-Goals

V15 adds bounded parallel worker execution. It is not an unrestricted team
launcher.

Non-goals:

- do not exceed the workflow concurrency cap,
- do not merge worker outputs automatically,
- do not launch workers without compiled packets,
- do not hide failures behind a synthesized success message.

## Workflow Architecture

Add:

```bash
python scripts/dwm_runner.py fanout --run out/<run> --cap <n>
python scripts/dwm_runner.py fanin --session out/sessions/<id>
```

Fanout artifacts:

- `workers/<worker_id>/attempt.json`,
- `workers/<worker_id>/status.json`,
- `fanin.json`,
- `conflicts.json`,
- `review-queue.json`.

## Execution Model

Each worker gets one packet, one worktree, one attempt ledger, and one evidence
bundle. Fan-in never trusts a worker directly; it produces review inputs for
DWM Core.

## Safety And Verification Gates

Concurrency must obey plan budget. File ownership conflicts require review.
Any worker that requests risky actions stops at a human gate.

## Evaluation Fixtures

- positive: two independent read-only packets fan out and fan in,
- positive: one worker failure preserves other evidence,
- negative: concurrency cap exceeded,
- negative: overlapping file ownership requires review.

## Release Plan

1. Add fanout planner that reads DWM schedules.
2. Add fixture worker backend for deterministic tests.
3. Add fan-in summary and review queue artifacts.
4. Defer live multi-Codex fanout until fixture behavior is stable.
