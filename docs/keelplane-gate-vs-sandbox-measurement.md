# Measurement: keelplane gate vs `codex --sandbox`

**Date:** 2026-06-22
**Question:** Does keelplane's command-safety gate detect false-pass / false-stop
better than off-the-shelf `codex --sandbox`? (The decisive measurement the
philosophy review demanded *before* building the gate-precision redesign, PR #6.)

**Method:** `measurements/gate_vs_sandbox.py`. A hand-labeled corpus of 14 dev
commands, each tagged with a human ground truth (should-pass = safe & reversible,
should-stop = irreversible/unsafe). The **keelplane verdict is obtained by
actually running `assess_command_safety`** (it is deterministic — ground truth,
not a guess). The **codex verdict** is derived from `--sandbox workspace-write`'s
OS-enforced rules: network denied, out-of-tree writes blocked, tree-local
read/write allowed.

- false-pass = ground truth `stop` but gate returned `pass` (unsafe slipped through)
- false-stop = ground truth `pass` but gate returned `stop` (needless halt)

## Result

| Gate | correct | false-pass | false-stop | total errors |
|------|--------:|-----------:|-----------:|-------------:|
| keelplane command-safety | 6 | **2** | **6** | **8 / 14** |
| codex --sandbox (workspace-write) | 12 | 0 | **2** | **2 / 14** |

**`codex --sandbox` wins decisively (2 errors vs 8).** This confirms the
adversarial critics' prediction that the off-the-shelf stack already beats
keelplane's gate.

## Why keelplane loses

1. **false-stop (6):** `git status`, `pytest`, `git commit`, `git fetch`,
   `pip install`, and any non-allowlisted `python` script are all rejected as
   `ERR_DWM_COMMAND_UNSUPPORTED` / `ERR_DWM_COMMAND_SCRIPT_NOT_ALLOWLISTED`. The
   gate is an allowlist of *keelplane's own workflow scripts* — it blocks
   ordinary dev work by construction.

2. **false-pass (2):** risk is inferred by **substring** (`NETWORK_MARKERS`,
   `DELETE_MARKERS`, …). An allowlisted script with a crafted argument slips
   through: `--sink ftp_host:21/exfil` (no `http://` substring → no network risk)
   and `--target /etc/hosts` (out-of-tree write, no risk substring) both PASS.

3. The 5 "correct stops" (`git push --force`, `rm -rf`, `npm publish`, `curl|bash`,
   `dropdb`) are **not precision** — they are the same blanket "not a python
   scripts/*.py command → block everything" rule that produces the 6 false-stops.
   keelplane cannot tell a dangerous shell command from a safe one; it blocks both.

## Why codex --sandbox wins

OS-enforced isolation judges the **physical effect**, not the command string, so
substring evasion (cases 13–14) is caught automatically and safe tree-local work
runs. Its only 2 errors are false-stops on safe network reads (`git fetch`,
`pip install`) — a known trade-off closed by a domain allowlist (the
"+10-line allowlist" the critics named), not a design flaw.

## Honesty caveats

- **n=14, author-constructed.** Small, and I built it; not an independent corpus.
- **Partial definitional overlap:** "irreversible" in the ground truth and the
  codex rule both lean on network/out-of-tree — mildly favorable to codex. The
  keelplane failures, however, do not depend on that overlap: its false-stops are
  on plainly-safe local commands and its false-passes are on plainly-unsafe ones.
- **Frame fairness:** keelplane's command-safety gate was *not* designed as a
  general dev-command gate; it gates keelplane's own workflow commands. But the
  stated target domain is dev automation ("휴먼게이트 빼고 알아서 착착"), so
  judging it as a dev-automation gate is the relevant test — and it fails it.

## Decision

Per the philosophy ("judge by net benefit, not sunk cost"):

- **Do NOT build** the gate-precision redesign. Adopt `codex --sandbox` (+ a thin
  domain allowlist + pre-push hook + git diff) as the reversibility boundary.
- **PR #6 is already closed** (2026-06-22) — the closed PR is the GitHub record
  of the refuted design; this measurement is the recorded rationale.
- keelplane's durable wedge is **not** this gate. Revisit where its measured
  value actually is (research/design orchestration per direction-anneal, vs the
  dev domain the user named — unresolved tension to settle next).
