# V14 Session And Worktree Runtime Spec

Status: planned; not implemented.

## Research And Prior Art

Useful runner products manage durable sessions and isolated workspaces. OMX
does this through its orchestration layer. DWM needs a smaller native runtime
that preserves evidence and avoids hidden mutable state.

## Product Position And Non-Goals

V14 adds durable session and worktree management for DWM Runner.

Non-goals:

- do not implement multi-worker scheduling,
- do not add a dashboard,
- do not delete worktrees automatically,
- do not treat session logs as proof without DWM hashes.

## Workflow Architecture

Add:

```bash
python scripts/dwm_runner.py session start --run out/<run>
python scripts/dwm_runner.py session status --session out/sessions/<id>
python scripts/dwm_runner.py session resume --session out/sessions/<id>
```

Session artifacts:

- `session.json`,
- `worktree.json`,
- `events.jsonl`,
- `locks.json`,
- `resume.md`,
- `status.json`.

## Execution Model

Sessions are append-only. Worktree creation is explicit, recorded, and bound to
the source commit. Cleanup is proposed as a command, not performed silently.

## Safety And Verification Gates

Refuse dirty source worktrees unless the run is read-only. Refuse symlinked
session paths. Refuse branch deletion, force push, hard reset, and secret
access unless explicitly approved by a tracked human gate.

## Evaluation Fixtures

- positive: start/resume one read-only session,
- positive: detect stale source commit,
- negative: dirty write session blocked,
- negative: symlinked session path rejected.

## Release Plan

1. Add session registry under ignored `out/sessions/`.
2. Add session status and resume commands.
3. Add fixtures for clean, dirty, stale, and symlink states.
4. Document cleanup as a human-confirmed operation.
