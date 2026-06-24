# Keelplane Evidence Protocol v1

Status: Proposed final draft
Date: 2026-06-23

## 1. Purpose

Normalize execution facts from Codex, Claude Code, and other harnesses without
pretending that every artifact has equal trust.

The protocol separates:

1. claim — what a producer says;
2. artifact — bytes produced or changed;
3. observation — a fact recorded by collector/runner custody;
4. attestation — a signed statement from a trusted identity;
5. policy result — whether declared requirements are satisfied.

## 2. Decision and assurance

Every report carries both:

```json
{"decision":"pass","assurance":"A1-local-observed"}
```

Decision: `pass`, `fail`, `inconclusive`.

Assurance:

- `A0-claims-only`;
- `A1-local-observed`;
- `A2-isolated-observed`;
- `A3-externally-attested`.

Higher assurance strengthens provenance only for covered subjects/predicates; it
does not broaden the claim.

## 3. Evidence origins

- `self-reported`: producer-created claim/result;
- `imported`: native artifact copied without independent process custody;
- `local-observed`: local Keelplane capture observed the bytes/state;
- `runner-observed`: bounded runner observed process/workspace;
- `externally-attested`: trusted signature/identity verified.

Adapters may downgrade unsupported origin claims but never upgrade them without
evidence.

## 4. Custody layout

```text
.keelplane/runs/<run-id>/<attempt-id>/
  plan/
    workflow.plan.json
    run-contract.json
  staging/                       # producer-writable, untrusted
    agent-results/
    handoffs/
    native-transcript-refs/
  observed/                      # collector/runner-owned
    repository/
      head-before.txt
      head-after.txt
      status-before.bin
      status-after.bin
      diff-worktree.patch
      diff-index.patch
      untracked-files.bin
      submodules.txt
    commands/
      <command-id>.json
      <command-id>.stdout
      <command-id>.stderr
    imports/
    events.jsonl
  reviews/
  gates/
  attestations/
  hashes/ledger.json
  evidence-manifest.json
  seal.json
```

`staging/` remains self-reported unless independently observed. In A1+ runs the
producer cannot author `observed/`, `hashes/`, manifest, or seal.

## 5. Identity

Required identifiers:

- `run_id`;
- immutable `attempt_id`;
- `invocation_id` and optional `parent_invocation_id`;
- `claim_id`, `artifact_id`, `command_id`, `review_id`, `gate_event_id`.

IDs are unique within a run. Optional W3C-compatible `trace_id`/`span_id` may
correlate systems but do not establish trust.

## 6. Path rules

Manifest paths are relative to the attempt root, use `/`, and must not contain
absolute roots, `.`, `..`, empty segments, NUL, control characters, or portable
Windows ADS/reserved-name syntax. They must resolve inside the root and must not
be symlinks or special files by default. The verifier rejects Unicode NFC or
case-fold collisions.

## 7. Run contract

`run-contract.json` binds a native execution suggestion to a plan. It records:

- plan exact-byte SHA-256 and schema version;
- target harness and capability snapshot;
- worker mapping and ownership;
- required claims/evidence;
- risk gates;
- observable budgets;
- compile report digest;
- pack/profile version.

It is an input, not proof that execution followed it.

## 8. Agent result

Agent results are self-reported unless a trusted runner captured them directly.

```json
{
  "schema_version": "1.0.0",
  "run_id": "auth-fix-001",
  "attempt_id": "attempt-01",
  "invocation_id": "uuid",
  "parent_invocation_id": null,
  "agent_name": "kp_explorer",
  "role": "explorer",
  "harness": "codex",
  "status": "completed",
  "source_snapshot_sha256": "sha256",
  "scope": {"read":["src/auth/**"],"write":[]},
  "summary": "Mapped the refresh path.",
  "claims": [],
  "artifact_refs": [],
  "command_refs": [],
  "blockers": [],
  "origin": "self-reported"
}
```

An agent result cannot set a Keelplane claim to supported.

## 9. Artifacts

An artifact record includes ID, media type, relative path, exact-byte digest,
size, producer invocation when known, origin, parent/source snapshot, redaction
status, and validation reference. Optional JSON semantic digest may use RFC
8785 JCS; exact-byte digest remains authoritative for file integrity.

## 10. Command receipt

```json
{
  "schema_version": "1.0.0",
  "command_id": "auth-race-test",
  "invocation_id": "uuid",
  "origin": "runner-observed",
  "argv": ["python","-m","pytest","tests/auth","-q"],
  "shell": false,
  "cwd": ".",
  "source_snapshot_sha256": "sha256",
  "started_at": "2026-06-23T01:10:00Z",
  "finished_at": "2026-06-23T01:10:09Z",
  "duration_ms": 9000,
  "status": "exited",
  "exit_code": 0,
  "signal": null,
  "timeout_ms": 120000,
  "stdout": {"path":"observed/commands/test.stdout","sha256":"...","size_bytes":1000,"truncated":false},
  "stderr": {"path":"observed/commands/test.stderr","sha256":"...","size_bytes":0,"truncated":false},
  "redaction_policy_sha256": "sha256"
}
```

Status: `exited`, `signaled`, `timed-out`, `blocked`, `not-run`,
`capture-error`.

Rules:

- nonzero exit is never rewritten as success;
- timeout/signal are not exit zero;
- shell execution records exact shell and text;
- stale source snapshot invalidates a required receipt;
- passive verification never reruns it.

## 11. Review record

