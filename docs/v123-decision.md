# V123 decision

Decision: keep the Agent Fabric controlled capture corpus as a source-only
coverage expansion.

Rationale:

- V122 could produce dogfood evidence from one observed shell capture manifest.
- V123 adds a second docs/source-only observed capture fixture and a corpus
  summary path over repeated `--capture-manifest` inputs.
- The corpus blocks duplicate manifests and preserves nested per-capture blocker
  evidence instead of hiding invalid or failed captures.
- This remains review evidence only: it does not execute commands, call live
  models, approve public claims, or upgrade trust.

Verification:

- `PYTHONPATH=. python3 tests/test_agent_fabric_dogfood_evidence.py`
- `PYTHONPATH=. python3 -m depone agent-fabric-dogfood-evidence --self-test`
