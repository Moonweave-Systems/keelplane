// Keelplane reusable template: research / design orchestration.
//
// Proven pattern (figure-agent "Illustrator Hand" dogfood, n=1 win):
//   Scope -> fan-out research -> BARRIER synthesis -> adversarial-verify-AGAINST-SOURCE -> compose doc
//
// Why this exists: turning a Keelplane blueprint into a runnable Workflow script
// was hand-coded each time and broke twice on JS parse errors. This template is
// syntax-validated and parameterized ENTIRELY through `args` -- you should not
// need to edit the JS. Run it with:
//
//   Workflow({ scriptPath: ".../templates/research-orchestration.workflow.mjs",
//              args: {
//                question: "the research/design question",          // REQUIRED
//                sources:  [ "path/to/source.py", "docs/spec.md" ], // REQUIRED ground truth to verify against
//                angles:   [ { key: "perf", prompt: "..." } ],      // OPTIONAL; derived from `question` if omitted
//                outPath:  "where/to/write/design-doc.md",          // OPTIONAL; doc is also returned
//                docKind:  "design document" } })                   // OPTIONAL label for the final artifact
//
// The script RETURNS { doc, confirmed, refuted, unverified, claimCount, angles }.
// The caller (you, the orchestrator) writes `doc` to `args.outPath` if set --
// keeping the workflow pure keeps it resumable and cacheable.
//
// Runtime requirement: the verify phase reads `args.sources` directly, so the
// workflow subagent must have read access to them (Read/Grep for local files,
// WebFetch for urls). Pass sources the agents can actually open.

export const meta = {
  name: 'research-orchestration',
  description: 'Fan-out research, synthesize, adversarially verify claims against source, compose a doc',
  whenToUse: 'Multi-angle research or design questions where claims must be checked against real source/data before they enter a doc',
  phases: [
    { title: 'Scope', detail: 'derive research angles from the question (skipped if angles supplied)' },
    { title: 'Research', detail: 'one worker per angle, each returns checkable claims' },
    { title: 'Synthesize', detail: 'barrier: merge all findings into a draft + flat claim list' },
    { title: 'Verify', detail: 'adversarial verify-against-source, one verifier per claim' },
    { title: 'Compose', detail: 'assemble the final doc from confirmed claims; flag refuted/unverified' },
  ],
}

// ---- input contract -------------------------------------------------------

// `args` may arrive as a parsed object OR, depending on how the caller passes it,
// as a JSON string. Normalize to an object so the contract checks are robust.
const input = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})

const question = input.question
const sources = input.sources || []
const docKind = input.docKind || 'design document'
// Claims per verifier. One verifier reads the sources once and judges a batch,
// instead of one agent (and one redundant source re-read) per claim.
const verifyBatchSize = Number.isInteger(input.verifyBatchSize) && input.verifyBatchSize > 0 ? input.verifyBatchSize : 8

// Accept angles as objects {key, prompt, why} or as bare strings; normalize so a
// string angle does not silently leak `undefined` into labels and prompts.
const suppliedAngles = (input.angles || []).map((a, i) =>
  typeof a === 'string' ? { key: `angle-${i + 1}`, prompt: a } : a,
)

if (!question || typeof question !== 'string') {
  throw new Error('research-orchestration: args.question (string) is required')
}
if (!Array.isArray(sources) || sources.length === 0) {
  // Against-source verification is the whole point. Without ground truth the
  // verify phase can only check plausibility, which is the weak form we reject.
  log('WARNING: args.sources is empty -- verifiers have no ground truth, so every claim will come back "unverified". Supply real files/data/artifacts to get the high-value against-source check.')
}

// ---- schemas (validated at the tool layer; agents retry on mismatch) ------

const ANGLES_SCHEMA = {
  type: 'object',
  required: ['angles'],
  properties: {
    angles: {
      type: 'array',
      minItems: 1,
      items: {
        type: 'object',
        required: ['key', 'prompt'],
        properties: {
          key: { type: 'string', description: 'short kebab-case label' },
          prompt: { type: 'string', description: 'what this worker should investigate' },
          why: { type: 'string', description: 'why this angle matters to the question' },
        },
      },
    },
  },
}

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['angle', 'claims'],
  properties: {
    angle: { type: 'string' },
    claims: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'statement'],
        properties: {
          id: { type: 'string', description: 'stable id, unique within this angle, e.g. perf-1' },
          statement: { type: 'string', description: 'a single checkable factual claim' },
          support: { type: 'string', description: 'reasoning or evidence the worker has for it' },
          source_hint: { type: 'string', description: 'where this could be verified (file, dataset, url)' },
        },
      },
    },
    notes: { type: 'string', description: 'context that is not itself a checkable claim' },
  },
}

