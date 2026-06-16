# V14 Session And Worktree Runtime Decision

Decision: keep

Command used to regenerate the V14 summary:

```bash
python scripts/dwm_runner.py --manifest fixtures/v14/manifest.json --out out/v13/v14-final
```

Generated summary values:

- `suite_id`: `v14-final`
- `fixture_count`: 5
- `required_fixture_count`: 5
- `required_passed`: 5
- `passed`: 5
- `failed`: 0
- `skipped`: 0
- `decision`: `keep`

This decision covers durable session/worktree state only. It does not claim
multi-worker scheduling, automatic worktree cleanup, dashboard behavior,
branch deletion, force push, hard reset, or secret access.
