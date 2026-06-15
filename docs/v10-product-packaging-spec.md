# V10 Product Packaging Spec

## Research And Prior Art

DWM already has a deterministic artifact chain from V0.5 through V9. The gap is
not another runtime layer; it is a stable product surface. Prior art such as
OMX and other workflow launchers focuses on operator UX, process management,
tmux/worktree handling, and broad execution. DWM should not copy that first.
Its useful product position is a control-plane that can summarize trusted
artifacts and tell the operator what is safe to do next.

## Product Position And Non-Goals

V10 packages the existing control-plane into a repo-local CLI called
`scripts/dwm.py`. The first slice is intentionally read-only. It reports the
state of existing artifacts, checks whether the repo has the expected product
surfaces, and prints the release command set.

Non-goals:

- do not execute workflow stages from `scripts/dwm.py`,
- do not launch Codex, OMX, subagents, tmux, worktrees, or browsers,
- do not install dependencies,
- do not call the network,
- do not mutate `out/` or source files from the product CLI.

## Workflow Architecture

The CLI exposes three user-facing commands:

- `status`: read one DWM run directory and summarize status, resume state,
  completed phases, selected phases, human approvals, invalidators, and
  snapshots.
- `doctor`: check the repository has required scripts, docs, approval fixtures,
  and the canonical V9 dogfood completion artifact.
- `commands`: print the canonical release commands and the canonical dogfood
  command set.

`--self-test` exercises these surfaces without modifying tracked files or
regenerating workflow artifacts.

## Execution Model

V10 is a packaging layer, not an executor. It uses Python stdlib only and reads
JSON/Markdown files already present in the repository. The default canonical run
is `out/v9/v32-semantic-dogfood`, because that is the first dogfood chain that
reaches `workflow-complete` through a tracked human approval artifact.

The CLI can output human-readable text or stable JSON with `--json`.

## Safety And Verification Gates

The CLI must reject paths outside `out/`, symlinked status files, missing
status artifacts, malformed JSON, and unknown run layouts. Doctor must report
failed checks instead of repairing them.

Release verification includes:

- `python scripts/dwm.py --self-test`,
- `python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json`,
- `python scripts/dwm.py doctor --json`,
- `python scripts/check_contract.py`,
- `python scripts/check_release_text.py .`.

## Evaluation Fixtures

The first slice uses existing dogfood artifacts as the fixture:

- positive: `out/v9/v32-semantic-dogfood` reports `workflow-complete`,
- negative: a missing run path returns a structured nonzero CLI error,
- negative: malformed JSON parsing is exercised against an existing non-JSON
  repository file without writing temporary repo-local artifacts.

## Release Plan

1. Add `scripts/dwm.py` with `status`, `doctor`, `commands`, and `--self-test`.
2. Add V10 workflow plan, spec, and keep decision.
3. Update README and roadmap so V10 is visible as the current product surface.
4. Extend `scripts/check_contract.py` to validate V10 docs and CLI output.
5. Run the release gate and reviewer pass before committing.
