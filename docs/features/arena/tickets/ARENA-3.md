# ARENA-3 — pure Arena rules `pokewalker/domain/arena.py`

**Tier:** seam (encounter and progression rules)

**Read:** PLAN D1, D8; REQUIREMENTS AR-14a, AR-16..AR-24, AR-32, AR-33; ARENA-2; `pokewalker/domain/battle.py` `defender_hp`; `pokewalker/domain/encounters.py` `roll_tier`.

**Goal.** A new pure module: no I/O, clock or table loading. Every function takes `rules` (the `arena.json` payload); rolls take `rng`. Slots are 0 entry, 1 middle, 2 boss.

| Function | Rule |
|---|---|
| `level_x2(floor, rules)` | `2 * min(floor, level_cap)` |
| `late_steps(floor, rules)` | `min(iv_steps_max, max(0, (floor - after_floor) // step_floors))` |
| `iv_bounds(slot, floor, rules)` | three `(low, high)` pairs; stat *i* (0 Attack, 1 Defense, 2 Stamina) gains `(steps + 2 - i) // 3`, capped at the tier high |
| `roll_ivs(slot, floor, rng, rules)` | `rng.randint(low, high)` per stat, Attack first |
| `hp_factor_x10(floor, rules)` | 10 up to floor 40; `10 + min(hp_cap_x10 - 10, late_steps * hp_step_x10)` up to floor 115; then `hp_cap_x10 + (floor - 115) * uncapped_step_x10` |
| `enemy_hp(canonical_hp, factor_x10)` | `-(-canonical_hp * factor_x10 // 10)`, the `defender_hp` form |
| `bst_cap(floor, rules)` | `round(base + span * (floor - 1) / span_floors)` below `full_floor`, else `full` |
| `boss_cap(floor, rules)` | `min(full, bst_cap * pct // 100)`; `decade_boss_pct` when `floor % 10 == 0`, else `boss_pct` |
| `is_special(identity, rules)` | `is_legendary` or `is_mythical` or `species_id` in either list |
| `pick_identity(floor, slot, identities, rng, rules)` | entry and middle: `rng.choice` over regular identities with `bst <= bst_cap`. Boss: reserved draw `rng.randrange(100) < chance`; on a hit, `rng.choice` over special identities with `bst <= boss_cap` if any; otherwise regular identities under `boss_cap` |
| `roll_enemy(floor, slot, identities, rng, rules)` | dict `identity`, `level_x2`, `ivs`, `factor_x10`, `special`; rng order: identity, then IVs |
| `ticket_for(floor, rules)` | tier name or `None` from `tickets.schedule` |
| `first_clear_bonus(floor, best_floor, rules)` | `floor > best_floor` and the floor's tier is in `first_clear_tiers` |
| `candy_for(special, slot, rules)` | `per_knockout`; 0 for a special finisher off the boss slot |
| `revive(party_hp)` | `[max(1, hp) for hp in party_hp]` |

**Files.** Production: `pokewalker/domain/arena.py`. Tests: `tests/test_arena_domain.py` (new).

**Accept.** Tests pass, RED first (absent module → `self.fail`, as `tests/test_battle.py:20` does):
- `test_level_is_floor_until_40_then_flat`
- `test_iv_bounds_match_requirement_table` (floors 1, 45, 50, 55, 60, 90, 100, 115; entry at 60 is 2/1/1)
- `test_hp_factor_matches_requirement_table` (41-44 → 10, 45 → 11, 50 → 12, 60 → 14, 90 → 20, 115 → 20, 116 → 21, 125 → 30)
- `test_bst_caps_match_requirement_table` (floors 1/5/10/20/30/32/40: base 300/354/422/557/693/720/720, boss 345/407/633/720/720/720/720)
- `test_pool_sizes_match_requirement_table` (regular entry pool 177/344/484/952 at floors 1/5/10/20; special boss pool 2/4/105/128)
- `test_entry_and_middle_never_special`
- `test_boss_special_reserved_draw_5_and_25_percent`
- `test_boss_falls_back_to_regular_when_no_special_fits`
- `test_ticket_schedule_floors_1_to_100`
- `test_first_clear_bonus_only_silver_or_better_above_best_floor`
- `test_special_finisher_earns_candy_only_from_boss`
- `test_revive_lifts_fainted_to_one_hp`
- `test_same_seed_same_enemy`

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena_domain.py"`, `git diff --check`.

**Stop if.** A requirement table value cannot be reproduced (report the floor and both values); the module needs I/O; a value is missing from `arena.json` (amend ARENA-2's table and C4 first, never hard-code).

**Do not touch.** `domain/battle.py`, `domain/encounters.py`, `domain/cp.py`.
