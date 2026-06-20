# V102 Live Proof 1 Spec

Status: planned live-proof gate
Date: 2026-06-19

## Purpose

V102 changes direction. After V94-V101 grew an increasingly self-referential
readiness, score, ladder, wave, and promotion chain, the central product claim
-- that DWM can actually run a bounded slice of real agent work -- has still
never been closed against a live backend. Every keep-gate path uses
`fixture-command` replays; the installed Codex path in
`scripts/execute_packet.py` exists but remains optional live-smoke evidence, not
product evidence.

V102 is not another gate, score, or audit layer. It is a single closed loop of
real execution: take one tiny seeded task, drive
`plan -> packet -> codex exec -> evidence -> verify -> review` end to end through
the installed Codex backend, and record exactly one trusted evidence bundle under
`out/live-proofs/<id>/`. The success claim is bounded to "live n=1 passed"; it
does not claim superiority over a direct agent.

The meta layer (V94-V101) is frozen for this slice. V102 must not extend it.

## Product Position

- `workflow-router`: route ordinary broad work.
- `keelplane` / DWM Core: design and compile bounded workflow
  slices into inspectable packets.
- V0.5-V3: schema, compiler, one-packet execution, review/repair, runtime entry,
  proven only against fixture and local-shell backends.
- V94-V101: readiness, score, ladder, benchmark-readiness, wave, and promotion
  artifacts. Frozen by V102; tracked only, not extended.
- V102: the first slice that closes a real Codex execution loop and stores its
  evidence, so later promotion artifacts finally have a real attempt to track.

V102 is the prerequisite the promotion chain was waiting on. Until V102 produces
a real attempt, V94-V101 are tracking the readiness of work that has not yet
happened.

## Non-Goals

- Do not extend, re-score, or re-route the V94-V101 meta chain.
- Do not claim DWM is faster, cheaper, or better than a direct agent.
- Do not run the live Codex loop inside the deterministic keep gate.
- Do not execute the live loop against DWM repo tracked files. The only writable
  surface is a run-local seeded worktree.
- Do not commit, push, merge, delete, install dependencies, deploy, access
  secrets, send external messages, or rewrite history.
- Do not auto-spawn parallel workers or advance past the single seeded slice.
- Do not treat a recorded bundle as proof of large-task automation.

## Scope

In scope:

1. A throwaway seeded micro-repo task with a deterministic red->green check.
2. An opt-in command that drives the existing trusted Codex execution path over
   that task and records one `live-proof.json` evidence bundle.
3. A deterministic, Codex-free schema/contract test of the evidence bundle that
   joins the keep gate.
4. Populating exactly one real `dwm-controlled` dogfood comparison metric.
5. README and roadmap reconciliation that states the bounded "live n=1" claim and
   restores the README length gate.

Out of scope: everything in Non-Goals, plus multi-slice runtime, worktree merge,
direct-agent comparison automation (the `direct-codex` mode stays a placeholder
unless a later slice adds it).

## Architecture

V102 reuses trusted code; it does not reimplement execution.

- Compile: `scripts/compile_workflow.py` compiles the seeded plan into one
  first-slice packet, exactly as today.
- Execute: the existing `execute_codex_cli` path in `scripts/execute_packet.py`
  (mode `installed-codex`) runs:

  ```text
  codex exec --skip-git-repo-check --cd <worktree> --sandbox workspace-write \
    --output-last-message <attempt>/transcript.md -
  ```

  with the packet prompt on stdin. V102 adds no new backend; it only fixes this
  path behind an opt-in command and a seeded worktree.
- Verify: the packet's verification command (`pytest -q` on the seed) runs after
  execution, producing `verification_passed`.
- Review: the existing review path
  (`scripts/review_worker_result.py` / `scripts/ingest_worker_review.py`, or the
  V2.5 `execute_packet.py --review` path) records an independent verdict.
