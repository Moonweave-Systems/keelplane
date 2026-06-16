# V10 Product Packaging Decision

Decision: keep

Command used to verify product packaging:

```bash
python scripts/dwm.py --self-test
```

Dogfood product commands:

```bash
python scripts/dwm.py status --run out/v9/v32-semantic-dogfood --json
python scripts/dwm.py doctor --json
python scripts/dwm.py commands --kind release --json
```

Generated dogfood values:

- `run_id`: `v32-semantic-dogfood`
- `version`: `v9`
- `status`: `workflow-complete`
- `resume_state`: `resumable`
- `completed_phase_ids`: `release_inventory, evidence_review, release_decision, human_gate`
- `human_approved_phase_ids`: `human_gate`
- `selected_phase_ids`: ``
- `doctor_ok`: `true`
- `release_command_count`: `70`

This decision covers the first read-only DWM product CLI surface. It does not claim workflow execution, worker execution, Codex CLI execution, OMX execution, subagent spawning, worktree merging, commits, pushes, dependency installation, production deployment, external messaging, secret access, network access, or autonomous execution beyond reporting existing deterministic artifacts.
