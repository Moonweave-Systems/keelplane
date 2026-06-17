# V68 Decision

Decision: keep.

Command used to verify README product-page cleanup:

```bash
python scripts/check_contract.py --self-test
```

The accepted cleanup moves command detail to `docs/command-reference.md`, moves
versioned implementation history to `docs/release-history.md`, embeds
`assets/dwm-dogfood-progress.svg`, and keeps benchmark claims separate from
process progress.

This decision does not claim upward benchmark performance, direct-agent
superiority, or generated `out/` directories as source truth.