- Record: a new thin orchestrator `scripts/dwm_live_proof.py` sequences the above
  and writes one `live-proof.json` bundle plus `live-proof.md`. It must not embed
  its own execution logic; it calls the trusted scripts and aggregates evidence.

### Path split (the core design decision)

Because a live LLM run is non-deterministic, V102 keeps two paths separate:

| Path | Command | In keep gate? | Backend |
| --- | --- | --- | --- |
| Deterministic schema test | `dwm_live_proof.py --self-test`, `--manifest fixtures/v102/manifest.json` | Yes (changed + full) | fixture-command, no Codex |
| Live proof run | `dwm_live_proof.py run ... --i-approve-live-codex` | No | installed-codex |

The keep gate proves the evidence schema and recorder logic deterministically
without a Codex binary. The live run is opt-in, requires the explicit approval
flag and a Codex binary, and produces the real n=1 bundle that is committed once.

## Evidence Schema

`out/live-proofs/<id>/live-proof.json` must contain at least:

```text
proof_id, schema_version, tool
task: { id, seed_path, objective, verification_command }
backend: "codex-cli", mode: "installed-codex", model_provider
worktree: { path, isolated: true, pre_state, post_state }
prompt_hash, packet_hash, adapter_hash
commands: [ argv... ]
files_touched: [ ... ]
transcript_path
verification: { command, returncode, passed, before: "red", after: "green", output_path }
review: { decision, evidence_path }
elapsed_seconds, interruptions
repo_tracked_diff_unchanged: true
dogfood_comparison: { mode: "dwm-controlled", status: "run",
                      metrics: { elapsed_seconds, interruptions, verification_passed } }
decision: "live-proof-pass" | "blocked" | "failed"
claim_policy: "live n=1 only; no direct-agent superiority claim"
source_hashes: { ... }
```

`live-proof.json` is hash-bound and written next to an ownership sentinel
`.dwm_live_proof-owned.json`, matching the repo's existing artifact ownership and
hash-ledger conventions.

Honesty rules:

- Authentication failure records `ERR_EXEC_BACKEND_AUTH` and `decision: blocked`.
  It never reports a pass.
- A nonzero verification result records `decision: failed` with the real output.
- Missing Codex binary records `ERR_EXEC_BACKEND_UNAVAILABLE` and produces no
  pass bundle.

## Execution Model

The live run, in order:

1. Refuse to run unless `--i-approve-live-codex` is present and `codex` is on
   PATH (`ERR_EXEC_BACKEND_UNAVAILABLE` otherwise).
2. Copy `fixtures/live-proof/seed/` into a fresh run-local worktree under
   `out/live-proofs/<id>/workspace` (or a pre-isolated git worktree). The seed is
   throwaway; the DWM repo working tree is never the target.
3. Block if the worktree is dirty before execution (`ERR_EXEC_DIRTY_WORKTREE`),
   matching V2 worktree isolation behavior.
4. Compile the seeded plan into one first-slice packet.
5. Run `installed-codex` execution scoped to the worktree only.
6. Run the verification command and capture red->green evidence.
7. Run the review step and record its verdict.
8. Write the `live-proof.json` bundle, assert
   `repo_tracked_diff_unchanged: true`, and stop.

Bounds: file-touch limit, `timeout_seconds` (default 120, max 3600 from
`timeout_from_config`), and a single attempt. No retry loop, no second slice.

### Human gates

- HUMAN GATE 1: after the spec, seed design, and slice plan are written, stop for
  review before implementing the recorder.
- HUMAN GATE 2: after the deterministic recorder and schema test pass, stop for
  explicit approval before the first live `codex exec` run.

The safe default at every gate is to stop, preserve artifacts, and ask.

## Safety And Verification Gates

- Writable surface limited to the seeded worktree; sandbox is `workspace-write`
  scoped to that path.
- All risky actions (network beyond Codex's own call, install, secret, deploy,
  push, delete, history rewrite) remain blocked by existing gates with safe
  defaults.
