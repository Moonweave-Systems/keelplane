# Keelplane Threat Model v1

Status: Proposed
Date: 2026-06-23

## 1. Security objective

Prevent consumers from treating weak, stale, contradictory, or tampered
evidence as strong proof that an agent workflow satisfied policy.

Keelplane does not promise defect-free software or authentic provider identity
unless trusted evidence establishes the specific claim.

## 2. Protected assets

- plan/run-contract integrity;
- repository before/after state;
- command outcomes/logs;
- approval decisions;
- handoff artifacts;
- review input and findings;
- manifest/ledger/seal;
- secrets/private code;
- correctness of decision/assurance labels;
- reproducibility of the run.

## 3. Actors

- **Human operator:** controls local workflow, may make mistakes.
- **Producer agent:** untrusted for self-certification; can hallucinate, omit,
  overwrite, or follow prompt injection.
- **Native harness:** trusted only according to observed/attested capability.
- **Local collector:** trusted for A1 under local-machine assumptions.
- **Isolated runner:** trusted for A2 when it owns process/workspace/log custody.
- **External attestor:** CI/signer trusted by configured A3 policy.
- **Repository/external inputs:** untrusted and potentially adversarial.

## 4. Trust boundaries

```text
Untrusted producer workspace/staging
          |
          v
Observer/capture boundary
  recomputes paths, repository state, hashes, receipts
          |
          v
Verification boundary
  schema + policy + assurance evaluation
          |
          v
Human/CI consumer
```

The producer must not write the observer's seal or silently replace observed
artifacts after sealing.

## 5. Assurance levels

### A0 — Claims only

Agent output or imported transcript with no independent observation.

### A1 — Local observed

Keelplane collector independently reads repository/files. Same workstation and
user remain in the trust base; provider identity is not proven.

### A2 — Isolated runner observed

Runner controls process launch, attempt directory, timeout, stdout/stderr, and
workspace custody. Agent cannot write seal/ledger paths.

### A3 — Externally attested

Trusted CI/builder produces a verifiable signed attestation under policy.

## 6. Threats and controls

### T1. Agent fabricates a command receipt

- Agent-created receipts remain `self-reported`.
- A1/A2 policies require collector/runner observation.
- Receipt binds source snapshot, invocation ID, logs, and status.

### T2. Agent rewrites evidence and seal

- Separate producer-writable `staging/` from observer-owned paths.
- Collector writes ledger/manifest/seal last.
- Verification rejects extra/missing/changed sealed paths.
- Stronger tiers use signed attestations.

### T3. Approval replay

- Bind approval to plan hash, attempt, action digest, scope, expiry, and
  single-use consumption.
- Changed action requires a new approval.

### T4. Stale review accepted after code changed

- Review stores exact input/scope digest.
- Verifier compares current subject digest.

### T5. Same-agent review masquerades as independent

- Record producer/reviewer invocation IDs.
- Record fresh context, harness/model separation, rationale visibility,
  human/tool participation.
- Policies may require cross-harness or human review.

### T6. Path traversal, symlink, hardlink, special-file attack

- Relative normalized paths only.
- Reject absolute paths, `..`, control chars, ADS, symlink, device, socket, FIFO.
- Detect Unicode/case collisions.
- Compare metadata before/after streaming hash.

### T7. Evidence leaks secrets

- Digest/metadata by default; content capture is allowlisted.
- Never collect `.env`, key stores, cookies, private keys, shell history, or
  full environments by default.
- Record redaction-policy digest and retention class.

### T8. Huge files exhaust resources

- File count, size, total bytes, depth, and time limits.
- Streaming hashes and explicit truncation flags.
- No whole-file binary-to-hex expansion.

### T9. Passive verification executes malicious commands

- Passive verification never executes artifact-provided commands.
- Active execution is separate, explicit, allowlisted, and gated.

### T10. Manifest lies

- Manifest is an index, not authority.
- Adapter discovers files independently and recomputes hashes/origin.

### T11. Canonicalization ambiguity

- Artifact digest is over exact bytes.
- Optional semantic JSON digest uses a documented canonicalization such as
  RFC 8785 JCS.

### T12. Timestamps imply false ordering

- Sequence and parent hash establish local order.
- Wall-clock time records source/trust and is not an integrity primitive.

### T13. Cross-platform path ambiguity

- `/` manifest separators; original platform recorded.
- Portable mode rejects reserved names, ADS, normalization/case collisions.

### T14. Provider/subscription identity is falsely asserted

- Authentication mode is declared/imported unless a supported attestation
  proves it.
- Reports do not infer identity from model text or filenames.

### T15. Native feature drift breaks safety mapping

- Capability manifest and tested version range.
- Fail closed on unsupported critical semantics.
- Experimental features are opt-in.

## 7. Out of scope for A1

A1 does not resist malicious root/admin, compromised collector/kernel, provider
forgery, collusion of all local components, or undiscovered defects outside
claims.

## 8. Security fixtures

Required tests include:

- path traversal/symlink/special file;
- case/Unicode collision;
- extra/missing file after seal;
- ledger/manifest tamper;
- stale review;
- gate replay;
- oversized binary/log;
- duplicate-key/malformed JSON;
- unsupported schema major;
- self-report trying to satisfy A2;
- command timeout/signal/truncation;
- secret redaction.
