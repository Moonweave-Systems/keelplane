# V126 Real Paired Dogfood Evidence Spec

Status: spec for the next real milestone. Not yet implemented.
Date: 2026-06-24.

Parent direction: `docs/v125-direction-check-roadmap.md` (Section 6.1, "now").

## 1. Research and prior art

The central product claim — that a governed run (Agent Fabric profile + Depone
capture/verify) is safer or higher-quality than a direct agent run — has never
been tested against a real run. After V107-V124 the Agent Fabric chain only ever
processed synthetic fixtures:

- `depone/agent_fabric/dogfood_evidence.py` consumes a capture manifest, but its
  self-test reads `depone/fixtures/agent_fabric/capture_manifest_shell.json`.
- `depone/agent_fabric/paired_evidence.py` builds its dogfood input inline in the
  self-test rather than from a captured run.
- `scripts/dwm_live_proof.py` already shells out to a live coding CLI
  (`subprocess.run`, `backend: codex-cli`, `mode: installed-codex`) and records a
  V103 two-arm comparison (`direct-codex` vs `dwm-controlled`, `files_touched`,
  `proof_ref`), but it is driven from `fixtures/live-proof/seed`.
- `scripts/dwm_dogfood_pair.py` already validates a real `direct-codex` receipt
  against a DWM measurement, requires a human-approval gate scoped to
  `direct-codex`, forbids overclaim terms, and binds `task_id` and
  `evidence_path`.

The capability to cross the value-proving threshold exists; it was pointed at
synthetic seeds. The mid-2026 consensus is unambiguous that deterministic,
ground-truthed, held-out checks (tests/typecheck/CI) are the pass/fail authority
and that paired comparison against a direct baseline is required before any
benefit claim (see V125 Sections 3-4 and source index).

## 2. Product position and non-goals

Position: V126 produces the first non-fixture, hash-bound capture manifest from
a real coding task, runs it once directly and once through an Agent Fabric
profile, and emits a real paired dogfood evidence report. It closes the gap
between "the plumbing exists" and "a real run has been verified."

This requires zero change to the core boundary. Depone Core still does not call a
model. A human or a native harness runs the agent; Depone observes the resulting
repository state and runs the declared verification command.

Non-goals:

