# V55 Adapter Live Matrix Spec

Status: implemented first adapter live availability matrix in
`scripts/dwm_adapter_live_matrix.py`.

## Research and Prior Art

V27 proved a single adapter command can be version-smoked. V49 made adapter
parity explicit and blocked planned-only live runs. V55 connects those ideas
for the real local machine: DWM can now record which external adapter commands
are present without executing prompts or touching auth secrets.

## Product Position and Non-Goals

V55 is an availability and auth-assumption matrix. It checks command presence
and version output only.

Non-goals:

- do not execute task prompts,
- do not read secrets or tokens,
- do not claim live adapter parity,
- do not register OpenCode as supported before a registry contract exists,
- do not unblock planned-only adapter runs.

## Workflow Architecture

The command is:

```bash
python scripts/dwm_adapter_live_matrix.py matrix --out out/adapter-live-matrix/<matrix_id>
```

It reads:

- `packaging/dwm-adapters.json`,
- optional target overrides for command names and version args.

It writes:

- `adapter-live-matrix.json`,
- `adapter-live-matrix.md`,
- `status.json`.

Default targets are Codex, Claude, and OpenCode. Codex and Claude are matched
against the adapter registry when present. OpenCode is recorded as a candidate
until it has a registry contract.

## Safety and Verification Gates

The gate blocks or marks unavailable:

- `ERR_ADAPTER_LIVE_MATRIX_UNSAFE_COMMAND` for non-bare executable names,
- `ERR_ADAPTER_LIVE_MATRIX_COMMAND_MISSING` for missing local commands,
- `ERR_ADAPTER_LIVE_MATRIX_NOT_REGISTERED` for command candidates outside the
  adapter registry,
- `ERR_ADAPTER_LIVE_MATRIX_VERSION_FAILED` when a version command fails.

## Evaluation Fixtures

`fixtures/v55/manifest.json` covers:

- positive: a registered adapter target with a safe local command records a
  matrix,
- negative: unsafe command names are blocked,
- negative: missing commands are blocked in the matrix,
- negative: unregistered targets are blocked in the matrix.

## Release Plan

V55 prepares future live preflight work. A later slice can consume this matrix
to decide whether a live adapter preflight is possible, but task execution still
requires an explicit human gate and a bounded packet.