const DRAFT_SCHEMA = {
  type: 'object',
  required: ['sections', 'claims'],
  properties: {
    sections: {
      type: 'array',
      minItems: 1,
      items: {
        type: 'object',
        required: ['title', 'body'],
        properties: {
          title: { type: 'string' },
          body: { type: 'string', description: 'prose; reference claims by their id' },
        },
      },
    },
    claims: {
      type: 'array',
      description: 'flat, de-duplicated list of every checkable claim the doc relies on',
      items: {
        type: 'object',
        required: ['id', 'statement'],
        properties: {
          id: { type: 'string', description: 'stable id unique across the whole draft' },
          statement: { type: 'string' },
          source_hint: { type: 'string' },
          origin_angle: { type: 'string' },
        },
      },
    },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['claim_id', 'verdict', 'reason'],
  properties: {
    claim_id: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'unverified'] },
    evidence: {
      type: 'object',
      properties: {
        locator: { type: 'string', description: 'file:line, dataset key, or url actually read' },
        excerpt_or_value: { type: 'string', description: 'the exact text/value found at the locator' },
      },
    },
    reason: { type: 'string', description: 'why the ground truth does or does not support the claim' },
  },
}

const VERDICT_BATCH_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: { type: 'array', items: VERDICT_SCHEMA },
  },
}

// ---- prompts --------------------------------------------------------------

const scopePrompt = `You are scoping a research/design question into independent investigation angles.

QUESTION:
${question}

${sources.length ? `Ground-truth sources that exist to check claims against:\n${sources.map((s) => `- ${s}`).join('\n')}` : 'No ground-truth sources were supplied.'}

Decompose the question into 3-6 distinct, non-overlapping angles. Each angle is a
separate surface or perspective a worker can investigate without coordinating with
the others. Avoid angles that just restate the question. Return the angles only.`

const researchPrompt = (angle) => `You are one research worker in a fan-out. Investigate ONLY your angle.

OVERALL QUESTION:
${question}

YOUR ANGLE (${angle.key}):
${angle.prompt}
${angle.why ? `Why it matters: ${angle.why}` : ''}

${sources.length ? `Ground-truth sources available (read them when relevant):\n${sources.map((s) => `- ${s}`).join('\n')}` : ''}

Return discrete, CHECKABLE claims -- each a single factual statement another agent
could later confirm or refute against a source. Do not pad with generalities.
For every claim give a source_hint pointing at where it could be verified.
Do NOT label anything "verified" or "confirmed" -- that is a later phase's job.`

const synthPrompt = (findings) => `You are the synthesis barrier. You have ALL fan-out findings below.

OVERALL QUESTION:
${question}

FINDINGS (JSON):
${JSON.stringify(findings, null, 2)}

Produce a coherent draft ${docKind}: ordered sections that answer the question,
referencing claims by id. Then produce a flat, de-duplicated \`claims\` list of every
checkable claim the draft relies on (merge duplicate claims from different angles into
one id, keeping the clearest statement and a source_hint). Carry forward unresolved
tensions as open_questions. Do not invent claims that no worker reported.`

const verifyBatchPrompt = (claimsChunk) => `You are an INDEPENDENT adversarial verifier. Your job is to REFUTE these claims, not
rubber-stamp them. You did not produce them and owe them no benefit of the doubt.

Read the ground-truth sources ONCE, then judge EVERY claim below against them.

GROUND-TRUTH SOURCES you may read:
${sources.length ? sources.map((s) => `- ${s}`).join('\n') : '(none supplied)'}

CLAIMS (JSON):
${JSON.stringify(claimsChunk.map((c) => ({ id: c.id, statement: c.statement, source_hint: c.source_hint })), null, 2)}

Rules:
- Verify against GROUND TRUTH, not against the producer's reasoning. Open the actual
  source/data/artifact, read the relevant part, and cite it (file:line, key, or value).
- Any "verified"/"confirmed" wording attached to a claim is itself a claim to refute,
  not a fact.
- Default to "refuted" when the ground truth contradicts the claim, and "unverified"
  when no source lets you check it (including when no sources were supplied).
- Only return "confirmed" when you actually read a source whose content supports it,
  and you cite that exact locator and excerpt/value.
- Return EXACTLY ONE verdict per claim, each carrying the matching claim_id. Do not
  merge, skip, or invent claims.`

