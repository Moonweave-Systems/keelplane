# V8 Frontier Review Ingestion Decision

Decision: keep

Command used to verify frontier-review ingestion:

```bash
python scripts/ingest_frontier_review.py --self-test
```

Dogfood commands:

```bash
python scripts/ingest_frontier_review.py --review out/v7.5/v32-semantic-dogfood --out out/v8/v32-semantic-dogfood
python scripts/ingest_frontier_review.py --resume out/v8/v32-semantic-dogfood
```

Generated dogfood values:

- `run_id`: `v32-semantic-dogfood`
- `status`: `frontier-ready`
- `resume_state`: `resumable`
- `completed_phase_ids`: `release_inventory, evidence_review, release_decision`
- `reviewed_phase_ids`: `evidence_review, release_decision`
- `ready_phase_ids`: `human_gate`
- `selected_phase_ids`: `human_gate`
- `state_hash`: `53ffa287b440c6c8c0a845e5448e202a227581f30671f402d6df3b2f2441e730`

This decision covers ingestion of one deterministic V7.5 reviewed frontier
result into the next frontier artifact. It does not claim workflow completion,
human approval, next-packet execution, Codex CLI execution, OMX execution,
subagent spawning, worktree merging, commits, pushes, dependency installation,
production deployment, external messaging, secret access, or autonomous
workflow completion.
