# V105 Proposal: Trust-Bounded Native Execution

Status: Proposed final draft
Date: 2026-06-23

## 1. Decision

Keelplane shall be the policy and evidence control plane around native agent
harnesses. It shall not implement another general-purpose model loop, provider
router, or multi-agent scheduler.

Keelplane may offer an optional thin runner that launches an external harness
under an explicit run contract. That runner is an observer and custody boundary,
not the model runtime.

```text
objective
  -> plan contract
  -> native lowering + capability report
  -> Codex / Claude Code execution
  -> deterministic capture or adapter import
  -> policy evaluation
  -> decision + assurance + report
```

## 2. Product thesis

> Agents make changes and claims. A trusted observer records facts. Keelplane
> evaluates whether those facts satisfy a declared policy and states the
> assurance limit explicitly.

A matching hash proves byte integrity, not author identity, command execution,
or provider authenticity.

## 3. Component boundaries

### Keelplane Core

Owns plan/policy schemas, activation, claim evaluation, gate/budget policy,
evidence normalization, decision/assurance, reports, and schema compatibility.
Core is deterministic and does not call a model or run task commands.

### Keelplane Capture

Owns safe local observation, streaming hashes, receipt import, path/redaction
policy, manifest, ledger, and local seal. Passive capture never executes the
development task or artifact-provided commands.

### Keelplane Runner (optional)

Owns external harness process launch, isolated workspace/worktree, stdout/stderr
custody, timeouts, attempt IDs, and append-only attempts. It does not own native
model reasoning, tools, or provider auth.

### Native harnesses

Codex, Claude Code, and other harnesses own authentication, hidden system
prompts, model choice, agent/session lifecycle, permission prompts, tools,
sandboxes, worktrees, MCP, UI, and native transcripts.

### Reference packs

Packs map portable roles to native custom agents. They are examples, not the
source of truth and not required for verification.

## 4. Primary user and first wedge

Primary user:

> A local power user or small engineering team already using official Codex
> and/or Claude Code subscriptions who wants lower rework, fresh review, and an
> honest record of what was checked.

First supported use cases:

1. medium feature or bug fix;
2. read-only code/security audit;
3. cross-harness review;
4. bounded multi-module migration.

Conductor/LangGraph remain later targets until the native coding-agent loop
proves user value.

## 5. Invariants

1. Claims are not observations.
2. Integrity is not authenticity.
3. Native compilation must report semantic loss.
4. Missing required evidence is inconclusive.
5. Producers cannot approve their own risky actions.
6. Agents cannot own the authoritative seal.
7. Direct execution is default for small tasks.
8. Productivity claims require paired evaluation.
9. Commands and side effects must be declared or observed with origin.
10. The protocol remains provider-neutral.

## 6. Decision and assurance

Decision:

- `pass`: all required policy checks succeeded;
- `fail`: required evidence contradicts a claim or policy was violated;
- `inconclusive`: evidence/evaluator capability is absent or stale.

Assurance:

- `A0-claims-only`;
- `A1-local-observed`;
- `A2-isolated-observed`;
- `A3-externally-attested`.

Legacy mapping may remain for compatibility:

| Decision | Legacy verdict |
|---|---|
| pass | verified |
| fail | refuted |
| inconclusive | insufficient-evidence |

The new fields are authoritative.

## 7. Plan model corrections

Separate:

- `objective`: desired outcome;
- `claims`: what must be demonstrated;
- `policy`: evidence, gate, freshness, assurance requirements;
- `execution_hints`: roles, ordering, parallelism, native profile.

Execution hints are never proof that execution followed the plan.

Until context-aware planning is implemented and evaluated, `keelplane design`
should be documented as a deterministic scaffold. A future surface may split:

```text
keelplane plan scaffold
keelplane plan import
keelplane plan validate
keelplane plan explain
```

A required claim should look like:

```json
{
  "claim_id": "auth-refresh-serialized",
  "statement": "Concurrent refresh requests cannot rotate one token twice.",
  "falsifier": "A concurrent test shows duplicate rotation.",
  "required_evidence": ["command:auth-race-test", "review:correctness"],
  "minimum_assurance": "A1-local-observed",
  "evaluator": "command-and-review-policy"
}
```

## 8. Native lowering, not bijection

A native compiler loads or probes a capability manifest, for example:

```json
{
  "target": "claude-code",
  "target_version": "observed-or-unknown",
  "subagents": true,
  "agent_teams": "experimental",
  "worktree_isolation": true,
  "per_agent_permissions": "partial",
  "team_session_resume": false,
  "structured_handoffs": false
}
```

Compiler output:

```text
team.prompt.md
run-contract.json
expected-evidence.json
compile-report.json
```

Each plan feature is classified as:

- `exact`;
- `approximated`;
- `omitted-noncritical`;
- `unsupported-critical`.

Compilation fails on unsupported critical gates or verification controls.

## 9. Proposed product surface

```bash
keelplane capture \
  --plan workflow.plan.json \
  --repo . \
  --run-id <id> \
  --out .keelplane/runs/<id>/attempt-01

keelplane verify workflow.plan.json \
  --evidence .keelplane/runs/<id>/attempt-01 \
  --policy default

keelplane report verification-report.json \
  --out verification-report.md
```

Reference-pack convenience:

```bash
keelplane init --harness codex|claude|both --profile feature-pipeline
```

Native runbook generation:

```bash
keelplane compile workflow.plan.json --target codex-native
keelplane compile workflow.plan.json --target claude-native
```

`compile` does not launch agents.

## 10. Verification kernel changes required first

1. Required claims with no evaluator are inconclusive.
2. Gates distinguish declared/requested/approved/denied/executed/expired/N/A.
3. Budgets use invocation records, not filenames.
4. Plan-level controls are not duplicated into every phase.
5. Command receipts carry origin and process status.
6. Reviews are bound to input snapshot and independence dimensions.
7. Manifest paths are independently discovered and hashed.
8. Files are streamed with limits.
9. Unsafe/colliding paths and special files are rejected.
10. Reports separate decision and assurance.

## 11. Subscription-only baseline

Reference packs:

- inherit the signed-in native model;
- contain no API keys or provider route;
- install no third-party MCP server;
- enable no bypass-permission mode;
- modify no global configuration;
- cap concurrency;
- state that API-key/environment precedence remains a harness concern.

Keelplane cannot prove subscription authentication unless the native harness
emits verifiable identity evidence. `auth_mode` is usually declared/imported.

## 12. Versioning

- Product package uses SemVer independently of V105 milestone labels.
- Plan, evidence, run-contract, and report schemas version independently.
- Major mismatch fails closed.
- Unknown security-relevant fields do not satisfy policy.
- Minor extensions must be monotonic: ignoring them cannot turn deny or
  inconclusive into pass.
- Native packs publish tested harness-version ranges.

## 13. Acceptance criteria

1. Current claim/adversarial false-pass path is stopped.
2. Local capture creates A1 evidence without agent-owned seal paths.
3. Missing required evidence returns inconclusive.
4. Contradictory command/test evidence returns fail.
5. Stale review snapshots are rejected.
6. Gate approvals cannot be replayed against changed action digest.
7. Tampering invalidates the local seal.
8. Both native packs validate structurally.
9. `feature-pipeline` completes one real task end to end.
10. Paired evaluation is published without superiority overclaim.

## 14. Non-goals

- a new model runtime or provider router;
- a general distributed scheduler;
- dashboard before the CLI loop is useful;
- undocumented private-state scraping;
- provider identity inferred from text/filenames;
- defect-absence claims from passing tests;
- more roles without measured benefit;
- public productivity graphs from internal readiness scores.
