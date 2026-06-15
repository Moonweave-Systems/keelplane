# V19 Adapter Ecosystem Spec

Status: planned; not implemented.

## Research And Prior Art

DWM should not depend on one runner. Codex CLI is the first native target, OMX
can remain optional, and future Claude or shell adapters may be useful when
their evidence can be normalized.

## Product Position And Non-Goals

V19 defines adapter interfaces for execution backends.

Non-goals:

- do not make every backend trusted by default,
- do not support opaque transcripts without normalized evidence,
- do not allow adapters to bypass DWM Core gates,
- do not require network access for local workflows.

## Workflow Architecture

Adapter contract:

- `capabilities.json`,
- `prepare`,
- `run`,
- `collect`,
- `verify`,
- `cancel`,
- `resume`.

Each adapter returns normalized evidence:

- command,
- environment summary,
- stdout/stderr/transcript,
- files touched,
- exit status,
- verification outputs,
- adapter hash.

## Execution Model

DWM Runner calls adapters through an allowlisted interface. Adapters may be
first-party or optional, but DWM Core accepts only normalized evidence ledgers.

## Safety And Verification Gates

Adapters declare risk capabilities. Any adapter requesting write, network,
secret, production, database, dependency, public API, deletion, external
message, or history rewrite capability requires matching gates.

## Evaluation Fixtures

- positive: Codex adapter emits normalized evidence,
- positive: fixture adapter runs without network,
- negative: OMX adapter missing capabilities is rejected,
- negative: opaque transcript is not accepted as proof.

## Release Plan

1. Define adapter schema.
2. Add first-party fixture and Codex adapters.
3. Add optional OMX adapter only after interface stability.
4. Add adapter compatibility tests to release gate.
