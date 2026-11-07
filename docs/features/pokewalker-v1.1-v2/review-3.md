What this change does: The combined plan adds v1.1 progression, followed by v2 gyms and catch-only raids. I reviewed all 37 tickets against the requirements, research, and built v1 at `648bb378`, assuming one process serving a few hobby servers.

The specific fixes for all 17 Round 1 findings and all 8 Round 2 findings are present. None remains **REPEAT**. These are additional findings.

1. **MUST FIX — The background sweep uses the wrong clock.** [M7.4c.md:21](<docs/features/pokewalker-v1.1-v2/tickets/M7.4c.md:21>)

   **Problem:** The prescribed sweep passes `self.clock()`, but [WalkerBot’s clock defaults to `time.monotonic`](<pokewalker/bot/client.py:74>). Gameplay uses UTC epoch seconds through [Walker’s separate clock](<pokewalker/bot/walker.py:43>). Comparing these clocks prevents the sweep from recognizing ordinary persisted deadlines. M8.4 inherits the problem for raid cleanup.

   **Fix:** Use `self.walker.clock()` for gameplay settlement and expiry. Add a lifecycle test with deliberately different monotonic and UTC clocks.

   **If skipped:** Quiet servers do not automatically return defenders or clear expired raid participation.

2. **MUST FIX — The ticket removes valid ordinary evolution branches.** [M6.1a.md:21](<docs/features/pokewalker-v1.1-v2/tickets/M6.1a.md:21>)

   **Problem:** The ticket drops a region-null recipe whenever the same source has a region-specific recipe. Unlike [PLAN Q1](<docs/features/pokewalker-v1.1-v2/PLAN.md:151>), it does not restrict that rule to regional sources. The pinned CSV has ordinary Pikachu→Raichu row 17 and Pikachu→Alolan Raichu row 517; following the ticket deletes the ordinary branch. Exeggcute, Cubone and Koffing have the same issue.

   **Fix:** Match Q1 precisely: suppress inappropriate wildcard routes for regional sources, while retaining ordinary sources’ selectable regional and ordinary targets. Add a committed-data test proving Pikachu can choose both Raichu forms.

   **If skipped:** Valid evolutions disappear despite D40’s condition stripping and the [documented regional alternatives](<docs/research/data-visuals/pokeapi-forms.md:328>).

3. **MUST FIX — Player recall lacks a holder check at confirmation.** [M7.5a.md:29](<docs/features/pokewalker-v1.1-v2/tickets/M7.5a.md:29>)

   **Problem:** The ticket specifies guild validation and shows Recall only for the holder, but confirmation calls `end_deployment` without requiring that the current deployment still belongs to the session profile. A player can open Recall, lose the gym to another player, then confirm the old panel. The [existing router](<pokewalker/bot/walker.py:126>) validates the session owner and revision; another player’s battle does not invalidate that session.

   **Fix:** Save the previewed deployment ID and, inside confirmation, require that exact active deployment and its holder to match the session profile. Test replacement by another holder before confirmation.

   **If skipped:** An ordinary player can recall someone else’s defender through a stale confirmation.

4. **SHOULD FIX — Returned deployments have no explicit payout cutoff or replay test.** [M7.4b.md:16](<docs/features/pokewalker-v1.1-v2/tickets/M7.4b.md:16>)

   **Problem:** The specified payout formula stops at `ends_at`, ignoring `ended_at`. A deployment recalled after one hour still calculates three payable hours when passed to `pay_hours` at hour three. Receipts prevent paying the same hour twice; they do not prevent paying newly calculated hours after return. Neither lifecycle ticket explicitly makes repeated ending a no-op.

   **Fix:** Freeze eligibility at the actual return time, make already-ended deployments immutable, and add tests for a late reward request and repeated ending. Include exclusion so forfeited hours cannot later be recovered.

   **If skipped:** A stale or repeated lifecycle call can award income for time the Pokémon no longer held the gym.

5. **SHOULD FIX — The deployment guard changes successful receipt replay.** [M7.7b.md:15](<docs/features/pokewalker-v1.1-v2/tickets/M7.7b.md:15>)

   **Problem:** The ticket explicitly places the deployed check before receipt lookup. If a power-up commits, the Pokémon is subsequently deployed, and the original operation is replayed, it returns `stale` instead of its saved success. That contradicts the [existing receipt contract](<contracts/persisted-state.md:284>) and the ordering in [powerup.py:52](<pokewalker/services/powerup.py:52>).

   **Fix:** Keep ownership and exclusion checks first, return an authorized existing receipt next, then reject deployment before any new mutation. Test power-up → deploy → replay, asserting the original result and no additional spend.

   **If skipped:** Retry behavior changes according to later assignment state, even though the original operation succeeded.

6. **SHOULD FIX — The mini content fixture cannot satisfy the new loader.** [M6.1b.md:30](<docs/features/pokewalker-v1.1-v2/tickets/M6.1b.md:30>)

   **Problem:** The ticket mentions mini source rows for a branch target, but the existing [pokemon_evolution.csv](<tests/fixtures/content_mini/source/pokemon_evolution.csv:1>) contains only `id,evolved_species_id` and no recipes. It lacks the loader’s required columns and the existing fixture family’s 1→2→3 edges. Reusing `_read` with the proposed columns reproduced a missing-columns error.

   **Fix:** Explicitly assign the complete mini evolution header, its existing family edges, the branch fixture, and updated source hashes to this row. Preserve the [committed-mini rebuild test](<tests/test_content_emit.py:157>).

   **If skipped:** Wiring the loader breaks the required miniature rebuild before the new branch assertions can run.

7. **SHOULD FIX — The `apply_finds` signature change misses a test caller.** [M6.4a.md:24](<docs/features/pokewalker-v1.1-v2/tickets/M6.4a.md:24>)

   **Problem:** The ticket adds a required `content` argument and updates `stepping.py`, but [test_finds.py:35](<tests/test_finds.py:35>) calls the service directly through its shared helper. This test file is absent from the row’s assigned edits, although its suite is required verification.

   **Fix:** Assign the helper’s update to M6.4a and pass `self.content`. Keep its existing behavioral assertions.

   **If skipped:** Multiple find regression tests fail with a missing-argument error.

Verdict: fix these before implementation. All tickets fit within 4 KiB; the largest is 4,053 bytes. Declared production scopes fit the two-file limit; actual 300-line compliance remains unproven until implementation.

Not checked: full runtime suites or live Discord behavior. Verification used source inspection and read-only/in-memory probes; no files were edited or committed.

MUST=3 SHOULD=4 NIT=0
