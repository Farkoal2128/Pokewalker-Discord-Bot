# EXR-3 — locks at join

**Tier:** seam (encounter rules; persisted player state)

**Read:** PLAN D4; SYNTHESIS XR-3, R2, R7; EXR-1, EXR-2; `services/raids.py:47-71`; `domain/encounters.py:66-88`; `content/balance/catch.json:43-50`; C3 "M8.3a", "Owner amendment: raid boss minimum level".

**Goal.** An EX spawn's locks replace individual rolls for every player; open fields roll exactly as today. Tests insert the `ex_raids` row and its `kind='ex'` spawn directly. C3 first.

- **Locks read.** `join`'s spawn read left-joins `ex_raids` on `ex_raid_id` and takes `shiny`, `level`, `iv_attack`, `iv_defense`, `iv_stamina`. A `world` spawn has none (all NULL).
- **Draw sequence, never changed by a lock:** `roll_gender`, `roll_shiny`, one `roll_level_ivs(..., level_range='raid_level_range')`. Each non-NULL lock then overwrites its field: `shiny` (0 and 1 are both locks), `level_x2 = 2 * level`, each IV on its own. Gender always rolls.
- **Lure.** With `shiny` locked, `active_lure` is not read, the encounter stores `lure_id` NULL and no lure encounter is consumed. With `shiny` open, the lure applies and is consumed as today (:49-65).
- Unchanged: tier `encounters.LEGENDARY`, route, content version, Pokédex seen, participation, the `raid:<spawn_id>:<user_id>` receipt, rollback together. `domain/encounters.py` is not edited.
- **C3:** amend "M8.3a": the lock rule, the fixed draw sequence, the lure rule. Rolls are made once at join and frozen in the encounter.

**Files.** Production: `pokewalker/services/raids.py`. Tests: `tests/test_ex_raid.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_ex_raid.py` pass, RED first:
- `test_no_locks_rolls_like_a_world_legendary` (same seed: same gender, shiny, level in 20-25, IVs)
- `test_each_lock_alone_overrides_only_its_field` (five subtests)
- `test_all_five_locks_fix_shiny_level_ivs_gender_still_rolls`
- `test_level_1_and_40_and_iv_0_and_15_store_and_give_a_cp` (`level_x2` 2 and 80; `storage.stats` returns a CP)
- `test_shiny_false_and_iv_zero_are_locks_not_unset`
- `test_shiny_locked_keeps_the_lure_and_stores_no_lure_id`
- `test_shiny_open_consumes_one_lure_encounter`
- `test_draw_sequence_is_the_same_whatever_is_locked` (a recording RNG: equal call lists)
- `test_partial_locks_two_players_share_locked_fields_and_roll_the_rest`
- `test_rejoin_returns_the_same_encounter_no_reroll_no_second_lure`
- `test_rolled_back_join_leaves_nothing` (encounter, lure, Pokédex, participation, receipt)

`tests/test_raids.py` `RaidJoinTests`, `tests/test_lure.py` and `tests/test_shiny_charm.py` pass unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid`, `raids`, `lure`, `shiny_charm`, `encounters`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A World Legendary join draws differently than before (a seeded `RaidJoinTests` case changes); `domain/encounters.py` or `catch.json` needs an edit; over 300 production lines.

**Do not touch.** `domain/**`, `content/**`, `services/catching.py`, `services/research.py`, `bot/**`.
