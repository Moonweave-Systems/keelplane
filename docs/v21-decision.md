# V21 Product Shell Decision

Decision: keep

Commands used to verify the V21 product shell:

```bash
python scripts/dwm.py plan "V21 shell smoke" --out out/v21/release-plan-smoke --json
python scripts/dwm.py run "V21 shell smoke" --out out/v21/release-run-smoke --json
python scripts/dwm.py resume --run out/v21/release-run-smoke --json
python scripts/dwm.py --self-test
```

Generated shell values:

- `plan.status`: `planned`
- `plan.decision`: `plan-only`
- `run.status`: `blocked`
- `run.decision`: `blocked-before-live-execution`
- `resume.trusted`: `true`
- `resume.verified_artifact_hashes`: `1`
- `blocked_by`: `ERR_DWM_SHELL_LIVE_EXECUTION_BLOCKED`

This decision covers the first product-shell command surface only. It does not
claim live model planning, live adapter execution, worker execution, worktree
creation, session attachment, fanout, deployment, secret access, or autonomous
completion.
