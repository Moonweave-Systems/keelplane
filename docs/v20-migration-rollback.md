# V20 Migration And Rollback Guide

Status: 1.0 release-candidate policy.

## Migration Sources

- V11 operator guidance artifacts remain readable as product guidance.
- V12 adapter command artifacts can be regenerated from trusted V1 runs.
- V13-V19 generated outputs are evidence, not source truth.

## Migration Rules

1. Validate the source artifact owner sentinel before trusting generated output.
2. Recompute source hashes before writing any replacement artifact.
3. Write migrated output to a new owned directory; do not mutate the original.
4. Preserve the old artifact path and hash in the migration record.
5. Require an explicit human gate before overwriting user config or deleting
   worktrees.

## Rollback Rules

Rollback means restoring the previous artifact directory pointer or reinstalling
the previous repo-local launcher. It must not use force push, hard reset,
recursive delete, production deploy, secret access, or dependency installation.

If migration compatibility is unknown, stop with a structured blocked status and
leave source artifacts unchanged.
