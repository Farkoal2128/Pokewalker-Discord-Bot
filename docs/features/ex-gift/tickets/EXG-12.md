# EXG-12 — Shiny Patch: EX-Gift picker, preview, confirm

**Tier:** seam (persisted player state; interaction responses)

**Read:** PLAN D4, D7, D8; SYNTHESIS EX-12, EX-21, R10, R11; EXG-8 (`held`, `take`), EXG-9, EXG-11 (Use button rows); `services/iv_items.py` `quote` (:38), `use` (:54-88); `bot/iv_items.py` `render_preview` (:15-23), `handlers` (:26-60); `bot/arena.py` `team_state` (:320-335, `storage.page` paging); `bot/storage.py` `show_detail` (:173-195, selection keys).

**Goal.** From EX-Gift a player picks one Pokémon, previews and confirms; it becomes shiny. The details-screen button comes in EXG-18 and reuses this preview. C3 and C5 first.

- **`services/iv_items.py`:** `use` accepts `shiny_patch` beside `ITEMS`, with the same key form (`shiny_patch:<uid>:<rev>`), receipt-owner check and `session_owner`. Held count from `ex_gift.held`. Refusals in order: `stale` (revision or not owned), `shiny` (already shiny, EX-21), `missing`; no `deployed` refusal (D8). `compute`: `UPDATE pokemon SET shiny=1,revision=revision+1 WHERE pokemon_uid=? AND profile_id=? AND revision=? AND state='owned'`, `ex_gift.take`, ledger `ex_item / shiny_patch / -1 / shiny_patch` → `{'status': 'used', 'pokemon'}`. `quote` returns `have` and `shiny` for it. Bottlecap and Vitamin do not change.
- **`bot/ex_gift.py`:**
  - `Use Shiny Patch (<n>)` (`ex_use_shiny_patch`) while held → picker: selection `{phase: 'ex_pick', ex_item, offset}`; 10 owned Pokémon per page (`storage.page`, newest first); select `ex_pick` (`<name> · CP <n>`, `· Shiny` when shiny); Prev `ex_pick_prev`, Next `ex_pick_next`, Back `ex_gift`.
  - A pick stores `pokemon_uid`, `pokemon_revision`, `ex_back='ex_pick'` and opens the preview.
  - `ex_preview_shiny_patch`: the selected Pokémon at its revision (else `REOPEN`); `shiny` → `It is already shiny. No Shiny Patch was used.`; none held → `You have no Shiny Patch. Nothing was used.`; else title `Use Shiny Patch`, `<name> becomes shiny. Uses 1 Shiny Patch (have <n>).`, buttons Confirm (`ex_shiny_patch_confirm`) and Back (`ex_back`, else `storage_detail`).
  - Confirm: `iv_items.use`; `used` → EX-Gift with `<name> is now shiny.` (from the picker) or `walker.handlers['storage_detail']` (from details); `stale` → `That Pokémon changed. Pick it again.`; other refusals as above.
- **C3:** amend "Bottlecap and Vitamin" with the Shiny Patch effect and refusals. **C5:** picker, preview, notices.

**Files.** Production: `pokewalker/services/iv_items.py`, `pokewalker/bot/ex_gift.py`. Tests: `tests/test_ex_items.py`, `tests/test_ex_gift_screens.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_items.py`:
- `test_shiny_patch_makes_shiny_bumps_revision_spends_one`
- `test_already_shiny_refused_item_kept`
- `test_stale_after_trade_research_or_evolution_refused` (each real service bumps the revision or sends it)
- `test_gym_deployed_target_allowed_live_arena_snapshot_unchanged`
- `test_same_press_once_other_profile_receipt_stale`, `test_missing_spends_nothing`

In `tests/test_ex_gift_screens.py`: `test_shiny_patch_button_only_while_held`, `test_picker_pages_and_pick_opens_preview`, `test_confirm_returns_to_ex_gift_with_notice`, `test_preview_refuses_shiny_target`, `test_stale_confirm_refused`.

`tests/test_iv_items.py` passes unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_items`, `ex_gift_screens`, `iv_items`, `storage`, `trading`, `research`, `evolution`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** An existing Bottlecap or Vitamin test must change; `bot/iv_items.py` or `bot/storage.py` needs an edit (EXG-18); over 300 production lines.

**Do not touch.** `bot/iv_items.py`, `bot/storage.py`, other services.
