# V20 Compatibility Matrix

Status: 1.0 release-candidate policy.

## Stable Contracts

- V1 compiled packet layout under `out/v1/`.
- V12 adapter command planner artifacts: `adapter-command.json` and
  `adapter-command.md`.
- V13 runner evidence artifacts: `runner.json`, `attempt.json`,
  `transcript.md`, `hashes.json`, and `status.json`.
- V14 session artifacts: `session.json`, `worktree.json`, `locks.json`,
  `events.jsonl`, `status.json`, and `resume.md`.
- V15 review and repair artifacts under `out/reviews/` and `out/repairs/`.
- V16 fanout/fanin artifacts under `out/fanout/`.
- V17 HUD summary and approval artifacts under `out/hud/`.
- V18 package metadata under `packaging/dwm-package.json`.
- V19 adapter registry under `packaging/dwm-adapters.json`.

## Compatibility Policy

DWM 1.0 accepts schema version `1.0` artifacts for the implemented V12-V19
surface. A future incompatible schema must fail closed with a structured error
and must not mutate existing artifacts before a migration plan is selected.

Claude, Codex, and shell surfaces are portable CLI or adapter surfaces, not
requirements for acceptance. OMX remains optional and is not required for local
release gates.

## Security Boundaries

1.0 acceptance fails if a required path permits stale evidence, untracked
approval, silent worktree mutation, hidden backend state, unbounded retry,
unchecked external action, secret access, production deploy, dependency
installation, database migration, deletion, public API mutation, or history
rewrite without a matching gate.

Required blocked phrases for release tooling: untracked approval; dependency installation; history rewrite.
