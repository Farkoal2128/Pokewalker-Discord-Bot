# ARENA-17 — floor skip at run start and the Fight-until-hurt chain step

**Tier:** seam (persisted player state; progression rules)

**Read:** PLAN D4, D5, D14, D19; REQUIREMENTS AR-3, AR-4a, AR-8, AR-10b..AR-10d, AR-11a, AR-32..AR-34; ARENA-9, ARENA-16; `services/arena.py` `start`, `set_order`, `fight`, `heal_all_and_fight`.

**Goal.** A run may start past proven floors, and one function resolves one chain fight. C3 first.

- **`domain/arena.py`** (pure; `health` = `[(hp, full_hp), ...]` in party order):
  - `max_skip(best_floor, rules)` → `min(best_floor // skip.divisor, skip.max)`.
  - `skip_tickets(skip, rules)` → `{tier: copies}` for floors `1..skip`, through `ticket_for`; `{}` at 0.
  - `hurt(health, pct)` → the first position with `hp * 100 < pct * full_hp`, else `None`.
  - `hp_order(health)` → positions by `hp / full_hp`, highest first, ties in current order; exact (`fractions.Fraction`), never float or raw HP.
- **`start(..., multipliers, skip=0)`.** With the team checks: `skip` must be an `int` in `0..max_skip(best_floor)`, else `invalid`. Inside the existing `arena_start` receipt: the run starts at floor `skip + 1`, slot 0, full HP, with that floor's entry enemy; each `skip_tickets` tier is added to `arena_tickets` with a ledger line `arena_ticket` / tier / `+n` / `arena_skip`. No first-clear bonus, no Candy, `arena_best_floor` unchanged. The result keeps its shape (`started` plus `run`); screens derive the payment from `skip_tickets`.
- **`chain_step`** (`fight`'s arguments), one writer job:
  1. `state` (ends an over-time run; `stale` / `excluded`), then the stale rule → `{'status': 'stale', 'run'}`.
  2. `hurt(health, stop_pct)` is set → `{'status': 'hurt', 'position', 'run'}`; nothing fights (D19).
  3. `auto_order` on and `hp_order` differs from the current order → `set_order`; go on at its revision.
  4. `fight`. Return its result plus `run` (the saved run after the fight) and `stop`: `'hurt'` with `position` when a member was revived or `hurt` is set for the new HP; else `'ticket'` when `tickets` is set; else `None`. `defeated` needs no `stop`.
  - It never spends a berry. Paused members continue: a pause is not a stop (AR-8).
  - `stop` and `run` are added outside the fight receipt, which keeps its D5 shape.

**Files.** Production: `pokewalker/services/arena.py`, `pokewalker/domain/arena.py`. Tests: `tests/test_arena.py`, `tests/test_arena_domain.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_domain.py`:
- `test_max_skip_half_best_floor_capped_at_40` (30 → 15, 79 → 39, 80 → 40, 1 → 0)
- `test_skip_tickets_follow_schedule` (40 → 2 Bronze, 4 Silver, 2 Gold)
- `test_hurt_is_strictly_below_and_hp_order_keeps_ties`

In `tests/test_arena.py`:
- `test_skip_starts_at_next_floor_full_hp_with_that_floors_enemy`
- `test_skip_pays_scheduled_tickets_with_ledger_lines_at_start`
- `test_skip_pays_no_bonus_or_candy_and_keeps_best_floor`
- `test_skip_over_limit_or_malformed_refused_writes_nothing`
- `test_same_start_press_pays_skip_once`
- `test_chain_step_fights_once_and_continues`
- `test_chain_step_hurt_member_stops_before_fighting`
- `test_chain_step_stops_after_revive_or_below_threshold`
- `test_chain_step_stops_after_ticket_floor_boss`
- `test_chain_step_defeat_stale_expired_or_excluded`
- `test_chain_step_auto_order_by_hp_percentage_only_when_on`
- `test_chain_step_spends_no_berries_and_keeps_receipt_shape`

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena`, `arena_domain`, `arena_screens`, `deletion`, `receipt_owner`; `git diff --check`.

**Stop if.** `fight` or its receipt shape must change; the skip needs a schema change; a seeded M1 test changes its enemy rolls; over 300 production lines.

**Do not touch.** `domain/battle.py`, `services/gyms.py`, `bot/arena.py`, `arena.json`, migrations.
