What this change does: The plan adds v1.1 progression features, then v2 gyms and catch-only raids, using the built v1 bot. I reviewed all 21 tickets against requirements, research, and code at `648bb378`, assuming one process serving a few hobby servers; the owner decisions and open decision gates remain intact.

**MUST FIX**

1. **Evolution targets are missing from the artifact.** [M6.1.md:20](<docs/features/pokewalker-v1.1-v2/tickets/M6.1.md:20>)

   **What this is:** Midnight/Dusk Lycanroc and Rapid Strike Urshifu must become selectable evolution targets. **Problem:** [graph.py:190](<content/build/graph.py:190>) excludes them entirely, while [storage.py:4](<pokewalker/services/storage.py:4>) resolves owned Pokémon only through existing identities. The ticket adds edges without defining resolvable target records.

   **Fix:** Include target records with stats, names and sprites, extend identification to resolve them, and keep them outside encounter pools. Test evolving to each excluded branch and reopening its details. **If skipped:** The selected branch either collapses to the default or produces a Pokémon that cannot be displayed.

2. **An evolution target does not uniquely identify its recipe.** [M6.3.md:22](<docs/features/pokewalker-v1.1-v2/tickets/M6.3.md:22>)

   **What this is:** Confirmation chooses an evolution using `to_identity_id`. **Problem:** Under Q2’s proposed sweets default, the pinned data contains 63 Alcremie records using seven different sweets. Q1 collapses their appearances to the same target, leaving multiple recipes with different item costs but the same target ID.

   **Fix:** Deduplicate identical normalized recipes and carry the selected recipe—not just its target—through preview and confirmation. Test a player holding only one of the alternative sweets. **If skipped:** Confirmation cannot reliably consume the item shown in the preview.

