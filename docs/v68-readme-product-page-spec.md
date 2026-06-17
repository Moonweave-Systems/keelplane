# V68 README Product Page Spec

Status: implemented README product-page cleanup in `README.md`.

## Research and Prior Art

The README had drifted into a release-note stream. That made the project look
busy but not easy to understand. The better product-page shape is concise:
what DWM is, how to run it, what exists, what is still honest, and where deeper
operator detail lives.

## Product Position and Non-Goals

V68 keeps README reader-facing. It does not remove implementation history; it
moves it to docs.

Non-goals:

- do not hide safety caveats,
- do not claim upward benchmark performance,
- do not delete command reference details,
- do not treat process progress as benchmark evidence.

## Workflow Architecture

The README now keeps:

- quick product positioning,
- quickstart demo,
- normal operator loop,
- current capability table,
- honest claim boundary table,
- process progress graph,
- benchmark evidence graph,
- short documentation links.

Detailed commands live in `docs/command-reference.md`. Versioned slice history
lives in `docs/release-history.md`.

## Execution Model

The process graph asset comes from the V67 promotion bundle and is tracked as:

- `assets/dwm-dogfood-progress.svg`,
- `assets/dwm-dogfood-progress.json`.

It is embedded as process evidence only. The benchmark graph remains separate
as `assets/dwm-live-benchmark.svg`.

## Safety and Verification Gates

V68 preserves the README claim boundaries:

- generated `out/` directories are verification evidence, not source truth,
- public trend promotion requires real release history,
- direct-agent superiority is not claimed,
- process progress is not an upward benchmark claim.

## Evaluation Fixtures

The release contract checks that README points to the new command and history
docs, embeds the process graph, preserves benchmark boundaries, and keeps the
tracked process asset metadata present.

## Release Plan

V68 is a public-page cleanup. Later slices can improve visual assets or add
real benchmark trend graphs only after the existing benchmark promotion gates
clear.
