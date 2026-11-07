What this change does: The draft records the accepted permission-check window and adds a fallback rollback test. It also shortens M6.8p and M6.8q to fit the ticket limit.

Looks good. Ship **as a paper amendment**. No new findings.

- **Round-3 SHOULD 1 is fixed:** [M6.8q:49](<scratchpad>/amend2/tickets/M6.8q.md:49) requires overflow clearing to fail after `send`, verifies rollback of state, Candy, receipt, ledger and pending record, then retries successfully once.
- **Round-3 MUST 1 is settled:** owner acceptance appears consistently in Q21, M6.8p and the round-3 disposition table.
- **Trims preserve required behavior:** contract edits, transaction boundaries, sweep timing, restart recovery, refusal/retry behavior and verification commands remain. The removed “every other row unchanged” wording retains meaningful coverage through M6.8m’s explicit regression proving the fallback sends B while leaving A owned.
- **All eight tickets fit 4,096 bytes:** M6.8p is **4,068**; M6.8q is **4,085**. Tickets j–o are unchanged from round 3.

Verified branch `feature/pokewalker-v1.1-v2`, HEAD `c48701b71ef8282dd2e6ba9a4e7b135c1073e6f5`, and a clean worktree. Compared the draft revisions and checked connected contracts, writer rollback, research sending and sweep tests. Relevant checked files have no drift from `a08f349`. Assumed the documented one-process, single-writer deployment serving a few hobby servers.

Not checked: executable implementation, tests or live Discord; this is paper review only. Nothing changed.

MUST=0 SHOULD=0 NIT=0
