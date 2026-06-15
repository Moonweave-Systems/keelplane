# V18 Plugin And Install Packaging Spec

Status: planned; not implemented.

## Research And Prior Art

DWM should become easy to install without losing repo-local reproducibility.
Claude plugins, Codex skills, and local CLIs provide different packaging
surfaces, but DWM Core should keep stable file contracts underneath them.

## Product Position And Non-Goals

V18 packages DWM as an installable product.

Non-goals:

- do not require global mutable state for core correctness,
- do not break existing `dynamic-workflow-designer` skill compatibility,
- do not force users onto OMX,
- do not hide release checks.

## Workflow Architecture

Packaging surfaces:

- local CLI entrypoint,
- Codex skill compatibility,
- optional Codex plugin,
- shell completion,
- upgrade/migration command.

## Execution Model

The installed product locates a DWM project root, validates versioned contracts,
and delegates to repo-local scripts or packaged modules with matching hashes.

## Safety And Verification Gates

Installers must not overwrite user config without backup. Upgrades must detect
schema incompatibility and provide migration instructions before modifying
artifacts.

## Evaluation Fixtures

- positive: install into a temp home,
- positive: validate an existing DWM repo,
- negative: incompatible schema blocks upgrade,
- negative: config overwrite requires approval.

## Release Plan

1. Decide package format.
2. Add install smoke in temp directories.
3. Add migration guide for V0.5-V17 artifacts.
4. Publish compatibility matrix.
