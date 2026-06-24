# V107 Decision

Decision: keep as the Agent Fabric contract/compiler slice.

Command used to verify this documentation-only PR:

```bash
python scripts/check_contract.py --tier changed
```

V107 records the final direction for a Depone-compatible agent system and now
includes the first deterministic contract/compiler slice. The accepted boundary
is:

- Depone Core remains deterministic and owns contracts, evidence, decisions,
  and assurance.
- Agent Fabric is a separate execution-plane layer for profile routing,
  role/toolbelt compilation, context policy, harness adapter lowering, and
  evidence handoff.
- Native harnesses such as Codex, Claude Code, OpenCode/OMO, shell, LangGraph,
  or Conductor remain responsible for actual execution.

Implemented in this slice:

- role, toolbelt, harness capability, profile, compile-report, invocation, and
  agent-result validators;
- `compile_agent_fabric(profile, harness_name, role_contracts)`;
- exact, approximated, and unsupported-critical tool mapping decisions;
- blocked reviewer write access, undeclared MCP tools, missing evidence
  obligations, and self-reported agent-result boundaries;
- no live model execution.

This decision intentionally does not claim:

- agent quality improvement;
- productivity improvement;
- direct-Codex, Claude Code, OpenCode, or OMO superiority;
- live model execution;
- hard per-agent tool filtering in any native harness;
- production readiness for the existing role pack.

The next implementation slice should be adapter-only and still deterministic:

1. add a reference adapter fixture for one local harness;
2. capture self-report, diff/touched-file summary, and test output as
   non-authoritative agent evidence;
3. keep hard tool-hiding claims behind capability evidence;
4. avoid public productivity or quality claims until paired dogfood evidence
   exists.

The current `agents/openai.yaml`, `packaging/dwm-roles.json`, V22 role pack
contract, V105 final profiles, and V105 agent-team spec are useful inputs, but
they are not yet the world-class Agent Fabric. V107 keeps the distinction
explicit so later work can build the Agent Fabric without weakening Depone's
evidence boundary.
