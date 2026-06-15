# DWM V12 To V20 Final Roadmap

Status: planning specs; not implemented.

Date: 2026-06-16

## Product Thesis

DWM should become an independent large-task automation system, not only a
policy layer that depends on OMX. The product should keep the current DWM Core
as the source of truth while adding a DWM Runner and product shell in controlled
slices.

The intended stack is:

```text
DWM Product Shell
-> DWM Core
-> DWM Runner
-> Codex CLI workers
-> evidence, review, gates, resume
```

OMX remains optional prior art or an adapter target. It must not become a
required dependency for the core DWM workflow contract.

## Version Roadmap

| Version | Name | Layer | Goal |
| --- | --- | --- | --- |
| V12 | Adapter Command Planner | Core/Product CLI | Generate exact next adapter commands without executing them. |
| V13 | DWM Runner MVP | Runner | Execute one approved packet through Codex CLI with evidence capture. |
| V14 | Session And Worktree Runtime | Runner | Add durable sessions, worktree isolation, logs, and resume. |
| V15 | Multi-Worker Fanout | Runner | Run bounded parallel Codex workers with deterministic fan-in. |
| V16 | Runtime Review And Repair | Core/Runner | Add runner-backed review, repair, and retry loops. |
| V17 | Dashboard And Approval UI | Product Shell | Provide local UI for runs, evidence, human gates, and next actions. |
| V18 | Plugin And Install Packaging | Product Shell | Package DWM as an installable CLI/plugin with stable contracts. |
| V19 | Adapter Ecosystem | Integration | Support optional Codex, OMX, Claude, shell, and local fixture adapters. |
| V20 | 1.0 Release Hardening | Release | Freeze compatibility, migration, security, and acceptance gates. |

## Architecture Boundary

DWM Core owns:

- workflow plans,
- compiled packets,
- hash ledgers,
- gates,
- reviews,
- ingestion,
- next-action decisions,
- release contracts.

DWM Runner owns:

- process launch,
- Codex CLI invocation,
- session IDs,
- worktree creation and cleanup proposals,
- stdout/stderr/transcript capture,
- timeouts,
- retry execution,
- runner-local logs.

DWM Product Shell owns:

- human-facing CLI,
- plugin packaging,
- dashboard/HUD,
- approval queue,
- evidence browser,
- install and migration docs.

## Non-Goals

- Do not replace Codex itself.
- Do not make OMX a required dependency.
- Do not hide execution state in opaque logs.
- Do not execute risky actions without DWM Core gates.
- Do not treat model output as proof without artifacts and verification.

## Completion Target

DWM is 1.0-ready when a user can run a broad objective through plan, packet,
runner execution, evidence capture, review, repair, fanout, human approval,
resume, and final release verification without relying on OMX as the required
orchestrator.
