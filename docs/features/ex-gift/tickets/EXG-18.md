# EXG-18 — Pokémon details: Shiny Patch and Golden Bottlecap buttons

**Tier:** seam (interaction responses)

**Read:** PLAN D7, D8; SYNTHESIS EX-21, EX-24, R10, R11; EXG-12, EXG-13 (preview and confirm handlers, `ex_back`); `bot/storage.py` `render_detail` (:47-83, IV buttons :77-82), `show_detail` (:173-195).

**Goal.** A player holding a Shiny Patch or Golden Bottlecap uses it straight from Pokémon details; the buttons are hidden when none is held (EX-24). C5 first.

- **`show_detail`:** the state adds `'ex_items': await ex_gift_service.held(conn, session['profile_id'])`; the selection drops `ex_back` and `ex_item`, so the preview's Back and the confirm return to details.
- **`render_detail`** row 2, after Use Bottlecap and Use Vitamin: `Use Shiny Patch` (`ex_preview_shiny_patch`) and `Use Golden Bottlecap` (`ex_preview_golden_bottlecap`), each only while held ≥1. They stay enabled for shiny, perfect or deployed targets, so the preview gives the EX-21 or gym refusal as a message. Row 2 holds at most four buttons.
- The EXG-12 and EXG-13 handlers already serve this path; this row adds no handler.
- **C5:** amend "Bottlecap and Vitamin" (details) with the two EX buttons and their visibility rule.

**Files.** Production: `pokewalker/bot/storage.py`. Tests: `tests/test_storage.py`, `tests/test_ex_gift_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_storage.py`:
- `test_details_ex_buttons_hidden_without_ex_items`
- `test_details_ex_buttons_shown_while_held_row_2_fits`

In `tests/test_ex_gift_screens.py`:
- `test_details_shiny_patch_preview_back_returns_to_details`
- `test_details_shiny_patch_confirm_redraws_details_shiny`
- `test_details_golden_bottlecap_confirm_redraws_perfect_ivs`
- `test_details_refusals_shiny_perfect_and_deployed_with_messages`
- `test_details_stale_preview_after_trade_refused`

Existing `tests/test_storage.py` and `tests/test_iv_items.py` pass unchanged (with no EX item held the view is as today).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `storage`, `ex_gift_screens`, `iv_items`, `gym_screens`, `share`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `bot/ex_gift.py` or a service needs a change; a details pin moves; over 300 production lines.

**Do not touch.** `services/**`, other `bot/` modules.
