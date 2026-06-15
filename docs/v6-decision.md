# V6 Runtime Ingestion Decision

Decision: keep

Command used to verify runtime ingestion:

```bash
python scripts/ingest_worker_review.py --self-test
```

Dogfood commands:

```bash
python scripts/ingest_worker_review.py --review out/v5.5/v32-semantic-dogfood --out out/v6/v32-semantic-dogfood
python scripts/ingest_worker_review.py --resume out/v6/v32-semantic-dogfood
```

Generated dogfood values:

- `run_id`: `v32-semantic-dogfood`
- `status`: `frontier-ready`
- `resume_state`: `resumable`
- `completed_phase_ids`: `release_inventory`, `evidence_review`
- `reviewed_phase_ids`: `evidence_review`
- `ready_phase_ids`: `release_decision`
- `selected_phase_ids`: `release_decision`

This decision covers ingestion of one deterministic V5.5 reviewed worker
result into the next frontier artifact. It does not claim multi-result fan-in,
worker repair, next-packet execution, Codex CLI execution, OMX execution,
subagent spawning, worktree merging, commits, pushes, dependency installation,
production deployment, external messaging, secret access, or autonomous
workflow completion.