const composePrompt = (draft, ledger) => `You are composing the final ${docKind}. Use ONLY claims that survived verification.

OVERALL QUESTION:
${question}

DRAFT (sections + claims, JSON):
${JSON.stringify(draft, null, 2)}

VERIFICATION LEDGER (JSON):
${JSON.stringify(ledger, null, 2)}

Write the final document in Markdown:
- Build the argument on CONFIRMED claims (cite their evidence locator inline).
- REMOVE or rewrite any section that depended on a refuted claim; do not silently keep it.
- Add a short "Unverified / open" section listing (i) unverified claims, (ii) any
  UNCOVERED claims (ledger.uncovered -- no verdict because a verifier batch failed
  or skipped them; name their ids/statements, they were NOT checked), and (iii) open
  questions. Do not present uncovered claims as established.
- End with a "Verification summary" line: counts of confirmed / refuted / unverified / uncovered.
Return the Markdown document only -- no preamble.`

// ---- orchestration --------------------------------------------------------

phase('Scope')
const angles = suppliedAngles.length
  ? suppliedAngles
  : (await agent(scopePrompt, { schema: ANGLES_SCHEMA, label: 'scope', phase: 'Scope' })).angles
if (!angles || !angles.length) {
  throw new Error('research-orchestration: no angles to research (scoping returned none)')
}
log(`${angles.length} angle(s): ${angles.map((a) => a.key).join(', ')}`)

phase('Research')
const findings = (await parallel(
  angles.map((a) => () =>
    agent(researchPrompt(a), { schema: FINDINGS_SCHEMA, label: `research:${a.key}`, phase: 'Research' })),
)).filter(Boolean)
if (!findings.length) {
  throw new Error('research-orchestration: every research worker failed -- nothing to synthesize')
}

phase('Synthesize')
// Barrier is justified: synthesis needs the COMPLETE finding set to de-duplicate
// claims across angles and resolve cross-angle tensions.
const draft = await agent(synthPrompt(findings), { schema: DRAFT_SCHEMA, label: 'synthesize', phase: 'Synthesize' })
const claims = draft.claims || []
log(`draft has ${draft.sections.length} section(s) and ${claims.length} checkable claim(s)`)

phase('Verify')
// Batch claims so each verifier reads the sources once and judges several claims.
const chunk = (arr, size) => {
  const out = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}
const claimBatches = chunk(claims, verifyBatchSize)
const runBatch = (batch, i, suffix) =>
  agent(verifyBatchPrompt(batch), { schema: VERDICT_BATCH_SCHEMA, label: `verify:batch-${i + 1}${suffix}`, phase: 'Verify' })
const batchResults = await parallel(claimBatches.map((batch, i) => () => runBatch(batch, i, '')))
// Retry batches that failed (e.g. a transient API error) ONCE, so one blip does not
// drop a whole batch of claims unverified.
const failedIdx = batchResults.map((r, i) => (r ? -1 : i)).filter((i) => i >= 0)
if (failedIdx.length) {
  log(`retrying ${failedIdx.length} failed verify batch(es) once`)
  const retried = await parallel(failedIdx.map((i) => () => runBatch(claimBatches[i], i, '-retry')))
  failedIdx.forEach((origIdx, k) => {
    if (retried[k]) batchResults[origIdx] = retried[k]
  })
}
const droppedBatches = batchResults.filter((r) => !r).length
if (droppedBatches) {
  // A dropped batch loses its claims -- surface it, never treat an unverified claim
  // as confirmed by omission.
  log(`WARNING: ${droppedBatches}/${claimBatches.length} verify batch(es) still failed after retry -- their claims stay UNVERIFIED, not silently confirmed`)
}
const verdicts = batchResults.filter(Boolean).flatMap((r) => r.verdicts || [])

const confirmed = verdicts.filter((v) => v.verdict === 'confirmed')
const refuted = verdicts.filter((v) => v.verdict === 'refuted')
const unverified = verdicts.filter((v) => v.verdict === 'unverified')
// Claims with NO verdict at all (dropped batch, or a verifier that skipped them):
// a real coverage gap that must be disclosed downstream, not hidden.
const verdictIds = new Set(verdicts.map((v) => v.claim_id))
const uncovered = claims.filter((c) => !verdictIds.has(c.id))
log(`verify: ${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified, ${uncovered.length} uncovered (no verdict)`)

phase('Compose')
const doc = await agent(composePrompt(draft, { confirmed, refuted, unverified, uncovered }), {
  label: 'compose',
  phase: 'Compose',
})

return { doc, confirmed, refuted, unverified, uncovered, claimCount: claims.length, angles }
