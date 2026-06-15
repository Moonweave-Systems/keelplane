# V17 Dashboard And Approval UI Spec

Status: planned; not implemented.

## Research And Prior Art

OMX-style tools are easier to use because operators can see sessions, teams,
and status. DWM needs a product shell that shows trusted evidence, gates, and
next actions without weakening the artifact contract.

## Product Position And Non-Goals

V17 adds a local dashboard/HUD and approval queue.

Non-goals:

- do not make UI state authoritative,
- do not approve gates from untracked chat messages,
- do not hide raw artifacts,
- do not require a hosted service.

## Workflow Architecture

The dashboard reads DWM artifacts and exposes:

- run list,
- current recommendation,
- trust checks,
- evidence browser,
- review queue,
- human gate approval form,
- command preview.

## Execution Model

The UI is local-first. It may write approval artifacts only through an explicit
tracked approval schema and only after rendering the evidence being approved.

## Safety And Verification Gates

Every approval must be traceable to a run, packet, evidence set, approver,
timestamp, and allowed output. UI approval cannot authorize worker execution,
merge, deployment, external message, secret access, or dependency installation
unless the matching risk gate explicitly allows it.

## Evaluation Fixtures

- positive: render V9 dogfood complete state,
- positive: render V8 human gate approval queue,
- negative: mismatched approval refused,
- negative: stale evidence warning visible.

## Release Plan

1. Add static/local dashboard prototype.
2. Add rendered screenshot or DOM contract tests.
3. Add approval artifact writer only after read-only UI is proven.
4. Keep CLI as the authoritative fallback.
