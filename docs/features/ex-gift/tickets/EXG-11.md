# EXG-11 — Time Gear Fragment

**Tier:** seam (persisted player state; abuse controls)

**Read:** PLAN D1, D4, D7, D8; SYNTHESIS EX-11, EX-25, R4, R6; EXG-8 (`held`, `take`, `recorded`), EXG-9; `services/cooldowns.py` (`PLAYER` :3-10, loop :34-44, audit :45-48); `0010_profiles_last_share.sql`; `bot/share.py:72`; `domain/steps.py:66`.

**Goal.** One Time Gear Fragment resets the six D67 player cooldowns of the profile in this server, without a moderation record. Contract and tests first (C3, C5).

- **`services/cooldowns.py`:**
  - Move the loop of `reset` (:34-44) into `clear(conn, scope, args, kinds, now, guild_id)`; `reset` calls it and still writes its `mod_audit` row. D67 behavior does not change.
  - `time_gear(conn, session, now)`, key `ex_time_gear:{session_id}:{rev}` (`rev` per D4): `profiles.session_owner` refusal; then `ex_gift.recorded(conn, key, 'ex_time_gear', pid)`, returned as is when found (D4); then none held (`ex_gift.held`) → `missing`; else `with_receipt(conn, key, 'ex_time_gear', compute, profile_id=…)`. `compute`: `ex_gift.take`, `clear(conn, 'guild_id=? AND user_id=?', [guild, user], list(PLAYER), now, guild)`, ledger `ex_item / time_gear_fragment / -1 / ex_time_gear` → `{'status': 'used', 'cooldowns': list(PLAYER)}`. No `mod_audit` row (R6). The force-raid, share (`last_share_at`) and step-credit limits stay (EX-25). Paused members may use it (D8).
- **`bot/ex_gift.py`:** EX-Gift row 1 gets `Use Time Gear Fragment (<n>)` (`ex_use_time_gear_fragment`) while held. It opens a confirm screen: `Reset your cooldowns in this server?`, the six `PLAYER` labels, `Share and message limits stay.`, `Uses 1 Time Gear Fragment (have <n>).`; buttons Confirm (`ex_time_gear_confirm`) and Back (`ex_gift`); selection phase `ex_time_gear`. Confirm without that phase → `REOPEN`. Afterwards EX-Gift shows `Time Gear Fragment used: your cooldowns in this server are reset.` or `You have no Time Gear Fragment.` Use buttons take rows 1-2 in `EX_ITEMS` order; later rows add theirs the same way.
- **C3:** append "Time Gear Fragment": the reused D67 updates, the receipt, no audit. **C5:** the button, confirm screen and notices.

**Files.** Production: `pokewalker/services/cooldowns.py`, `pokewalker/bot/ex_gift.py`. Tests: `tests/test_ex_items.py` (new), `tests/test_ex_gift_screens.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_items.py`:
- `test_time_gear_resets_six_cooldowns_for_this_profile_only` (another player here and the same user in another server keep theirs)
- `test_time_gear_keeps_force_raid_share_and_step_limits`
- `test_time_gear_no_mod_audit_profile_receipt_and_ledger`
- `test_time_gear_missing_spends_nothing`, `test_excluded_member_refused`
- `test_same_press_replays_used_after_stock_reaches_zero` (result equal to the first)
- `test_arena_cooldown_cleared_after_time_gear` (through `arena.state`)

In `tests/test_ex_gift_screens.py`: `test_time_gear_button_only_while_held`, `test_time_gear_confirm_then_notice`, `test_time_gear_confirm_without_phase_refused`.

`tests/test_cooldown_reset.py` passes unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_items`, `ex_gift_screens`, `cooldown_reset`, `admin`, `arena`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A D67 test must change; a third production file is needed; over 300 production lines.

**Do not touch.** `bot/admin.py`, `bot/share.py`, `domain/steps.py`, other services.