```json
{
  "schema_version": "1.0.0",
  "review_id": "correctness-review-01",
  "reviewer_invocation_id": "uuid",
  "producer_invocation_ids": ["uuid"],
  "scope_digest": "sha256",
  "input_artifact_refs": ["artifact:git-diff"],
  "independence": {
    "fresh_context": true,
    "same_model_as_producer": "unknown",
    "same_harness_as_producer": false,
    "implementation_rationale_visible_before_findings": false,
    "human_reviewer": false
  },
  "verdict": "approved",
  "findings": [],
  "origin": "imported"
}
```

Verdict: `approved`, `changes-requested`, `refuted`, `inconclusive`.
A stale scope digest invalidates the review. Different invocation IDs alone do
not prove independence.

## 12. Gate event

Approvals are action-scoped:

```json
{
  "schema_version": "1.0.0",
  "gate_event_id": "uuid",
  "gate_id": "network",
  "run_id": "auth-fix-001",
  "attempt_id": "attempt-01",
  "plan_sha256": "sha256",
  "action_digest": "sha256",
  "scope": {"effect":"network","description":"Fetch official metadata"},
  "state": "approved",
  "single_use": true,
  "expires_at": null,
  "approved_by": {"kind":"human","id":"local-operator","authentication":"interactive-confirmation"},
  "origin": "local-observed"
}
```

States: `declared`, `requested`, `approved`, `denied`, `executed`, `expired`,
`not-applicable`. Approval does not imply execution; execution references the
same action digest and consumes one-time approval.

## 13. Event log

`observed/events.jsonl` may provide a hash-chained event sequence. Each line has
monotonic `seq`, event type, IDs, payload/digest, previous event digest, and
current digest over canonical bytes. A chain detects local deletion/reordering
but is not an identity signature.

## 14. Manifest

The manifest is an index and policy input, not an authority. It records run,
plan, subject snapshot, collector/assurance, harness declaration, invocations,
artifacts, commands, reviews, gates, budgets with measurement source,
redaction/retention, event log, ledger, attestations, warnings, and unsupported
capabilities. Verifier discovers files and recomputes digests independently.

## 15. Ledger and seal

Ledger records exact bytes, size, and media type for sealed paths. It excludes
itself, manifest, and seal. Manifest references ledger digest; seal references
both and a digest of sealed path names. Extra/missing paths invalidate the seal.
Files are streamed and metadata is compared before/after hashing.

```json
{
  "schema_version": "1.0.0",
  "run_id": "auth-fix-001",
  "attempt_id": "attempt-01",
  "manifest_sha256": "sha256",
  "ledger_sha256": "sha256",
  "sealed_paths_sha256": "sha256",
  "sealed_at": "2026-06-23T01:19:00Z",
  "sealer": {"name":"keelplane-capture","version":"0.1.0","origin":"local-observed"},
  "signature": null,
  "assurance": "A1-local-observed"
}
```

A local seal is only tamper-evident under local assumptions.

## 16. External attestation

A3 may wrap a Keelplane predicate in an in-toto Statement and DSSE/Sigstore
signature. Bind plan/source/output subjects, run type, parameters,
dependencies, runner identity, invocation, and report digest. Do not invent a
custom signature protocol.

## 17. Claim evaluation

Each required claim declares statement, falsifier, evidence selectors, minimum
origin/assurance, freshness/snapshot constraints, evaluator ID/version, and
hard/soft policy.

Result: `supported`, `refuted`, `not-evaluated`, `stale`,
`unsupported-evaluator`. Required non-supported/non-refuted states make the run
inconclusive unless policy explicitly says otherwise.

## 18. Budgets

Every budget has limit, observed value, unit, measurement source, origin, and
hard/advisory status. Do not hard-enforce token/cost when native harness does not
reliably expose it.

## 19. Privacy, retention, sharing

- digest/metadata by default;
- content/diff capture is allowlisted;
- exclude credentials, `.env`, cookies, key stores, private keys, shell history,
  and full environments;
- record redaction-policy digest and truncation;
- retention: `ephemeral`, `project`, `release`;
- external upload/sharing is opt-in.

## 20. Adapter contract

```python
class EvidenceAdapter:
    name: str
    version: str
    def probe(self, root): ...
    def discover(self, root): ...
    def normalize(self, discovered): ...
    def validate(self, context): ...
```

Adapters fail closed on unsupported major schema, never execute artifact
commands in passive mode, report downgraded origins, enforce limits/path policy,
and preserve unknown evidence without letting it satisfy policy.

## 21. Stable issue codes

```text
KP-SCHEMA-UNSUPPORTED
KP-PATH-UNSAFE
KP-PATH-COLLISION
KP-ARTIFACT-MISSING
KP-HASH-MISMATCH
KP-SEAL-INVALID
KP-ORIGIN-INSUFFICIENT
KP-CLAIM-NOT-EVALUATED
KP-CLAIM-REFUTED
KP-COMMAND-FAILED
KP-COMMAND-STALE
KP-REVIEW-MISSING
KP-REVIEW-STALE
KP-REVIEW-INDEPENDENCE
KP-GATE-MISSING
KP-GATE-DENIED
KP-GATE-REPLAY
KP-BUDGET-EXCEEDED
KP-REDACTION-UNKNOWN
KP-CAPABILITY-UNSUPPORTED
```

## 22. Legacy compatibility

Legacy verdicts and marker gates may be read during migration. Legacy evidence
cannot exceed A1, and marker-only approvals cannot satisfy action-bound
high-risk policies.
