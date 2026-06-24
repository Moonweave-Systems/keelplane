# V123 Agent Fabric controlled capture corpus

Status: implemented source-only controlled capture corpus coverage.

V123 extends `depone agent-fabric-dogfood-evidence` from a single observed
capture manifest to a repeatable source-only corpus summary. Operators may pass
`--capture-manifest` more than once to validate multiple shipped controlled
captures and produce an `agent-fabric-controlled-capture-corpus` report.

Example:

```bash
python3 -m depone agent-fabric-dogfood-evidence \
  --capture-manifest depone/fixtures/agent_fabric/capture_manifest_shell.json \
  --capture-manifest depone/fixtures/agent_fabric/capture_manifest_docs_source_only.json \
  --out controlled-capture-corpus.json
```

The corpus report is ready only when:

- at least two capture manifests are supplied;
- each capture manifest independently produces
  `dogfood-evidence-ready-source-only`;
- the supplied manifests are distinct by canonical source hash.

The V123 fixture `capture_manifest_docs_source_only.json` is a second
source-only observed capture shape for documentation review coverage. It does
not execute commands, call live models, inspect MCP runtime, approve public
claims, or upgrade trust. Its underlying adapter self-report remains
`A0-claims-only`; only the hash-bound Depone observer capture can make the
manifest `A1-local-observed`.

Ready output includes:

- `kind`: `agent-fabric-controlled-capture-corpus`;
- `decision`: `controlled-capture-corpus-ready`;
- `capture_count`, `ready_count`, and `blocked_count`;
- ordered `entries` with each manifest decision, assurance, test status, and
  canonical source hash;
- `source_hashes.capture_manifests` in input order;
- `boundary` flags proving source-only behavior.

Blocking decisions use `blocked-insufficient-capture-corpus` with nested blocker
codes such as `ERR_CONTROLLED_CAPTURE_CORPUS_TOO_SMALL`,
`ERR_CONTROLLED_CAPTURE_CORPUS_DUPLICATE`, or
`ERR_CONTROLLED_CAPTURE_NOT_READY`.

Verification:

```bash
PYTHONPATH=. python3 tests/test_agent_fabric_dogfood_evidence.py
PYTHONPATH=. python3 -m depone agent-fabric-dogfood-evidence --self-test
```
