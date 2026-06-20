# Keelplane Autonomous Loop — Live n=1 Record

The first end-to-end live run of the Keelplane Autonomous Loop driving real
`codex exec` across multiple phases, gated by loop-owned immutable verification.
The live runs are non-deterministic, so this tracked record preserves the
evidence that `out/` (gitignored) holds.

Scope: this proves the loop CONTROL is correct — it advances only on verified,
hash-bound evidence and stops honestly otherwise. It does NOT claim codex
reliability, nor any direct-agent superiority, autonomy, or benchmark result.

## Clean run — `verified-complete`

```bash
python scripts/keelplane_loop.py run \
  --manifest fixtures/keelplane-loop/live-manifest.json \
  --out out/keelplane-loop/live-1 \
  --mode installed-codex --i-approve-live-codex \
  --timeout-seconds 240 --max-wall-seconds 600 --max-calls 12
```

- `terminal_state`: `verified-complete`
- `verified_phase_count`: 2 (both phases autonomously verified, no human between)
- `mode`: `installed-codex`
- `evidence_chain_head`: `457965aaf60639cb0928d55f81fef075cdf359a49781f9ae3db5e513a4e713fc`
- `status_hash`: `2b1d83893cc4421322d909717cf0489f52a8b2990a76d8f9f4d5045de84d8853`
- phase checkpoint commits: `0e364766527a1ed49f9dfbebd12f88cad5fba3f0`, `bb2adf97a48faa49ec918696ad62d5adc02411eb`
- packet hashes: `0707f0035a63...`, `5aeb4a045e97...`
- Real codex evidence: `out/v2/keelplane-live-1-part1-0/attempts/0000/transcript.md`,
  `out/v2/keelplane-live-1-part2-0/attempts/0000/transcript.md`. The part2
  transcript states codex implemented `scripts/keelplane_run_summary.py` only and
  the loop-owned tests passed (`2 passed`); no test or other file was modified.
- Main repo tracked files unchanged; the worker built source inside an isolated
  worktree.

## Fault run — `failed` (the differentiator)

```bash
python scripts/keelplane_loop.py run \
  --manifest fixtures/keelplane-loop/live-fault-manifest.json \
  --out out/keelplane-loop/live-fault-1 \
  --mode installed-codex --i-approve-live-codex \
  --timeout-seconds 240 --max-wall-seconds 600 --max-calls 12
```

- `terminal_state`: `failed` (never `verified-complete`)
- `verified_phase_count`: 1 (part1 verified, then the fault phase could not pass)
- `evidence_chain_head`: `5abe64b3335c0d32345ae6b1bafc18ab70ae66802b1f68a92b1eabb369a0e470`
- `status_hash`: `d41458943267b91c9763bf7e552ae558b56d85cee7ff624ee7672bb4aa8fa08d`
- invalidator: `ERR_KEELPLANE_VERIFY_FAILED` — "declared checks did not pass"
- explanation: "a phase did not pass declared checks after the allowed repair"
- The fault phase ran codex twice (`out/v2/keelplane-live-fault-1-part2-unsatisfiable-0`
  and `-1` = initial attempt plus one repair), then stopped. Codex could not game
  the immutable test (loop restores it, plugin autoload disabled, new
  verification-affecting files fail the phase). Main repo tracked files unchanged.

## Why it matters

OMO-style harnesses optimize "finish fast." The Keelplane loop optimizes "if it
says verified, the declared checks really passed." The clean run shows it can
complete a multi-phase task autonomously; the fault run shows it refuses to claim
completion when a phase cannot be verified — the bounded, evidence-gated autonomy
that is the point of the tool.
