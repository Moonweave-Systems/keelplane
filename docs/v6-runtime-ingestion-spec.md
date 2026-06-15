# V6 Runtime Ingestion Spec

Status: first slice implemented
Date: 2026-06-15

## Purpose

V6 consumes reviewed V5.5 worker results and turns them into the next scheduler
frontier. It is the first slice where a later worker result can satisfy a phase
dependency.

The workflow is:

```text
V4 scheduled packet
-> V4.5 dispatch bundle
-> V5 worker result evidence
-> V5.5 reviewed worker result
-> V6 ingested runtime frontier
```

V6 still does not execute workers. It only records that a reviewed phase is
complete and emits the next ready packet.

## Workflow Design

Source plan: `docs/v6-runtime-ingestion.workflow.plan.json`.

Patterns:

- Sequential
- Resume And Cache
- Adversarial Verify

Phases:

1. Review validation: require an owned V5.5 directory that resumes to
   `review-approved`.
2. Lineage reconstruction: follow review -> V5 result -> V4.5 dispatch -> V4
   schedule -> V3/V1 plan snapshot.
3. Frontier generation: append the reviewed phase to `completed_phase_ids` and
   compute next ready phases from the original plan.
4. Resume verification: recompute source, state, packet, prompt, journal, and
   hashes.

## Command Contract

```bash
python scripts/ingest_worker_review.py --review out/v5.5/<run_id> --out out/v6/<run_id>
python scripts/ingest_worker_review.py --resume out/v6/<run_id>
python scripts/ingest_worker_review.py --self-test
```

## Accepted Inputs

V6 accepts only:

- an owned V5.5 review directory,
- `status.json` with `status: review-approved`,
- clean V5.5 resume,
- `review.json` with verdict `approve`,
- a reviewed source phase that was selected by the original V4 schedule,
- a recoverable V4 schedule and V1 plan snapshot.

V6 rejects:

- stale or malformed review artifacts,
- `needs-human`, `changes-requested`, or `invalid` reviews,
- reviewed phases not selected by the V4 schedule,
- duplicate completion of an already completed phase,
- missing V4/V3/V1 lineage,
- symlinked or outside-`out/v6` output paths.

## Output Model

```text
out/v6/<run_id>/
├── .ingest_worker_review-owned.json
├── run.json
├── state.json
├── hashes.json
├── packets/
│   ├── 0001.<phase>.packet.json
│   └── 0001.<phase>.prompt.md
├── journal/0000.json
├── status.json
└── resume.md
```

`state.json` records:

- `completed_phase_ids`,
- `reviewed_phase_ids`,
- `ready_phase_ids`,
- `selected_phase_ids`,
- `blocked_phases`,
- `reviewed_results`.

## First Slice Rules

For the dogfood result, V6 should mark `evidence_review` complete and select
`release_decision` as the next frontier packet.

Approve path requires:

1. V5.5 review status is `review-approved`.
2. V5.5 resume is `resumable`.
3. `review.json.verdict` is `approve`.
4. `review.json.source_phase_id` is selected by the V4 schedule.
5. The source phase is not already completed.
6. The original V4 schedule, V3 runtime, and V1 plan hashes still validate.
7. Generated `state.json`, packet, prompt, and journal match resume
   recomputation.

## Non-Goals

- Do not execute the next packet.
- Do not call Codex CLI, OMX, subagents, network APIs, or paid APIs.
- Do not merge worker outputs into the repository.
- Do not implement arbitrary multi-result fan-in yet.
- Do not bypass `needs-human` or rejected V5.5 reviews.

## Release Criteria

The slice is `keep` only if:

- `python scripts/ingest_worker_review.py --self-test` passes,
- dogfood ingestion over `out/v5.5/v32-semantic-dogfood` returns
  `frontier-ready`,
- clean resume returns `resume_state: resumable`,
- tampered generated state invalidates resume,
- no worker execution or runtime backend execution is introduced.