- No public benefit, quality, speed, or superiority claim. n=1 is evidence, not
  proof; the report must carry the existing claim policy ("live n=1 only; no
  direct-agent superiority claim").
- No model calls from Depone Core; no provider routing; no API keys.
- No new Agent Fabric profile, role, or compiler milestone (those are frozen per
  V125 Section 6.5).
- No automatic public-claim approval. The paired-evidence decision may at most
  reach `paired-evidence-ready-source-only` and still requires a human gate.

## 3. Workflow architecture

```text
real localized task (one ownership region, declared verification command)
  |
  v
ARM A: direct run            ARM B: governed run
  human/harness runs the     human/harness runs the task through one Agent
  task directly under a      Fabric profile (e.g. feature-pipeline or
  native harness             direct-small-fix) under the same harness
  |                            |
  v                            v
Depone observer step (deterministic, no model):
  - read `git diff --name-only` and a bounded `git diff` summary
  - run the task's declared verification command, capture argv/cwd/exit/output
  - assemble an observer_capture payload with observed_by = "depone-observer"
  |
  v
build_capture_manifest(fixture, observer_capture=..., allowed_touched_files=...)
  -> A1-local-observed manifest, hash-bound (capture_bridge.py)
  |
  v
build_dogfood_evidence_report(capture_manifest)   (dogfood_evidence.py)
  -> requires A1 + observed-local-capture + test_output.status == "passed"
  |
  v
build_paired_evidence_report(adapter_smoke_report, dogfood_evidence)
  -> paired-evidence-ready-source-only | blocked-*   (paired_evidence.py)
  |
  v
paired delta record (direct vs governed): escaped-defect, review-precision,
  missing-evidence, files-touched, elapsed; labeled n=1, no superiority claim
```

The observer step is the load-bearing new piece. Today `observer_capture` is
hand-authored in fixtures; V126 makes Depone generate it by observing real repo
state and running the declared command, so the A1 evidence is genuinely observed,
not asserted.

## 4. Execution model

1. Define one real task in a small task descriptor: `task_id`, ownership region
   (`allowed_touched_files`), the exact verification command, and the acceptance
   claim with a falsifier. A real Depone maintenance task is a good first choice
   (for example a localized bug fix or a docs/code consistency fix), so the run
   is genuinely useful work, not a toy.
2. Run ARM A (direct) and ARM B (governed) in isolated worktrees so the two arms
   do not contaminate each other. The agent execution is performed by the harness
   or the human, not by Depone Core.
3. For each arm, run the Depone observer step to produce an `observer_capture`
   that conforms to `capture_bridge.REQUIRED_OBSERVER_FIELDS`
   (`observed_by`, `source_fixture_hash`, `diff_summary`, `touched_files`,
   `test_output`, `command_receipts`). `command_receipts` must be non-empty and
   each receipt records `command`, `exit_code`, and a log path.
4. Build the A1 capture manifest per arm and validate it
   (`validate_capture_manifest` must return no errors). Tamper, stale source
   hash, and out-of-ownership touched files must fail closed, exactly as the
   existing capture-bridge self-test asserts.
5. Build the dogfood evidence report per arm and the paired evidence report.
6. Emit a paired delta record comparing the two arms on observable metrics only.
7. Replace the inline-fabricated dogfood input in the paired-evidence self-test
   with the captured fixture from the governed arm, so the self-test exercises a
   real observed capture rather than a synthetic dict.

## 5. Safety and verification gates

- Reuse the existing `dwm_dogfood_pair.py` human-approval gate: a `direct-codex`
  receipt requires a human approval scoped to `direct-codex`; overclaim terms are
  rejected; `task_id` and `evidence_path` are bound.
- Depone runs only the task's declared verification command and read-only git
  inspection. It does not run arbitrary commands from the agent transcript, does
  not install dependencies, does not access the network, and does not message
  externally. Any such need stops with a blocked decision and a safe default.
- Assurance stays bounded: a real local observation reaches A1-local-observed.
  Worktree isolation may support A2 only when the observer runs outside the
  agent's writable space; otherwise the report stays A1. No agent may upgrade
  assurance or write the observer-owned manifest.
- The paired report carries the n=1 claim policy and makes no superiority claim.

## 6. Evaluation fixtures

Required cases (extend `depone/fixtures/agent_fabric/` and the dogfood manifest):

- one real captured governed-arm manifest that validates as A1 and yields
  `dogfood-evidence-ready-source-only`;
- the same manifest tampered (observer_capture mutated) must yield
  `observer_capture_hash mismatch` and block;
- a stale `source_fixture_hash` must block;
- a touched file outside `allowed_touched_files` must block;
- a `test_output.status` other than `passed` must yield
  `blocked-dogfood-tests-not-passed`;
- the paired report with a ready adapter smoke and the real dogfood evidence must
  reach `paired-evidence-ready-source-only`; a non-passing arm must block.

## 7. Implementation plan

- Phase 1: add the observer step (deterministic git inspection + declared-command
  runner producing `observer_capture`). New code lives under `depone/` package
  with stdlib only; it does not call a model.
- Phase 2: add the task descriptor and the two-arm capture driver; reuse
  `dwm_live_proof.py` comparison shape and `dwm_dogfood_pair.py` receipt/gate
  validation rather than inventing a parallel path.
- Phase 3: capture one real task end to end, store the governed-arm manifest as a
  tracked fixture, and rewire the paired-evidence self-test to consume it.
- Phase 4: write `docs/v126-decision.md` recording the captured `task_id`, the
  observed deltas, and the explicit non-superiority statement.

Done means: a real, hash-bound A1 capture from an actual run exists; the paired
evidence report reaches ready-source-only from that real capture; the
self-test no longer fabricates its dogfood input; and the decision doc records
the n=1 deltas without any superiority claim.

Required verification:

- `python scripts/check_contract.py --tier changed`
- the new observer and capture-driver self-tests
- `PYTHONPATH=. python3 -m depone agent-fabric-paired-evidence --self-test`
- `python scripts/check_release_text.py .` and `python scripts/check_whitespace.py .`