3. **The proposed selectors exceed Discord’s option limit.** [M6.4.md:30](<docs/features/pokewalker-v1.1-v2/tickets/M6.4.md:30>), [M7.6.md:28](<docs/features/pokewalker-v1.1-v2/tickets/M7.6.md:28>)

   **What this is:** Players select an evolution item to buy and Pokémon for three battle slots. **Problem:** The pinned default evolution methods reference 50 item IDs, and a collection can contain hundreds of Pokémon. Neither picker specifies paging; Discord permits at most 25 options per string select. [Discord component reference](https://docs.discord.com/developers/components/reference#string-select)

   **Fix:** Reuse the existing paged storage-selection pattern. Add acceptance cases that reach choices beyond the first page and assert every select stays within 25 options. **If skipped:** Normal collections or the proposed item catalog cannot fit in the requested screens.

4. **Gym income grants an unusable evolution-item placeholder.** [M7.4.md:29](<docs/features/pokewalker-v1.1-v2/tickets/M7.4.md:29>)

   **What this is:** Hourly gym rewards roll the gym table and call `items.grant`. **Problem:** [gym_income_table.json:67](<content/balance/gym_income_table.json:67>) contains `evolution_item`. M6.4 resolves that placeholder only in passive finds; [items.py:38](<pokewalker/services/items.py:38>) otherwise stores it literally.

   **Fix:** Share the concrete-item resolution between passive and gym rolls. Add a forced gym evolution-item roll that awards a usable named kind. **If skipped:** Players receive inventory that no evolution recipe consumes.

5. **Deleting a profile does not clear its identity from spawn history.** [M8.1.md:23](<docs/features/pokewalker-v1.1-v2/tickets/M8.1.md:23>)

   **What this is:** Spawn history stores `spawned_by_profile_id`. **Problem:** The schema declares plain nullable text, but [M8.4.md:24](<docs/features/pokewalker-v1.1-v2/tickets/M8.4.md:24>) assumes deletion clears it. Without a foreign key or deletion hook, that assumption is false.

   **Fix:** Use `REFERENCES profiles(profile_id) ON DELETE SET NULL`; test that deleting the spender clears attribution while preserving the committed spawn. **If skipped:** Deleted profile data remains, contrary to D28. Cascading deletion of the spawn would instead violate D60’s no-cancellation rule.

6. **The permission check can authorize spending against a different channel.** [M8.2.md:19](<docs/features/pokewalker-v1.1-v2/tickets/M8.2.md:19>)

   **What this is:** The handler checks announcement permission before submitting the spawn transaction. **Problem:** It passes only `permission_ok`. An admin can change the configured channel between that check and the transaction, and the spawn stores no checked channel ID.

   **Fix:** Pass the checked channel ID, verify it still matches inside the transaction, and retain that destination for announcement and restart recovery. Test a channel change between check and commit. **If skipped:** A non-refundable ticket can be consumed using permission evidence for the wrong destination.

**SHOULD FIX**

7. **The stale-defender check lacks a defined comparison value.** [M7.6.md:17](<docs/features/pokewalker-v1.1-v2/tickets/M7.6.md:17>)

   **What this is:** Start must reject a preview whose defender changed. **Problem:** The acceptance test requires this, but the service inputs and preparation flow never specify saving the preview’s deployment ID. Reading the current defender alone cannot detect replacement.

   **Fix:** Save the expected deployment ID in session selection and compare it before simulation. **If skipped:** A player can confirm one matchup and fight another, contrary to [battle-system.md:30](<docs/research/gyms/battle-system.md:30>).

8. **The type-chart acceptance rules contradict each other.** [M7.1.md:19](<docs/features/pokewalker-v1.1-v2/tickets/M7.1.md:19>)

   **What this is:** M7.1 checks imported type factors against battle rules. **Problem:** It requires “exactly” three factors, while [M6.1.md:27](<docs/features/pokewalker-v1.1-v2/tickets/M6.1.md:27>) correctly includes neutral effectiveness `1`, making four.

   **Fix:** Include neutral `1.0` in the expected set and retain a neutral-matchup test. **If skipped:** The specified checks cannot both pass without weakening one contract.

9. **Claim still counts World Legendary Tickets as ordinary bag space.** [M7.3.md:22](<docs/features/pokewalker-v1.1-v2/tickets/M7.3.md:22>)

   **What this is:** M7.3 makes rare-pocket classification data-driven. **Problem:** It does not update the ordinary-item sum in [milestones.py:153](<pokewalker/services/milestones.py:153>), which excludes only Master Balls and Shiny Lures. At 999/1000 ordinary units plus one ticket, Claim incorrectly sees a full bag.

   **Fix:** Reuse `items.bag_units` for ordinary claims. Add that exact mixed-inventory acceptance case. **If skipped:** Valid ordinary rewards remain stuck in the inbox.

10. **Raid confirmation Back buttons leave the raid.** [M8.3.md:26](<docs/features/pokewalker-v1.1-v2/tickets/M8.3.md:26>)

    **What this is:** Raids reuse the existing Master Ball and shiny-Run confirmations. **Problem:** Both Back buttons invoke `open_encounter` in [screens_catch.py:60](<pokewalker/bot/screens_catch.py:60>) and [:87](<pokewalker/bot/screens_catch.py:87>); M8.1 makes that handler skip raid encounters.

    **Fix:** Preserve the selected raid encounter when returning from confirmation. Test both Back buttons with and without an ordinary queued encounter. **If skipped:** Back opens another Pokémon or returns home.

11. **Reopening a completed raid renders it as catchable.** [M8.3.md:21](<docs/features/pokewalker-v1.1-v2/tickets/M8.3.md:21>)

    **What this is:** Repeated `/raid` returns the saved encounter. **Problem:** The command always calls `render_catch`, including after Catch or Run. [screens_catch.py:32](<pokewalker/bot/screens_catch.py:32>) does not dispatch terminal states itself.

    **Fix:** Render the saved terminal result for resolved encounters and explicitly handle participation whose encounter disappeared after deletion. Test command responses, not merely absence of a second encounter. **If skipped:** Players see active catch controls for completed encounters or an unexplained recovery refusal.

12. **The nonce fallback silently changes D60.** [M8.2.md:55](<docs/features/pokewalker-v1.1-v2/tickets/M8.2.md:55>)

    **What this is:** The ticket checks whether the pinned library supports `enforce_nonce`. **Problem:** If unsupported, it permits `nonce` alone, although [README.md:346](<docs/features/pokewalker-bot/README.md:346>) explicitly requires both.

    **Fix:** Leave the compatibility decision open until verified; if unsupported, rebrief the dependency or obtain an explicit requirement change. **If skipped:** Implementation can claim completion while knowingly omitting a required mechanism. The persisted `attempted` guard does not resolve that contract mismatch.

13. **The required privacy disclosure is not a completion prerequisite.** [M8.4.md:28](<docs/features/pokewalker-v1.1-v2/tickets/M8.4.md:28>)

    **What this is:** Raid participation survives profile deletion until spawn expiry. **Problem:** The current [privacy.md:7](<docs/features/pokewalker-bot/privacy.md:7>) does not disclose this exception. The ticket only reports suggested wording, and G-F2 does not require the owner’s update.

    **Fix:** Add the owner-controlled disclosure update as an explicit prerequisite to final completion. **If skipped:** The shipped privacy text contradicts the required retention behavior.

14. **M6.2 must update a file the plan forbids it to change.** [PLAN.md:97](<docs/features/pokewalker-v1.1-v2/PLAN.md:97>)

    **What this is:** Balance-table edits require regenerated manifest hashes. **Problem:** The plan permits artifact regeneration only in M6.1/M7.1, while [M6.2.md:38](<docs/features/pokewalker-v1.1-v2/tickets/M6.2.md:38>) requires rebuilding during M6.2. The integrity check at [test_content_integrity.py:65](<tests/test_content_integrity.py:65>) makes this necessary.

    **Fix:** Explicitly authorize M6.2’s generated manifest/artifact changes and correct “not affected.” **If skipped:** The implementer must violate either the ownership boundary or the acceptance checks.

15. **“Wiring” edits hide production files from row budgets.** [M6.3.md:37](<docs/features/pokewalker-v1.1-v2/tickets/M6.3.md:37>), [M7.7.md:27](<docs/features/pokewalker-v1.1-v2/tickets/M7.7.md:27>)

    **What this is:** Rows are supposed to touch at most two production files and change at most 300 production lines. **Problem:** Even excluding migrations and JSON, M6.1, M6.3–M6.5, M6.6c, M7.3–M7.5, M7.7, and M8.1–M8.3 exceed two Python files. M6.3 names four; M7.7 names five. The 300-line stop conditions also measure `gyms.py`, rather than the whole row.

    **Fix:** Count all production edits and split coherent service, UI, and integration slices before dispatch. Do not introduce abstractions merely to reduce file counts. **If skipped:** The declared review bounds do not describe the actual work.

16. **The parallel batch contains dependencies.** [PLAN.md:222](<docs/features/pokewalker-v1.1-v2/PLAN.md:222>)

    **What this is:** M7.1–M7.3 are allowed to run in parallel. **Problem:** M7.2 consumes M7.1’s battle rules; M7.3 derives the new ticket pocket from M7.1’s capacities. Disjoint files do not make these rows independent.

    **Fix:** Finish M7.1 first, then allow M7.2 and M7.3 to proceed together. **If skipped:** Their focused verification runs against missing inputs or requires unplanned coordination.

17. **The capacity acceptance case rejects the last valid slot.** [M6.6a.md:41](<docs/features/pokewalker-v1.1-v2/tickets/M6.6a.md:41>)

    **What this is:** One expansion raises storage from 250 to 300. **Problem:** The test description says the 300th catch is refused. The existing check at [catching.py:68](<pokewalker/services/catching.py:68>) correctly refuses when the collection is already full.

    **Fix:** Specify that a catch taking storage from 299 to 300 succeeds; the next attempt fails without spending items. **If skipped:** RED-first implementation can encode an off-by-one capacity bug.

Verdict: fix 1–6 first, then reconcile the remaining acceptance and execution gaps. All 21 tickets are within 4 KiB; the largest is 4,087 bytes.

Not checked: runtime tests, live Discord behavior, or installed-library nonce support. No files were edited or committed; implementation line counts remain estimates.

MUST=6 SHOULD=11 NIT=0
