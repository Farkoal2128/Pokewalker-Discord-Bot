# ARENA-1 — C7: starting HP, `Result.party_hp`, `Result.finisher`

**Tier:** seam (contract C7; its results are persisted by gym battles)

**Read:** PLAN D6; REQUIREMENTS AR-11, AR-11b, AR-14a; `contracts/gym-battle.md`; `pokewalker/domain/battle.py`.

**Goal.** A compatible C7 change so HP can carry between Arena fights. Contract first, then tests (RED), then code.

- **Contract** (`contracts/gym-battle.md`: amend "Inputs and outputs" in place and add `services/arena.py` as a consumer):
  - `Combatant.hp` is the positive integer **starting HP for this fight**. Gyms keep passing canonical HP (`gyms._battle_snapshot`), so gym behavior is unchanged.
  - `Result.party_hp`: each member's HP when the fight ends, in party order; 0 for a fainted member; a bench member that never fought keeps its starting HP.
  - `Result.finisher`: zero-based party position whose hit took the defender to 0 HP, or `None` when the defender did not faint. It is set on a double-knockout draw too.
  - Compatibility: additive fields with defaults; no arithmetic, timing or outcome change; `ENGINE_VERSION` stays `"1"`.
- **Code** (`battle.py`; anchors `class Result` :47, `return Result(` :168):
  - Add `party_hp: tuple[int, ...] = ()` and `finisher: int | None = None` **after** `engine_version`, so the positional constructors in `tests/test_gym_battle.py:128,142` and `tests/test_gym_legendary_setting.py:92` stay valid.
  - `simulate` passes `party_hp=tuple(health)` and `finisher=active if not defender_health else None`. `active` is still the hitter at that point: the loop breaks at :151-155, before `active += 1` (:160).
  - `Combatant` validation is unchanged (:44 already accepts any positive integer).

**Producers and consumers.** `git grep -n "Result(\|simulate(\|\.survivors\|engine_version" -- pokewalker` → producer `battle.py:168`; the only consumer is `services/gyms.py:333-351`, which builds its receipt from named fields and stays byte-identical.

**Files.** Production: `pokewalker/domain/battle.py`. Tests: `tests/test_battle.py`. Contract: `contracts/gym-battle.md`.

**Accept.** New tests in `tests/test_battle.py` pass, each seen RED first:
- `test_party_hp_lists_end_hp_in_party_order_with_zero_for_fainted`
- `test_bench_member_keeps_starting_hp`
- `test_starting_hp_below_canonical_is_used_as_given`
- `test_finisher_is_position_of_the_knockout_hit_after_substitution`
- `test_finisher_set_on_double_knockout_draw`
- `test_finisher_none_on_loss_and_tick_limit`
- `test_result_positional_constructor_still_valid`

Existing `tests/test_battle.py`, `tests/test_gym_battle.py` and `tests/test_gym_legendary_setting.py` pass unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_battle.py"`, `-p "test_gym_battle.py"`, `-p "test_gym_legendary_setting.py"`, `git diff --check`.

**Stop if.** An existing battle or gym test needs an edit; the grep shows a `Result` consumer other than `gyms.py`; a stored gym receipt would change shape.

**Do not touch.** `services/gyms.py`, `content/balance/battle.json`.
