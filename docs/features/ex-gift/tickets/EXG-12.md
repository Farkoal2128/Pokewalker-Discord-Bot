# EXG-12 — Shiny Patch: EX-Gift picker, preview, confirm

**Tier:** seam (persisted player state; interaction responses)

**Read:** PLAN D4, D7, D8; SYNTHESIS EX-12, EX-21, R4, R10, R11; EXG-8, EXG-9, EXG-11 (Use rows); `services/iv_items.py` `quote` (:38), `use` (:54-88); `bot/iv_items.py` `render_preview` (:15-23), preview guard (:45-52); `bot/arena.py` `team_state` (:320-335, paging); `bot/storage.py` `show_detail` (:173-195).

**Goal.** From EX-Gift a player picks one Pokémon, previews and confirms; it becomes shiny. The details button (EXG-18) reuses this preview. C3 and C5 first.

- **`services/iv_items.py`:** `use` accepts `shiny_patch` beside `ITEMS`: same key form (`shiny_patch:<uid>:<rev>`), `session_owner`, owned-receipt check. For EX items that lookup (:66-71) moves before `storage.detail` and every refusal, so a replay returns its recorded result (D4); Bottlecap and Vitamin keep their order. Held count from `ex_gift.held`. Refusals: `stale` (revision or not owned), `shiny` (EX-21), `missing`; no `deployed` refusal (D8). `compute`: `UPDATE pokemon SET shiny=1,revision=revision+1 WHERE pokemon_uid=? AND profile_id=? AND revision=? AND state='owned'`, `ex_gift.take`, ledger `ex_item / shiny_patch / -1 / shiny_patch`. `quote` returns `have` and `shiny`.
- **`bot/ex_gift.py`:**
  - `Use Shiny Patch (<n>)` (`ex_use_shiny_patch`) while held → picker: selection `{phase: 'ex_pick', ex_item, offset}` (no `ex_preview`); 10 owned Pokémon per page (`storage.page`, newest first); select `ex_pick` (`<name> · CP <n>`, `· Shiny` if shiny); Prev `ex_pick_prev`, Next `ex_pick_next`, Back `ex_gift`.
  - A pick stores `pokemon_uid`, `pokemon_revision`, `ex_back='ex_pick'`, then the preview.
  - `ex_preview_shiny_patch`: the selected Pokémon at its revision (else `REOPEN`); `shiny` → `It is already shiny. No Shiny Patch was used.`; none held → `You have no Shiny Patch. Nothing was used.`; else it records `ex_preview='shiny_patch'` and shows `Use Shiny Patch`: `<name> becomes shiny. Uses 1 Shiny Patch (have <n>).`, Confirm (`ex_shiny_patch_confirm`), Back (`ex_back`, else `storage_detail`).
  - Confirm requires `selection['ex_preview'] == 'shiny_patch'` (as `bot/iv_items.py:51`), else `Preview the Shiny Patch before confirming.`; then `iv_items.use`; `used` → EX-Gift with `<name> is now shiny.` (picker) or `walker.handlers['storage_detail']` (details); `stale` → `That Pokémon changed. Pick it again.`
- **C3:** amend "Bottlecap and Vitamin" with the Shiny Patch. **C5:** picker, preview, notices.

**Files.** Production: `pokewalker/services/iv_items.py`, `pokewalker/bot/ex_gift.py`. Tests: `tests/test_ex_items.py`, `tests/test_ex_gift_screens.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_items.py`: `test_shiny_patch_makes_shiny_bumps_revision_spends_one`, `test_already_shiny_refused_item_kept`, `test_stale_after_trade_research_or_evolution_refused` (each real service), `test_gym_deployed_allowed_arena_snapshot_unchanged`, `test_replay_returns_used_after_revision_and_stock_change`, `test_other_profile_receipt_stale`, `test_missing_spends_nothing`.

In `tests/test_ex_gift_screens.py`: `test_shiny_patch_button_only_while_held`, `test_picker_pages_and_pick_opens_preview`, `test_confirm_returns_to_ex_gift_with_notice`, `test_preview_refuses_shiny_target`, `test_confirm_without_or_with_other_preview_spends_nothing`, `test_stale_confirm_refused`.

`tests/test_iv_items.py` passes unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_items`, `ex_gift_screens`, `iv_items`, `storage`, `trading`, `research`, `evolution`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A Bottlecap or Vitamin test must change; `bot/iv_items.py` or `bot/storage.py` needs an edit; over 300 production lines.

**Do not touch.** `bot/iv_items.py`, `bot/storage.py`, other services.
