# V124 Agent Fabric controlled capture claim gate

Status: implemented source-only controlled capture corpus input for the public-claim gate.

V124 extends `depone agent-fabric-claim-gate` so the V123 controlled capture
corpus can move a source-ready adapter smoke report to
`ready-for-public-claim-review`. This is still review readiness only: the gate
does not approve public claims, execute commands, call live models, inspect MCP
runtime state, or upgrade trust.

## Command

```bash
python3 -m depone agent-fabric-claim-gate \
  --adapter-smoke agent-fabric-adapter-smoke.json \
  --controlled-capture-corpus controlled-capture-corpus.json \
  --out agent-fabric-claim-gate.json
```

The existing `--paired-evidence` path remains supported. `--controlled-capture-corpus`
is an additional source-only evidence path for corpus-level dogfood review.

## Controlled corpus contract

The controlled capture corpus input is a JSON object with:

- `decision`: `controlled-capture-corpus-ready` or
  `controlled-capture-corpus-ready-source-only`.
- `boundary.executes_commands`: `false`.
- `boundary.calls_live_models`: `false`.
- `boundary.approves_public_claim`: `false`.
- `boundary.trust_upgrade`: `false`.

If the corpus is not ready, executes commands, calls live models, approves public
claims, or upgrades trust, the claim gate returns
`blocked-controlled-capture-corpus-not-ready` with explicit blocker codes.

## Decisions

- `ready-for-public-claim-review`: adapter smoke is source-ready and the
  controlled capture corpus is source-ready, non-executing, non-approving, and
  non-upgrading.
- `blocked-controlled-capture-corpus-not-ready`: the corpus is missing readiness
  or violates source-only/public-claim boundaries.
- Existing V119/V120 decisions remain unchanged for missing evidence, blocked
  adapter smoke, and paired-evidence inputs.

## Verification

```bash
PYTHONPATH=. python3 tests/test_agent_fabric_claim_gate.py
python3 -m depone agent-fabric-claim-gate --self-test
python3 scripts/check_contract.py --tier changed
```
