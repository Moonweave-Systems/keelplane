# Workflow Plan Schema

Canonical artifact: `workflow.plan.json`

Schema version: `0.5`

This reference defines the file contract emitted by substantial
`keelplane` outputs and consumed by
`scripts/evaluate_plan.py`. JSON is the source of truth. A rendered blueprint is
derived from the same data and must not add requirements that are absent from
the JSON.

## Top-Level Fields

Required top-level fields:

- `schema_version`: must be `"0.5"`.
- `plan_id`: stable fixture or run identifier.
- `created_by`: must be `"keelplane"` for candidate plans.
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
- `execution_path`: mode, first slice, consumer, and optional multi-wave
  execution contract.

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
`Use <downgrade_target> instead of keelplane for this request.`

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

## Execution Path And Wave Model

Official UX centers on a gated run model:

- `slice`: one atomic worker task.
- `wave`: one gated group of one or more slices sharing evidence, budget, and
  fan-in rules.
- `run`: one or more waves, where each follow-on wave unlocks only after the
  prior wave receipt, verification, and gate evidence pass.

`execution_path.first_wave` is the preferred first runnable unit. Legacy
`execution_path.first_slice` remains required for compatibility with existing
consumers and must continue to validate.

## Legacy First Slice

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

## First Wave And Follow-On Waves

Plans may include `execution_path.first_wave` and `execution_path.waves` when a
consumer needs a bounded multi-wave handoff contract. `first_wave` is the
official model for new plans; `first_slice` is the backward-compatible alias.

`execution_path.first_wave` requires:

- `id`
- `concurrency_cap`: positive integer
- `slices`: non-empty list of slice objects
- `entry_gate`
- `exit_gate`
- `fan_in`

Each `first_wave.slices[]` item requires:

- `id`
- `instruction`
- `expected_output`
- `completion_check`
- `forbidden_actions`: non-empty list

`first_wave.slices[].inputs` is optional, but when present it must be a
non-empty list.

`execution_path.waves` is optional, but when present it must be a non-empty list
of wave records. Each wave requires:

- `id`
- `depends_on`: list of wave ids
- `concurrency_cap`: positive integer
- `slices`: non-empty list of slice ids
- `exit_gate`

Dependent waves must include `entry_gate`, and the entry gate must reference a
prior receipt, verified state, or exit-gate semantics. Dependencies may point to
`first_wave.id` or to another `waves[].id`. Wave ids must be unique across
`first_wave` and `waves`, dependencies must point to known wave ids, and
dependency cycles are rejected.
When `first_wave` is present, every `waves[]` entry is a follow-on wave and must
declare a non-empty `depends_on` path back to `first_wave` or a verified prior
wave.

Automatic progression to the next wave is allowed only when the previous wave
receipt is verified, required evidence exists, the verifier or refuter passed,
touched files are within scope, forbidden actions are absent, tests were not
weakened, expected command exit codes match, budgets remain within limits, no
network/deploy/publish/secret/payment/external-message action occurred, and no
human approval gate is required.

Automatic progression stops on missing evidence, test failure, forbidden file
touches, test weakening, dependency installation, network/deploy/publish access,
secret or environment access, budget excess, refuter rejection, an unsatisfied
next-wave entry gate, or a required human approval gate.