- `repo_tracked_diff_unchanged: true` must hold after every run, including the
  live run; the V102 manifest smoke verifies it.
- The deterministic schema test must pass with no Codex binary present.

## Evaluation Fixtures

- `fixtures/live-proof/seed/`: a minimal Python repo with one function and one
  failing `pytest` case (for example, an `add` that returns the wrong value).
  Verification is `pytest -q`; red before, green after the fix. Tracked as the
  canonical seed.
- `fixtures/live-proof/<id>.workflow.plan.json`: a single-phase plan whose packet
  instructs the worker to make the failing test pass, with `pytest -q` as the
  verification command.
- `fixtures/v102/manifest.json`: deterministic schema fixtures for the evidence
  bundle, covering a recorded pass bundle, an auth-blocked bundle, a
  verification-failed bundle, and a tampered/malformed bundle that must be
  rejected. These run as `fixture-command`, never invoking Codex.

## Command Contract

```bash
# Deterministic, keep-gate (no Codex binary required)
python scripts/dwm_live_proof.py --self-test
python scripts/dwm_live_proof.py --manifest fixtures/v102/manifest.json --out out/v102/final

# Opt-in live run (requires codex on PATH and explicit approval)
python scripts/dwm_live_proof.py run \
  --seed fixtures/live-proof/seed \
  --plan fixtures/live-proof/live-proof-1.workflow.plan.json \
  --out out/live-proofs/live-proof-1 \
  --i-approve-live-codex
python scripts/dwm_live_proof.py inspect --proof out/live-proofs/live-proof-1
```

Public manifest execution is limited to `fixtures/v102/manifest.json`.

## Acceptance Criteria

V102 is `keep` only if all of these hold:

- a real `codex exec` ran on the seeded task and its change turned `pytest -q`
  from red to green, proven by captured output, not assertion;
- `out/live-proofs/live-proof-1/` contains a single hash-bound bundle with
  transcript, files-touched, verification output, review verdict, and source
  hashes;
- the bundle records `decision: "live-proof-pass"` and
  `repo_tracked_diff_unchanged: true`;
- exactly one `dwm-controlled` dogfood comparison metric is populated with real
  values instead of `null` / `not-run`;
- `python scripts/dwm_live_proof.py --self-test` and the `fixtures/v102/manifest.json`
  manifest pass with no Codex binary on PATH;
- the live run is opt-in and did not enter or destabilize the deterministic keep
  gate;
- V94-V101 scripts and artifacts and all DWM repo tracked files are unchanged by
  the live run;
- `README.md` states only "live n=1 passed; no superiority claim yet" and passes
  its own length gate (`scripts/check_readme_quality.py`, currently failing at
  206 > 190 lines); the bounded live claim is added while meta-layer prose is
  trimmed so the file shrinks below the limit;
- `docs/spec.md`, `docs/automation-roadmap.md`, and `docs/release-history.md` are
  reconciled (the V88 reconciliation audit stays green), and
  `python scripts/check_contract.py` returns to green.

The decision is `adjust` if the loop runs but the bundle is incomplete, the
red->green evidence is missing, or the claim drifts beyond "live n=1".

The decision is `defer` if a live Codex run cannot be closed safely within the
seeded worktree and gates.

## Decision Output

Record the outcome in `docs/v102-decision.md` after implementation, including the
exact live run command, the `live-proof.json` decision, the verification
returncode, and the populated dogfood metric. It must restate that V102 proves a
bounded live n=1 loop only and makes no superiority, autonomy, or benchmark
claim.

## Open Questions

- Whether the seed should later include a second task category (small refactor)
  before any direct-codex comparison is attempted.
- Whether the live transcript should be redacted or summarized before commit to
  avoid leaking environment paths.
- Whether a later slice adds the `direct-codex` comparison arm needed before any
  relative-quality statement is even considered.
