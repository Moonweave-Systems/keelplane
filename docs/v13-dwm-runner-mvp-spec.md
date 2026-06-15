# V13 DWM Runner MVP Spec

Status: planned; not implemented.

## Research And Prior Art

OMX proves that Codex CLI orchestration is useful when process launch, team
state, and hooks are packaged. DWM should not copy that full surface first. The
MVP runner should execute exactly one DWM-approved packet and return evidence
to DWM Core.

## Product Position And Non-Goals

V13 introduces DWM Runner as the first native execution layer. It is still not
a multi-agent runtime.

Non-goals:

- do not run parallel workers,
- do not manage long-lived teams,
- do not provide a dashboard,
- do not support arbitrary shell commands,
- do not bypass DWM gates.

## Workflow Architecture

Add a runner entry:

```bash
python scripts/dwm_runner.py run --packet out/<run>/packets/<packet>.json --out out/runner/<run_id>
```

Runner output should include:

- `runner.json`,
- `attempt.json`,
- `stdout.txt`,
- `stderr.txt`,
- `transcript.md` when available,
- `git-status-before.txt`,
- `git-status-after.txt`,
- `hashes.json`,
- `status.json`.

## Execution Model

The MVP runner may call Codex CLI only through an explicit allowlisted command
shape. It must capture outputs before DWM Core decides whether the run is
trusted.

## Safety And Verification Gates

The runner refuses packets without trusted DWM Core status. Write-mode packets
require an isolated worktree or explicit read-only mode. Secret access, network
access, dependency installation, production deploy, database migration, history
rewrite, deletion, and external messaging require human gates.

## Evaluation Fixtures

- positive: dry-run read-only packet records evidence,
- positive: Codex auth failure records blocked evidence,
- negative: stale packet refuses execution,
- negative: write packet without worktree refuses execution.

## Release Plan

1. Add `scripts/dwm_runner.py` with dry-run and Codex-fixture modes.
2. Add manifest fixtures under `fixtures/v13/`.
3. Add `docs/v13-decision.md` from generated summary.
4. Keep live Codex execution as optional smoke evidence until auth is stable.
