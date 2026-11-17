# EXR-5 — coverage: EX encounters through the existing catch path

**Tier:** seam (encounter and catch rules; persisted player state). Tests only.

**Read:** PLAN D4, D5; SYNTHESIS R6 (expiry and cleanup need no change), R7, §7; EXR-3, EXR-4; `services/catching.py:55-80`; `services/research.py:114-134`; `domain/cp.py:49-64`; `bot/client.py:187-196`; `tests/test_raids.py` `RaidJoinTests` (:966, fixtures and `throw` helper), `RaidSweepTests` (:1868).

**Goal.** Prove the synthesis's "no change needed" claims for catching, rewards, auto-send, expiry and the queue, with EX spawns made by `raids.ex_commit` and joined by `raids.join`. This row writes no production code and amends no contract (C4 is unchanged, R7).

**No RED.** Every test is expected to pass on its first run. The commit body records that first run. A failing test is a finding against R6 or R7: stop and report it. Never fix it here and never weaken the assertion.

**Files.** Production: none. Tests: `tests/test_ex_raid.py`. Contract: none.

**Accept.** New tests in `tests/test_ex_raid.py` pass:
- `test_ordinary_boss_join_catch_rewards_pokedex_never_flees`: exact identity; CP from the species stats and the level; catch chance from the species `base_catch_rate` and the level (`domain.cp.catch_probability`); a failed throw never flees (tier `Legendary/Mythical`, `legendary_flee_probability` 0); the species' candy and Stardust; Pokédex seen at join and caught at catch
- `test_mythical_boss_end_to_end`
- `test_regional_form_boss_keeps_its_form` (`10100:10202`, Alolan Raichu)
- `test_gender_variety_boss_stores_the_rolled_variety` (`876:876`, Male Indeedee)
- `test_locked_level_sets_cp_and_catch_chance`
- `test_master_ball_catches_and_full_storage_waits_like_any_catch`
- `test_unconfirmed_ordinary_ex_catch_is_auto_sent_after_900_s`
- `test_shiny_legendary_and_mythical_ex_catches_are_never_auto_sent`
- `test_catch_committed_before_expiry_stays_readable_after_cleanup`
- `test_throw_at_expiry_is_refused_and_spends_nothing`
- `test_world_legendary_spawns_expires_and_respawns_beside_a_24_h_ex_raid` (ticket, expiry, force-raid; the EX-Raid stays live throughout)
- `test_sweep_ends_ex_raid_at_exactly_expires_at` (one second before: live; at `expires_at`: ended, unfinished encounters and participation removed)
- `test_raids_off_mid_raid_keeps_the_live_ex_raid_and_skips_new_ones`
- `test_ex_encounter_stays_outside_the_three_encounter_queue`

`tests/test_raids.py`, `tests/test_catching.py` and `tests/test_research.py` pass unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid`, `raids`, `catching`, `research`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** Any test here fails on its first run (name the case and the claim it contradicts); a test can only pass by editing production code or a contract; a fixture needs an identity that the catalog lacks (`content/artifact/content.json`).

**Do not touch.** `pokewalker/**`, `contracts/**`, `content/**`.
