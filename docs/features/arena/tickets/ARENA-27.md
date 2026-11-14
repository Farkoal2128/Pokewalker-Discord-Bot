# ARENA-27 — `fight`: boosted party combatants and the per-fight countdown

**Tier:** seam (persisted player state; battle inputs)

**Read:** PLAN D2, D5, D20; AR-42, AR-44, AR-45; ARENA-9, 17, 26; `services/arena.py` `fight`, `chain_step`, `heal_all_and_fight`; `domain/battle.py` `Combatant`.

**Goal.** An active X item doubles the party's stat in Arena fights and counts down one per fight. C3 first.

- **Boost** (in `fight`'s `compute`, where `party` is built): for each `rules.x_items.items` entry whose `run['<item>_left'] > 0`, multiply that `stat` of every party `Combatant` by `rules.x_items.multiplier`, in the `dataclasses.replace` call that already sets `hp`. Both kinds active → both stats.
- Only the party combatants of that `battle_engine.simulate` call change. The enemy `Combatant`, its `battle_hp`, the call's other arguments, the stored team snapshots (D2), `domain/battle.py`, `ENGINE_VERSION` and C7 do not.
- **Countdown:** in the `UPDATE arena_runs` that stores the fight, each counter drops by one, not below 0. Win, loss and draw alike. A loss or draw also ends the run: what is left is never read again and nothing is refunded. Expiry (`state`) leaves the counters as they are.
- So a use at 3 boosts the next three fought fights, whichever floors they are on; the fourth is unboosted.
- `chain_step` and `heal_all_and_fight` fight through `fight`: boosted and counted with no code of their own. A chain gets no new stop reason: it runs on when a boost ends.
- The fight result, its receipt (D5) and its ledger lines do not change: no new key. The screens read the counters from `run`. A replayed fight neither fights nor counts down again.
- **C3:** append "Arena boosted fights (ARENA-27)": the multiplied fields, the countdown rule, what does not change.

**Files.** Production: `pokewalker/services/arena.py`. Tests: `tests/test_arena.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_arena.py` pass, RED first. A test that reads the combatants wraps `battle_engine.simulate` and keeps the `party` and `enemy` it was given:
- `test_x_attack_doubles_only_party_attack_given_to_simulate`
- `test_x_defense_doubles_only_party_defense_and_both_kinds_combine`
- `test_enemy_combatant_and_stored_snapshots_stay_unboosted`
- `test_three_fights_boosted_fourth_not_both_counters_drop_each_fight`
- `test_loss_and_draw_count_down_and_end_the_run`
- `test_expired_run_keeps_counters_and_refunds_nothing`
- `test_chain_step_and_heal_all_fights_are_boosted_and_counted`
- `test_chain_continues_when_a_boost_runs_out`
- `test_replayed_fight_counts_down_once`
- `test_crash_mid_boost_keeps_count_and_rolls_back_together` (start 3, one fight commits, crash in the second: 2 left, no extra drop on resume; a ledger failure after the fight UPDATE rolls back counters, run and receipt)
- `test_fight_result_and_receipt_keys_unchanged_by_boost`
- `test_real_engine_boosts_cut_ticks_and_damage_taken` (no patch; the same team, enemy and seed with and without each item, at a floor where the unboosted fight lasts several ticks: X-Attack needs fewer ticks, X-Defense keeps more party HP)

No pinned test changes: with both counters at 0 every existing fight test passes as it is.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena`, `arena_screens`, `battle`, `gym_battle`, `deletion`, `receipt_owner`; `git -c core.whitespace=cr-at-eol diff --cached --check` (the contract has CR line ends: keep them).

**Stop if.** The boost needs a change in `domain/**`, `services/gyms.py` or the snapshot format; a new result key or receipt field is needed; an existing fight test fails with both counters at 0; no fixture floor shows the real-engine effect (report the numbers; do not change the rule); over 300 production lines.

**Do not touch.** `domain/**`; `services/gyms.py`, `services/items.py`; `buy_x`, `use_x`; `bot/**`; migrations; `content/**`.
