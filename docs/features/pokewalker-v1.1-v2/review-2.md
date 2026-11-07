What this change does: The combined plan adds v1.1 progression, then v2 gyms and catch-only raids. I reviewed all 36 tickets against the requirements, research, and v1 code at `648bb378`, assuming one process serving a few hobby servers.

All 17 Round 1 findings are addressed; none remains **REPEAT**. The following are additional findings.

1. **MUST FIX — The prescribed Star Piece call crashes successful catches.** [M6.5b.md:14](<docs/features/pokewalker-v1.1-v2/tickets/M6.5b.md:14>)

   **Problem:** The ticket inserts `items.boost(...)`, but `throw` already assigns a list of balls and berries to `items` at [catching.py:79](<pokewalker/services/catching.py:79>). That local variable shadows an imported module.

   **Fix:** Import `boost` directly or alias the service module, and use that name in the prescribed call. **If skipped:** Successful catches raise an exception and roll back instead of awarding the Pokémon.

2. **MUST FIX — Evolution recipes and Pokémon use incompatible gender values.** [M6.1a.md:25](<docs/features/pokewalker-v1.1-v2/tickets/M6.1a.md:25>), [M6.3a.md:20](<docs/features/pokewalker-v1.1-v2/tickets/M6.3a.md:20>)

   **Problem:** The loader keeps numeric `gender_id` values, while `options` compares the edge’s gender directly with the Pokémon’s stored string. The database uses `female`, `male`, and `genderless` at [0001_core.sql:69](<pokewalker/db/migrations/0001_core.sql:69>); Combee’s pinned evolution row uses `1`.

   **Fix:** Explicitly normalize recipe genders to the existing strings. Test an emitted Combee recipe through the actual options service. **If skipped:** Female Combee and other gender-gated evolutions have no matching option.

3. **MUST FIX — Gym transactions lack an explicit server-boundary check.** [M7.4a.md:24](<docs/features/pokewalker-v1.1-v2/tickets/M7.4a.md:24>), [M7.6a.md:17](<docs/features/pokewalker-v1.1-v2/tickets/M7.6a.md:17>)

   **Problem:** Deploy and battle enumerate ownership and eligibility checks without requiring the selected gym to belong to the session’s server. The proposed separate gym/profile foreign keys also permit a server A profile to reference a server B gym, violating D10.

   **Fix:** Scope gym lookups and mutations by both gym ID and session guild ID. Add two-server tests proving foreign-guild deploy, battle, recall, and reward requests change nothing. **If skipped:** Implementing only the listed checks permits cross-server gym activity.

4. **SHOULD FIX — Capacity and route tickets omit conflicting v1 test updates.** [M6.6c.md:12](<docs/features/pokewalker-v1.1-v2/tickets/M6.6c.md:12>), [M6.7.md:29](<docs/features/pokewalker-v1.1-v2/tickets/M6.7.md:29>)

   **Problem:** Existing tests explicitly require table-controlled capacities and unrestricted routes: [test_conversion.py:71](<tests/test_conversion.py:71>), [test_storage.py:373](<tests/test_storage.py:373>), [test_milestones.py:173](<tests/test_milestones.py:173>), and [test_route.py:129](<tests/test_route.py:129>). M6.6c identifies a different milestone test for its sole update.

   **Fix:** Assign these deliberate updates to the relevant tickets. Preserve the boundary checks using profile capacities and sufficient awarded steps for unlocked-route cases. **If skipped:** Correct new behavior fails the required regression suite.

5. **SHOULD FIX — The raid migration breaks three existing SQL fixtures.** [M8.1a.md:29](<docs/features/pokewalker-v1.1-v2/tickets/M8.1a.md:29>)

   **Problem:** Adding `raid_spawn_id` breaks positional inserts in [test_walker_encounter.py:88](<tests/test_walker_encounter.py:88>), [test_walker_ack.py:41](<tests/test_walker_ack.py:41>), and [test_route.py:92](<tests/test_route.py:92>). An in-memory SQLite reproduction confirmed all three change from valid SQL to “22 columns but 21 values were supplied.”

   **Fix:** Assign explicit-column fixture updates to M8.1a and include these suites in verification. Remove M8.1c’s promise that the encounter suite stays unchanged. **If skipped:** Regression tests fail before exercising raid behavior.

6. **SHOULD FIX — An expired spawn temporarily blocks another ticket.** [M8.2a.md:22](<docs/features/pokewalker-v1.1-v2/tickets/M8.2a.md:22>)

   **Problem:** Ticket use rejects any unended spawn, while [M8.4.md:20](<docs/features/pokewalker-v1.1-v2/tickets/M8.4.md:20>) ends expired spawns only through cleanup. Between the deadline and the next sweep, `/raid` reports no active spawn but ticket use still reports one.

   **Fix:** Run expiry settlement before checking for an active spawn. Test ticket use after expiry with cleanup still pending. **If skipped:** Players receive contradictory responses for up to a sweep interval.

7. **SHOULD FIX — Deployed evolution controls must be both absent and disabled.** [M7.7b.md:17](<docs/features/pokewalker-v1.1-v2/tickets/M7.7b.md:17>), [M7.7c.md:26](<docs/features/pokewalker-v1.1-v2/tickets/M7.7c.md:26>)

   **Problem:** M7.7b makes evolution options empty so the Evolve button disappears. M7.7c requires four disabled buttons, including Evolve. Both acceptance rules cannot hold.

   **Fix:** Keep the smaller existing rule: Evolve is absent while deployed; the other three actions are disabled. Update M7.7c’s acceptance case. **If skipped:** Implementers must contradict one ticket to satisfy the other.

8. **NIT — Survivor rewards display an internal deployment UUID.** [M7.4a.md:33](<docs/features/pokewalker-v1.1-v2/tickets/M7.4a.md:33>)

   **Problem:** The new `survivor:<deployment_id>` inbox key reaches the fallback at [bot/milestones.py:68](<pokewalker/bot/milestones.py:68>), producing “Survivor: \<UUID\>.”

   **Fix:** Assign a small renderer change mapping this category to “Gym survivor reward,” with one display assertion. **If skipped:** Players see an internal identifier instead of a useful reward source.

Verdict: fix 1–7 before implementation. All tickets fit within 4 KiB; the largest is 4,086 bytes. No files were edited or committed.

Not checked: full runtime suites or live Discord behavior. The 300-production-line limits remain estimates until implementation.

MUST=3 SHOULD=4 NIT=1
