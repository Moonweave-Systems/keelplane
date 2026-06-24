# V121 Decision: Agent Fabric Paired Evidence CLI

Decision: add a source-only CLI that produces the paired evidence report the
V120 claim gate already knows how to consume.

Rationale:

- V120 defined the claim gate behavior for paired evidence, but operators still
  needed a deterministic source-only producer for that input.
- Hash-binding both adapter smoke and dogfood evidence makes the review packet
  reproducible before any public claim review.
- The command keeps approval separate: producing paired evidence can make a
  claim ready for human review, not approved.

Boundary:

- no command execution;
- no live model calls;
- no installed harness detection;
- no MCP runtime introspection;
- no automatic public-claim approval;
- no trust upgrade.
