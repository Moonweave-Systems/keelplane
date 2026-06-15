# V11 Operator Guidance Spec

## Research And Prior Art

V10 made DWM visible as a product CLI, but the operator still has to interpret
raw status fields by hand. Prior workflow launchers such as OMX focus on
starting work, multiplexing processes, and managing execution state. DWM should
not jump straight to that layer before it can explain the next safe action from
its own deterministic artifacts.

The V11 slice adds operator guidance over existing runs. It keeps artifacts as
the source of truth and turns `status.json`, `hashes.json`, selected phases,
invalidators, and human approvals into one stable recommendation.

## Product Position And Non-Goals

V11 adds `dwm next`, a read-only operator guidance command. It answers:

- is this run trusted,
- what status is it in,
- what is the next safe action,
- is human approval required,
- which command should the operator inspect next.

Non-goals:

- do not execute workflow stages,
- do not launch Codex, OMX, subagents, tmux, worktrees, or browsers,
- do not create approval artifacts,
- do not install dependencies,
- do not call the network,
- do not mutate `out/` or source files from the product CLI.

## Workflow Architecture

The command surface becomes:

- `status`: summarize one DWM run.
- `next`: verify one run and recommend the next safe operator action.
- `doctor`: check the repo product surface and canonical dogfood chain.
- `commands`: print release, dogfood, and product command sets.

`next` reuses the existing path safety and hash-ledger validation primitives.
It returns structured JSON with:

- `trusted`,
- `trust_checks`,
- `verified_artifact_hashes`,
- `recommendation.action`,
- `recommendation.requires_user_approval`,
- `recommendation.safe_default`,
- `recommendation.commands`,
- `recommendation.blocked_by`.

## Execution Model

V11 remains a read-only control-plane slice. It reads one run under repo-local
`out/`, verifies the run's local hash ledger when present, and derives a
recommendation from the trusted status shape.

Recommendation states:

- `complete`: workflow is already complete.
- `repair-required`: artifacts are untrusted, stale, malformed, or invalidated.
- `human-approval-required`: selected next phase is `human_gate`.
- `next-phase-ready`: selected phases exist and can be dispatched by the
  matching deterministic adapter.
- `inspect`: no selected next phase is recorded.

## Safety And Verification Gates

`next` must reject paths outside `out/`, unknown run layouts, symlinked
artifacts, malformed JSON, stale hash ledgers, and missing hash evidence. It
must not convert a model message into approval or claim that an external action
has run.

Release verification includes:

- `python scripts/dwm.py --self-test`,
- `python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json`,
- `python scripts/dwm.py commands --kind product --json`,
- `python scripts/check_contract.py`,
- `python scripts/check_release_text.py .`.

## Evaluation Fixtures

The first slice uses existing repo artifacts:

- positive: `out/v9/v32-semantic-dogfood` returns trusted `complete`,
- positive: `commands --kind product` includes the `next` command,
- negative: in-memory self-test tampering of the canonical hash ledger is
  rejected before a recommendation is trusted,
- negative: outside-`out/` paths remain rejected.

## Release Plan

1. Add `next` and product command discovery to `scripts/dwm.py`.
2. Add V11 workflow plan, spec, and keep decision.
3. Update README and roadmap so V11 is visible as the current operator surface.
4. Extend `scripts/check_contract.py` to validate V11 docs and CLI output.
5. Run release checks and reviewer pass before committing.
