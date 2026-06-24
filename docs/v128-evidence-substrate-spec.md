# V128 Consensus Evidence Substrate Spec

Status: spec for the "next" milestone. Not yet implemented.
Date: 2026-06-24.

Parent direction: `docs/v125-direction-check-roadmap.md` (Section 6.3, "next").
Depends on: V126 (a real captured manifest exists) and V127 (decision/assurance
are honest).

## 1. Research and prior art

Depone's defensible moat is vendor-neutral, cross-harness, tamper-evident
evidence that survives in audit and procurement. The chosen substrate is already
the right one in prose — `keelplane-v105-final/docs/ecosystem-positioning.md` and
the V124 spec name OpenTelemetry GenAI semantic conventions, W3C Trace Context,
in-toto/DSSE/Sigstore/SLSA, and MCP — but the implementation emits a bespoke
`kind` + SHA-256 JSON format:

- `depone/agent_fabric/capture_bridge.py` produces an
  `agent-fabric-capture-manifest` with `source_fixture_hash`,
  `observer_capture_hash`, and SHA-256 content-addressing.
- No in-toto Statement / `predicateType`, no DSSE `payloadType` / envelope, no
  `gen_ai.*` attributes, and no Sigstore exist in the schemas.

The mid-2026 consensus (V125 Section 4): the de facto telemetry wire format is
OTel GenAI semconv plus OpenInference; the mature, regulator-accepted provenance
substrate is in-toto/ITE-6 Statements wrapped in DSSE envelopes, signable via
Sigstore and loggable to Rekor. Being the neutral evidence layer on top of these
standards is more defensible than reinventing the envelope, and it makes Depone
evidence ingestible from any harness's traces and acceptable to supply-chain
tooling and regulated buyers.

## 2. Product position and non-goals

Position: emit Depone evidence in the consensus shapes so it is portable and
audit-grade, while staying stdlib-only. V128 changes the wire format of evidence,
not the trust model: the same A0-A3 assurance, the same hash binding, the same
"no agent seals evidence" rule, now expressed as in-toto/DSSE + OTel GenAI JSON.

Non-goals:

- No new dependency. Depone emits the standard JSON shapes itself; it does not
  vendor `in-toto`, `sigstore`, or an OTel SDK. (This honors the repo invariant:
  standard library only.)
- No cryptographic signing in V128. Emitting a DSSE envelope structure with an
  unsigned or hash-only payload is allowed; real Sigstore signing is the later A3
  item. The envelope must not claim a signature it does not have.
- No live OTel export / collector. V128 emits spans as static JSON conforming to
  the semantic conventions; it does not start a tracer or send telemetry.

## 3. Workflow architecture

```text
capture manifest (A1, hash-bound)            paired/dogfood evidence report
        |                                              |
        v                                              v
  in-toto/ITE-6 Statement                       OTel GenAI span set (static JSON)
  - subject: artifacts + their SHA-256          - gen_ai.operation.name
  - predicateType: depone evidence predicate    - invoke_agent / execute_tool spans
  - predicate: decision, assurance, claims,     - gen_ai.usage.* where observed
    gates, command receipts                     - W3C trace_id / span_id linkage
        |
        v
  DSSE envelope (payloadType = application/vnd.in-toto+json)
  - payload: base64 of the Statement
  - signatures: [] until Sigstore signing exists (V128 emits empty/unsigned)
        |
        v
  evidence bundle: { statement, dsse_envelope, otel_spans, assurance }
  - assurance still A0/A1 from V127; A2/A3 reserved for signing/custody
```

## 4. Execution model

1. Define a Depone in-toto predicate type (a stable URI string, for example
   `https://depone.dev/attestations/evidence/v1`) and a serializer that maps an
   existing capture manifest / verification report into an ITE-6 Statement:
   `_type`, `subject` (artifact name + `digest.sha256`), `predicateType`,
   `predicate` (decision, assurance, per-claim states from V127, gate results,
   command receipts).
2. Wrap the Statement in a DSSE envelope JSON: `payload` (base64 of the
   canonical Statement), `payloadType` = `application/vnd.in-toto+json`,
   `signatures: []`. Document explicitly that an empty signatures array means
   "unsigned content-addressed envelope," not a signature.
3. Add an OTel GenAI span serializer that maps a run's roles/tools/agents to the
   semantic conventions (`gen_ai.operation.name`, `invoke_agent`,
   `execute_tool`, and `gen_ai.usage.*` only where a value was actually
   observed), with W3C `trace_id` / `span_id` linkage. Unknown fields are
   omitted, never invented.
4. Keep the existing bespoke manifest as the internal source and emit the
   standard shapes as derived views, so nothing downstream breaks during
   migration; mark the standard shapes authoritative once consumers move.
5. Add an ingest path: accept an externally produced in-toto/DSSE statement or an
   OTel GenAI span set as a verifier input, so Depone can verify evidence
   captured by any harness, not only its own capture step.

## 5. Safety and verification gates

- The DSSE envelope must never present `signatures: []` as signed. Reports must
  state "unsigned, content-addressed" until V-later Sigstore signing lands.
- Assurance is unchanged by re-serialization: emitting an in-toto Statement does
  not raise A1 to A3. A3 remains reserved for a DSSE-wrapped Statement signed via
  Sigstore (Fulcio keyless + Rekor), specified later.
- Round-trip integrity: serializing a manifest to a Statement and back must
  preserve every hash and decision; a mismatch fails closed.
- Ingested external statements are untrusted until their digests are verified
  against present artifacts; unknown security-relevant fields do not satisfy
  policy (monotonic extension rule).

## 6. Evaluation fixtures

- a V126 captured A1 manifest serialized to an ITE-6 Statement whose `subject`
  digests match the manifest hashes;
- the Statement wrapped in a DSSE envelope with `signatures: []` and the report
  text asserting "unsigned";
- an OTel GenAI span set for a run that includes `invoke_agent` and
  `execute_tool` spans and omits `gen_ai.usage.*` when not observed;
- a tampered Statement (a subject digest altered) fails round-trip verification;
- an ingested external in-toto statement whose digest does not match a present
  artifact yields `inconclusive`, not `pass`.

## 7. Implementation plan

- Phase 1: in-toto/ITE-6 Statement serializer + DSSE envelope emitter
  (stdlib `json` + `base64` + `hashlib` only), with round-trip fixtures.
- Phase 2: OTel GenAI span serializer with semconv field mapping and
  observed-only usage fields.
- Phase 3: ingest path for externally produced statements/spans as verifier
  inputs.
- Phase 4: write `docs/v128-decision.md` recording the predicate type, the
  unsigned-envelope caveat, and the A3 signing item deferred to a later
  milestone.

Done means: Depone can emit and ingest its evidence as in-toto/ITE-6 Statements
in DSSE envelopes and as OTel GenAI spans, all stdlib-only and hash-faithful,
with signing explicitly deferred and never over-claimed.

Required verification:

- `python scripts/check_contract.py --tier changed`
- the new serializer/ingest self-tests
- `python scripts/check_release_text.py .` and `python scripts/check_whitespace.py .`
