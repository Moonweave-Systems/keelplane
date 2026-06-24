# V109 Agent Fabric Capture Bridge Spec

V109 connects V108 reference adapter fixture output to a Depone-facing capture
manifest without adding live execution.

## Boundary

The capture bridge is deterministic and passive:

- it does not call live models;
- it does not execute artifact-provided commands;
- it does not treat agent self-report as observed evidence;
- it does not create approvals, seals, or final decisions.

Agent self-report alone remains `A0-claims-only`. A manifest reaches
`A1-local-observed` only when a Depone observer supplies local observations for
all required capture fields.

## Manifest kind

A V109 manifest has kind `agent-fabric-capture-manifest`.

Required top-level fields:

- `schema_version`;
- `kind`;
- `source_fixture_hash`;
- `fixture`;
- `assurance`;
- `decision`;
- `allowed_touched_files`;
- `observer_capture`;
- `observer_capture_hash`;
- `required_observer_fields`.

## Assurance labels

- `A0-claims-only`: valid fixture plus no observer capture. Decision is
  `claims-only`.
- `A1-local-observed`: observer capture exists, is hash-bound, refers to the
  current fixture hash, contains required observation fields, and touches only
  explicitly allowed files. Decision is `observed-local-capture`.

## Fail-closed cases

Validation rejects:

1. tampered fixture hashes;
2. tampered observer capture hashes;
3. stale observer capture source fixture hashes;
4. missing observer capture fields;
5. unexpected touched files;
6. unexpected diff files;
7. missing command receipts for A1.

## Verification

```bash
python3 tests/test_agent_fabric_capture_bridge.py
python3 -c 'from depone.agent_fabric.capture_bridge import _self_test; _self_test()'
python3 -m depone validate-contracts --file depone/fixtures/agent_fabric/capture_manifest_shell.json
python3 -m depone validate-contracts --all
```
