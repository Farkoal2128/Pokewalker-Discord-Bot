What this change does: The amendment adds research sending to caught results, replaces full-storage refusal with a forced Send/Upgrade choice, removes Home’s Claim button, and adds bulk channel configuration. I reviewed the seven tickets against HEAD `a08f34903fadda9ea3fc1e5df93f0849d3e4b491`, assuming one database writer and multiple concurrent Discord sessions.

**Must fix:**

1. **The lazy fallback does not satisfy the confirmed 15-minute deadline** ([PLAN-insert.md:126](<scratchpad>/amend2/PLAN-insert.md:126); [M6.8k.md:16](<scratchpad>/amend2/tickets/M6.8k.md:16)).
   - **What this is:** Fallback runs only on a later valid click, `/walker`, or `/raid`.
   - **Problem:** A player who leaves after catching keeps the Pokémon indefinitely. The original session expires 900 seconds after opening, and the router rejects expired sessions before reaching fallback ([walker.py:132](<pokewalker/bot/walker.py:132>)); even clicking the abandoned choice after its deadline cannot resolve it.
   - **Fix:** Schedule persisted overdue choices through the existing startup/periodic sweep ([client.py:148](<pokewalker/bot/client.py:148>)), retaining the UID-based receipt and atomic acknowledgment. Specify sweep timing and restart catch-up, name a no-interaction deadline test, and split the added production scope into bounded rows.
   - **If we skip it:** “15-minute fallback” actually means “on a future valid interaction, possibly never.” Lazy resolution would require an explicit change to the owner’s timing requirement.

2. **The permission recheck still uses stale member-role membership** ([M6.8p.md:23](<scratchpad>/amend2/tickets/M6.8p.md:23)).
   - **What this is:** The batch now calls `check_actor` inside its writer job, addressing the missing call from round 1.
   - **Problem:** `check_actor` rereads `interaction.user.guild_permissions` ([admin_channels.py:117](<pokewalker/bot/admin_channels.py:117>)). Installed discord.py constructs a separate interaction Member with captured role IDs ([interactions.py:288](<.venv/Lib/site-packages/discord/interactions.py:288>), [member.py:323](<.venv/Lib/site-packages/discord/member.py:323>)). Removing that member’s Manage Server role while queued does not update those IDs; the proposed fake-boolean test hides this.
   - **Fix:** Specify a current member-role authorization check at mutation admission, with lookup failures refusing the batch. Test removal of the member’s role while the original interaction remains unchanged; rereading the same interaction object is insufficient.
   - **If we skip it:** A former administrator can still enable channels after losing permission. Round-1 finding 9 remains open.

The round-1 disposition audit is:

| Round-1 finding | Round-2 result |
|---|---|
| 1. Wrong Pokémon selected | Fixed on paper: `overflow_uid` identifies the crossing catch; M6.8m names the A-at-limit/B-over-limit regression. |
| 2. Lock bypasses | Fixed: M6.8l guards unrelated registered actions across valid sessions and checks `/raid` before joining. |
| 3. New review opens bulk picker | Fixed: M6.8j preserves `caught` and rebuilds that Pokémon’s single review. |
| 4. Fresh recovery loses selection | Fixed: M6.8k explicitly persists the choice selection and tests both buttons. |
| 5. Warning precedes terminal/stale/expiry handling | Fixed: M6.8m uses the service refusal after those checks; raid Back and Master Ball cases are named. |
| 6. Recovery omits Send | Fixed: the button belongs to `render_terminal`; caller coverage and existing label assertions are addressed. |
| 7. Broken intermediate rows | Fixed in the proposed sequence: record → lock → activate overflow → remove obsolete handlers. |
| 8. Contradictory active requirements | Fixed: replacements cover Q4, Q16, contracts, fallback receipt and final smoke criteria. |
| 9. Missing authorization recheck | **Still open:** the call exists, but its member-role data can be stale; finding 2 above. |
| 10. Blanket test deletion | Fixed: retained Storage/Expand coverage and mixed authorization tests are explicitly preserved. |

I found no additional receipt or transaction defect in the proposed fallback: the synthetic single selection fits `research.send`, the stable UID receipt is owner-bearing, and send plus acknowledgment remain within the writer transaction. Raid refusal paths return normally, so continuing `/raid` after fallback does not inherently roll back the send.

All ticket sizes pass: **4,086 / 4,085 / 3,585 / 4,077 / 2,562 / 2,160 / 3,910 bytes** for j–p. Declared production scopes are **2 / 2 / 2 / 2 / 2 / 1 / 1 files**. Named tests and inherited RED requirements are present; the 300-production-line limit remains an implementation check. Relevant committed files match the draft’s `6f7d5e6` baseline.

**Verdict: fix 1 and 2 first.**

Not checked: executable tests, live Discord behavior or actual implementation line counts; this was paper-only, and nothing changed.
MUST=2 SHOULD=0 NIT=0
