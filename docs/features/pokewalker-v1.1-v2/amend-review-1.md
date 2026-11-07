What this change does: The amendment adds all 63 Alcremie forms, contextual purchase/capacity actions, and a U+FFFD guard. I reviewed the tickets against `1ac0157`, current HEAD `878b443`, and the pending v2 rows, assuming the existing single-writer deployment serving a few hobby servers.

1. **MUST FIX — The prescribed lookup crashes on SQLite rows** — [M6.8b.md:23](<scratchpad>/amend/tickets/M6.8b.md:23)
   **Problem:** `pokemon.get("form_id")` fails for `sqlite3.Row`. Home and caught-encounter rendering pass these rows directly (`bot/walker.py:192,301`). An in-memory probe reproduced `AttributeError`.
   **Fix:** Read the optional field using an operation supported by both rows and dictionaries. Test real SQLite rows with and without `form_id`, plus dictionaries.
   **If skipped:** Ordinary Home and catch screens break immediately after M6.8b.

2. **MUST FIX — Gym receipts discard the exact form** — [M6.8b.md:11](<scratchpad>/amend/tickets/M6.8b.md:11)
   **Problem:** The claim that callers inherit form support overlooks `services/gyms.py:204`: `_battle_snapshot` copies an explicit field list without `form_id`. The pending battle renderer resolves sprites from that snapshot. A probe resolved an owned `869:10346` correctly, then resolved its snapshot as `869:869`.
   **Fix:** Assign snapshot persistence and its contract/test fallout explicitly. Extend pending M7.6b to cover the service and renderer within two production files, updating its bounds, or add a bounded row if it has already landed. Test non-default Alcremie as attacker and defender, including receipt replay.
   **If skipped:** Battle results substitute the default Alcremie picture.

3. **MUST FIX — Catch shortcuts lose raid encounters** — [M6.8f.md:22](<scratchpad>/amend/tickets/M6.8f.md:22), [M6.8g.md:19](<scratchpad>/amend/tickets/M6.8g.md:19)
   **Problem:** M8.1c makes `open_encounter` exclude raids unless a confirmation flag identifies one. A storage-full raid throw with an ordinary ball has no such flag; research also discards its encounter ID. Returning therefore opens the ordinary queue or Home.
   **Fix:** Preserve the encounter ID through both shortcuts and amend M8.1c to recognize this explicit return path, with ownership/state/expiry checks. Test successful and cancelled returns with ordinary encounters queued and with none. Ball reset can remain as decided.
   **If skipped:** The promised return to the encounter breaks once raids land.

4. **MUST FIX — Migration fallout misses an existing failing test** — [M6.8b.md:14](<scratchpad>/amend/tickets/M6.8b.md:14)
   **Problem:** `tests/test_gyms.py:361–388` upgrades to the latest schema, removes only `gym_deployment_id`, compares the entire Pokémon row, and expects version 14. Migration 0015 breaks both assertions. The ticket omits this file and suite, although M6.8c subsequently runs it.
   **Fix:** Include that test in M6.8b’s files and verification, asserting the new nullable field deliberately. Also assign version-expectation updates for capacity, gym, and new form tests when M8.1a introduces 0016, or explicitly bound migration-specific tests to their target version.
   **If skipped:** The promised green sequence fails and later raid migration repeats the problem.

5. **MUST FIX — Cream selection accepts another sweet’s recipes** — [M6.8d.md:29](<scratchpad>/amend/tickets/M6.8d.md:29)
   **Problem:** The ticket saves `evolve_item` but explicitly leaves `evolve_pick` unchanged. That handler validates against every recipe. After selecting Love Sweet, a submitted Strawberry Sweet edge is accepted despite being absent from the displayed cream options.
   **Fix:** For grouped sources, validate the submitted edge against the saved, current item group. Add a cross-group rejection test and exercise the real two-step path in affected screen tests.
   **If skipped:** The sweet selection does not constrain the next screen’s accepted input.

6. **SHOULD FIX — Replace obsolete verification blockers** — [M6.8a.md:20](<scratchpad>/amend/tickets/M6.8a.md:20)
   **Problem:** The ticket requires another network audit and stops without network access, while PLAN-insert still marks sprite existence and the terminal artifact unresolved. Your supplied evidence settles both. M6.8d also permits null sprites without requiring a recorded miss.
   **Fix:** Record the supplied 124 HTTP-200 results and terminal diagnosis, remove the redundant network blocker, and require exact normal/shiny URLs for these verified forms; keep `869.png` for the default.
   **If skipped:** Offline implementation can stop unnecessarily, and missing images can satisfy acceptance despite verified available assets.

All tickets currently meet the byte limit and declared production-file limit. Verdict: fix 1–5 before implementation.

Not checked: full application tests or live Discord; sprite evidence was accepted as supplied. No files edited. The cross-row failures above remain unresolved.
MUST=5 SHOULD=1 NIT=0