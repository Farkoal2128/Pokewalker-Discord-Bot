# ARENA-5 — gyms refuse live Arena team members

**Tier:** seam (persisted state; interaction responses)

**Read:** PLAN D3, D9; REQUIREMENTS AR-6a, AR-6b; ARENA-4; `services/gyms.py` `deploy`, `battle`; `bot/gyms.py` `reason`, `party_state`, `battle_dispatch`, `dispatch`.

**Goal.** A Pokémon on the caller's own live Arena team can neither defend nor attack a gym, and the gym screens say why. C3 and C5 first. Test fixtures insert `arena_runs` rows directly (ARENA-8 does not exist yet).

- **`gyms.deploy`** (:60; after ownership/revision, **before** `companion` :80-81): uid in `profiles.arena_team(conn, profile_id, now)` → `{'status': 'in_arena'}`, no write. A companion on a team gets `in_arena`; off a team, still `companion`.
- **`gyms.battle`** (:256; party loop :301-312, beside the companion/deployed refusal :307-308): a party member on the team → `refuse('in_arena')`, before the companion/deployed refusal. That is before `simulate`, the `gym_battles` insert and `last_battle_at` (:333-341), and it rolls back `settle` like every refusal (:273-279). The nominee must be a party member (:314), so this one check covers "Claim with attacker" (AR-6a) and plain attacks (AR-6b).
- **`bot/gyms.py`:**
  - `reason()` (:209) takes the team set and returns `'in the Arena'` for the deploy and attacker pickers, ahead of its companion reason. Its callers, `party_state` (:227, :233) and the deploy branch (:355, :364), load `profiles.arena_team(conn, session['profile_id'], now)` once per screen.
  - Claim options (`render_party` :127) already skip members that have a `reason`, so a team member is never offered as a claim.
  - `gym_battle_start` (:290-303): status `in_arena` keeps the party screen with "That Pokémon is on your Arena team. Pick another attacker." (not `REOPEN`).
  - `gym_deploy_confirm` (:368-374): status `in_arena` → "This Pokémon is on your Arena team and can't defend a gym until the run ends."
  - `render_result` :154 ("you already hold a gym") stays unreachable for this case because the refusal comes before the battle; a test pins that.
- **C3:** append the `in_arena` refusals to the gym lifecycle. **C5:** append the picker label and the two refusal texts.

**Files.** Production: `pokewalker/services/gyms.py`, `pokewalker/bot/gyms.py`. Tests: `tests/test_arena_gym_block.py` (new). Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** Tests pass, RED first:
- `test_companion_on_team_reports_in_arena_everywhere`, `test_companion_off_team_still_companion`
- `test_deploy_refuses_live_team_member_in_arena_nothing_written`
- `test_deploy_allowed_after_hour_18_without_opening_arena`
- `test_deploy_allowed_after_run_ended`
- `test_other_profiles_run_does_not_block`
- `test_battle_refuses_team_attacker_before_fight_no_cooldown_no_battle_row`
- `test_claim_with_team_member_refused_defender_stays_no_cooldown`
- `test_refused_battle_rolls_back_settle_payouts`
- `test_deploy_and_attacker_pickers_mark_team_members_in_the_arena`
- `test_claim_select_omits_team_member`
- `test_start_with_team_member_keeps_party_screen_with_arena_notice`
- `test_deploy_confirm_names_arena_reason`
- `test_no_result_screen_says_already_hold_a_gym_for_arena_refusal`

Existing `test_gyms`, `test_gym_battle`, `test_gym_screens` and `test_gym_legendary_setting` pass unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena_gym_block.py"`, `-p "test_gyms.py"`, `-p "test_gym_battle.py"`, `-p "test_gym_screens.py"`, `-p "test_gym_legendary_setting.py"`, `git diff --check`.

**Stop if.** An existing gym test needs a changed assertion; the block needs a write, a trigger or a new column; the row passes 300 production lines.

**Do not touch.** `pay_hours`, `end_deployment`, `feed`, `_battle_snapshot` (ARENA-10 owns the roll helper).
