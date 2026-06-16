# V11 Operator Guidance Decision

Decision: keep

Command used to verify operator guidance:

```bash
python scripts/dwm.py --self-test
```

Dogfood operator commands:

```bash
python scripts/dwm.py next --run out/v9/v32-semantic-dogfood --json
python scripts/dwm.py commands --kind product --json
```

Generated dogfood values:

- `run_id`: `v32-semantic-dogfood`
- `version`: `v9`
- `status`: `workflow-complete`
- `resume_state`: `resumable`
- `trusted`: `true`
- `verified_artifact_hashes`: `4`
- `recommendation.action`: `complete`
- `recommendation.requires_user_approval`: `false`
- `product_command_count`: `7`

This decision covers the first read-only DWM operator guidance surface. It does not claim workflow execution, worker execution, Codex CLI execution, OMX
execution, subagent spawning, worktree merging, commits, pushes, dependency
installation, production deployment, external messaging, secret access, network
access, or autonomous execution beyond recommending the next safe operator
action from existing deterministic artifacts.
