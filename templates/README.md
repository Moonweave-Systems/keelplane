# Keelplane Workflow Templates

Validated, parameterized Workflow-tool scripts for patterns Keelplane has proven
worth reusing. They exist to remove the blueprint -> hand-coded-JS step: instead
of writing a fresh Workflow script (and risking parse errors) every time a design
calls for a known pattern, run the template and supply `args`.

These run on the Claude Code `Workflow` tool, which is Claude-Code-only. A Codex
execution path for the same patterns is a separate, deferred work item.

## `research-orchestration.workflow.mjs`

The proven research/design pattern: **Scope -> fan-out research -> barrier
synthesis -> adversarial-verify-against-source -> compose doc.** Use it for
multi-angle research or design questions where claims must be checked against
real source/data before they enter the document.

Lineage: distilled from the figure-agent "Illustrator Hand" dogfood, where the
against-source verifiers falsified four claims the brief called "verified" plus a
blind spot a single pass had accepted. The against-source verify step is the
high-value part — see `references/workflow-patterns.md` -> "Adversarial Verify
(Against Source)".

### Run it

```
Workflow({
  scriptPath: "<this-dir>/research-orchestration.workflow.mjs",
  args: {
    question: "the research/design question",          // REQUIRED (string)
    sources:  ["path/to/source.py", "docs/spec.md"],   // REQUIRED ground truth to verify against
    angles:   [{ key: "perf", prompt: "..." }],        // OPTIONAL; derived from `question` if omitted
                                                        //  (a bare string is accepted and auto-keyed)
    outPath:  "where/to/write/design-doc.md",          // OPTIONAL; the doc is also returned
    docKind:  "design document",                       // OPTIONAL label for the final artifact
    verifyBatchSize: 8                                 // OPTIONAL; claims per verifier (default 8)
  }
})

`args` may be passed as a real JSON value or a JSON string — the template parses
either.
```

Returns `{ doc, confirmed, refuted, unverified, claimCount, angles }`. The script
stays pure (no file write) so it is resumable/cacheable — the caller writes `doc`
to `outPath`.

### Contract notes

- `sources` is required for the verify phase to do real work. With no sources,
  verifiers correctly return everything as `unverified` rather than rubber-stamp.
- The workflow subagent must have read access to `sources` (Read/Grep for local
  files, WebFetch for urls).
- The single barrier (synthesis) is justified: it needs the complete finding set
  to de-duplicate claims across angles.
- Verify batches claims (`verifyBatchSize`, default 8): each verifier reads the
  sources once and judges its batch, instead of one agent per claim. A live audit
  of 83 claims ran ~20 agents batched vs. ~92 unbatched. A failed batch is retried
  once; any claim still left without a verdict is returned as `uncovered` and the
  composed doc discloses it -- never silently treated as confirmed.

### Validation

Syntax + phase-alignment checked with `/tmp/keelplane_wf_validate.cjs` (mimics how
the Workflow tool evaluates the script: meta export + body in an async context, so
top-level `await`/`return` are legal). `node --check` alone will falsely reject the
top-level `return` — that is expected, not a bug.
