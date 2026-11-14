# ARENA-7 — trades refuse live Arena team members

**Tier:** seam (trading between players)

**Read:** PLAN D3, D10; REQUIREMENTS AR-7a; ARENA-4, ARENA-6; `services/trading.py` `tradable_reason`, `eligible_page`, `offer`, `_recheck`, `confirm`; `bot/trade.py` `REASONS`, `picker`, `trade_offer`.

**Goal.** A team member is left out of the trade picker, refused at offer, and refused again at acceptance, so an offer made before the run started cannot complete during it. C3 and C5 first. Fixtures insert `arena_runs` rows directly.

- **`trading.REFUSED`** (:11) gains `'in_arena'`. `tradable_reason(identity, pokemon, profile, arena_team=frozenset())` (:24) passes the set to `research.protected_reason` (ARENA-6), which reports `in_arena` first.
- **`eligible_page(conn, profile_id, offset, now)`** (:31): load `profiles.arena_team` once; when it is not empty, append `AND pokemon_uid NOT IN (<one placeholder per uid>)` to the **eligible count and eligible page** queries only, so those two agree. The total-owned count (:35) is unchanged: starting a run does not change how many Pokémon the player owns. `_TRADABLE` (:15) itself is unchanged.
- **`offer`** (:164): pass the caller's team at :169 → `{'status': 'ineligible', 'reason': 'in_arena'}`, no write.
- **`_recheck(conn, sides, owners, content, now)`** (:188; sole caller `confirm` :260): load each owner's team and pass it at :196 → `{'side', 'reason': 'in_arena'}`. `confirm` then clears that side's offer exactly as it does for any ineligible offer today (:261). `_swap` is untouched.
- **No trigger change.** `pokemon_trade_guard` (`0018_trades.sql:42`) cannot see the injected clock; the acceptance recheck in the same transaction is the guard (D3).
- **`bot/trade.py`:** `REASONS` (:18) gains `"in_arena": "it is on an Arena team"`; the three `eligible_page` calls (:132, :135, :159) pass `walker.clock()`.
- **C3:** append `in_arena` to the trading eligibility and acceptance rules. **C5:** append the reason text and the picker omission.

**Call sites** (`git grep -n "eligible_page(\|_recheck(\|tradable_reason(" -- pokewalker`): exactly the ones named above.

**Files.** Production: `pokewalker/services/trading.py`, `pokewalker/bot/trade.py`. Tests: `tests/test_trading.py`, `tests/test_trade_screens.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_trading.py`:
- `test_eligible_page_omits_live_team_members_and_counts_agree` (also asserts total-owned is unchanged)
- `test_offer_refuses_team_member_in_arena_no_write`
- `test_offer_made_before_run_start_refused_at_acceptance_side_cleared`
- `test_partner_side_team_member_refused_names_their_side`
- `test_team_member_tradable_after_hour_18_and_after_run_end`
- `test_other_profiles_run_does_not_block_my_trade`

In `tests/test_trade_screens.py`:
- `test_picker_omits_team_member_and_offer_text_names_arena`
- `test_acceptance_refusal_text_names_arena_for_either_side`

Existing trading tests keep their assertions. The direct callers that must now pass `now` are updated with their fixture time and nothing else: `tests/test_trading.py:296,300,628` and `tests/test_trade_screens.py:144` (re-grep `eligible_page(\|_recheck(` in `tests/` before editing). The trigger tests in `tests/test_trading_schema.py` pass unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_trading.py"`, `-p "test_trade_screens.py"`, `-p "test_trading_schema.py"`, `-p "test_trade_command.py"`, `git diff --check`.

**Stop if.** `eligible_page` or `_recheck` has a caller beyond those named; the swap or the trigger would need a change; an existing trading assertion must change.

**Do not touch.** Migration 0018, `_swap`, `services/research.py`.
