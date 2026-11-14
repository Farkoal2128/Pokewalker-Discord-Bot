# ARENA-8 — `services/arena.py`: run start, expiry, party order, heal

**Tier:** seam (persisted player state; rate limit)

**Read:** PLAN D2-D5, D7; REQUIREMENTS AR-1..AR-8, AR-10c, AR-12, AR-13, AR-15, AR-35a; ARENA-2..4; `gyms.py` `deploy` :68-73, `feed` :224-239, `_battle_snapshot` :242; `items.checkin` :111-114; `profiles.session_owner`.

**Goal.** New service module; mutators need the writer transaction (`gyms.py:15`). `rules = load_table('arena')['rules']`; `now` = `Walker.clock()`; receipts pass `profile_id` (AR-4b). C3 first.

- **`state(conn, session, now)`** → `{'status': 'none'|'live'|'ended', 'run', 'cooldown_left', 'enabled', 'best_floor', 'tickets'}`. A live run past `started_at + run_seconds` is ended first (`expired`, `revision+1`, AR-3). Every other function calls this first.
- **`start(conn, session, team, now, rng, content, multipliers)`**, `team` = three `(uid, revision)`. In order; `state` runs first, so an over-time run is saved as `expired` even if the start is refused. Otherwise a refusal writes nothing:
  1. `session_owner` → `stale` / `excluded`.
  2. paused → `{'status': 'paused', 'until'}`, the check-in shape.
  3. `guilds.arena_enabled = 0` → `off`.
  4. a live run → `live`.
  5. latest `started_at + cooldown_seconds > now` → `{'status': 'cooldown', 'seconds_left'}`.
  6. `team_size` distinct uids, each owned at that revision (`storage.detail`) → else `invalid` / `stale`; `gym_deployment_id` set → `deployed`. The companion and specials may join (AR-6).
  7. Receipt `arena_start:<session_id>:<_original_revision>`: snapshot each member with `_battle_snapshot` (`full_hp = hp = combatant.hp`, `family_id`, `special`), roll the floor 1 entry enemy, insert the run at `floor 1, slot 0` → `started`.
- **Enemy helper** (reused by ARENA-9): `domain.roll_enemy` → row `{pokemon_uid: None, pokemon_id, form_id, revision: 0, content_version: profiles.content_facts(content)[0], level_x2, iv_attack/defense/stamina, gender: 'genderless', shiny: 0}` (every key `_battle_snapshot` reads, gyms.py:250) → `_battle_snapshot` → stored `{'snapshot', 'battle_hp': domain.enemy_hp(hp, factor_x10), 'special'}`.
- **`set_order(conn, session, run_id, revision, order, now)`**: `order` is a permutation of `(0,1,2)`; reorders `team`, bumps `revision`. No receipt: no resource moves.
- **`heal(conn, session, run_id, revision, positions, berry, now)`**: `berry` in `heal_items`; each position below `full_hp` (else `full`); needs `len(positions)` berries (else `missing` with `short`, nothing spent). Receipt `arena_heal:<run_id>:<revision>`: debit inventory, `hp = full_hp`, bump `revision`, ledger line `item` / berry / `-n` / `arena_heal` → `healed`.
- **Stale rule** (AR-4a), `set_order`/`heal`: no live run, other `run_id` or `revision` → `{'status': 'stale', 'run'}`, nothing spent.

**Files.** Production: `pokewalker/services/arena.py`. Tests: `tests/test_arena.py` (new). Contract: `contracts/persisted-state.md`.

**Accept.** Tests pass, RED first: `test_start_snapshots_and_rolls_enemy`, `test_every_identity_snapshots_as_itself` (through the real enemy-row builder), `test_start_refusals_in_order_write_nothing`, `test_paused_start_persists_expiry_only`, `test_companion_legendary_may_join`, `test_cooldown_runs_18h_from_start`, `test_same_start_press_one_run`, `test_expires_at_hour_18_first`, `test_restart_resumes_same_state`, `test_powerup_keeps_snapshot`, `test_set_order_persists`, `test_heal_mixed_berry_types`, `test_heal_short_spends_nothing`, `test_golden_razz_refused`, `test_stale_revision_spends_nothing`, `test_every_receipt_has_profile_id`.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena.py"`, `git diff --check`.

**Stop if.** Over 300 production lines (move `heal` to ARENA-9); `_battle_snapshot` needs an edit; an import cycle with `services/gyms.py` appears.
