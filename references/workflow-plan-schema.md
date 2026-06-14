# Workflow Plan Schema

Canonical artifact: `workflow.plan.json`

Schema version: `0.5`

This reference defines the file contract emitted by substantial
`dynamic-workflow-designer` outputs and consumed by
`scripts/evaluate_plan.py`. JSON is the source of truth. A rendered blueprint is
derived from the same data and must not add requirements that are absent from
the JSON.

## Top-Level Fields

Required top-level fields:

- `schema_version`: must be `"0.5"`.
- `plan_id`: stable fixture or run identifier.
- `created_by`: must be `"dynamic-workflow-designer"` for candidate plans.
- `source_prompt`: original user prompt.
- `activation`: activation or downgrade decision.
- `objective`: desired outcome.
- `surfaces`: surfaces in scope.
- `assumptions`: claims plus verification steps.
- `patterns`: names from `references/workflow-patterns.md`.
- `phases`: ordered phase records.
- `workers`: worker role records.
- `handoffs`: phase-to-phase artifacts.
- `parallelism`: shape, cap, fan-in rule, and barriers.
- `verification`: falsifiers and required evidence.
- `risk_gates`: gated actions and safe defaults.
- `budget`: agent, round, retry, time, and file-touch limits.
- `resume`: cache, invalidation, and restart rules.
- `execution_path`: mode, first slice, and consumer.

## Activation

`activation` fields:

- `decision`: `"activate"` or `"downgrade"`.
- `matched_thresholds`: threshold labels that justify the decision.
- `downgrade_target`: `"direct-codex"`, `"workflow-router"`,
  `"simple-plan"`, or `null`.
- `reason`: concise routing rationale.

Activated plans must include at least one exclusive threshold and one supporting
threshold.

Exclusive thresholds:

- `downstream-consumer`
- `resumable-handoffs`
- `multi-surface-fanout`

Supporting thresholds:

- `planned-fanout`
- `adversarial-verification`
- `human-gates`

Downgrade artifacts must name a downgrade target, keep `parallelism.shape` as
`"none"`, use empty `workers`, `phases`, `handoffs`, and
`resume.restart_points` lists, set `execution_path.mode` to `direct-codex`, set
`execution_path.consumer` to `human`, and use this exact first-slice instruction:
`Use <downgrade_target> instead of dynamic-workflow-designer for this request.`

## Surfaces

Each surface requires:

- `id`
- `kind`: `repo`, `package`, `artifact`, `api`, `data-source`, `web-source`, or
  `document`
- `locator`
- `access_mode`: `read-only`, `write-proposed`, or `write-approved`

## Workers

Each activated worker requires:

- `id`
- `role`
- `tool_permissions`
- `forbidden_actions`: non-empty list
- `context_budget`
- `prompt_contract`
- `ownership`: non-empty list

`tool_permissions` requires typed boolean fields `read`, `write`, `shell`, and
`network`, plus `mcp_connectors` and `requires_escalation_for`.

`context_budget` requires:

- `max_files`
- `max_tokens`
- `must_include`: non-empty list
- `must_exclude`

`prompt_contract` requires:

- `inputs`: non-empty list
- `required_output_schema`
- `stop_conditions`: non-empty list

## Handoffs

Each activated handoff requires:

- `from_phase`
- `to_phase`
- `artifact`
- `artifact_schema`

`artifact_schema` requires:

- `format`: `json`, `markdown`, `patch`, `test-log`, `rendered-artifact`, or
  `other`
- `required_fields`
- `validation_command`

Activated handoff fields must be non-empty. `artifact_schema.required_fields`
must be a non-empty list.

## Verification And Gates

Each verification item requires:

- `claim_or_output`
- `falsifier`
- `evidence_required`

Each risk gate requires:

- `trigger`
- `safe_default`
- `requires_user_approval`

Risky write, shell, network, and external-message permissions must appear as
risk gates, not only prose. Fixture-specific dependency, production, database,
secret, and history-rewrite expectations are enforced when the manifest names
them as required risk gates.

## First Slice

`execution_path.first_slice` requires:

- `instruction`
- `inputs`: non-empty list
- `expected_output`
- `completion_check`
- `forbidden_actions`: non-empty list

The first slice must be small enough for another agent to start without
reinterpretation and must identify forbidden actions before execution.
Repo-bound plans must include `repository path` in `first_slice.inputs`;
non-repo plans must not include it.
