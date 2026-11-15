# EXG-13 — Golden Bottlecap

**Tier:** seam (persisted player state; interaction responses)

**Read:** PLAN D4, D7, D8; SYNTHESIS EX-13, EX-21, R4, R10, R11; EXG-12 (mirror it: same picker, preview and confirm path); `services/iv_items.py` `apply` (:21), `perfect` (:27), `quote` (:38-51), `use` (:54-88); `bot/iv_items.py` `render_preview` (:15-23), `refusal` (:29-32).

**Goal.** From EX-Gift a player picks one Pokémon and maxes all three IVs. Sibling of EXG-12. C3 and C5 first.

- **`services/iv_items.py`:** `use` accepts `golden_bottlecap` like `shiny_patch` (key `golden_bottlecap:<uid>:<rev>`, the owned-receipt lookup before `storage.detail` and every refusal, held count from `ex_gift.held`). Refusals in order: `deployed` (R11, as Bottlecap), `stale`, `perfect` (all IVs 15, EX-21), `missing`. `compute`: `UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15,revision=revision+1 WHERE pokemon_uid=? AND profile_id=? AND revision=? AND state='owned'`, `ex_gift.take`, ledger `ex_item / golden_bottlecap / -1 / golden_bottlecap`. `quote` computes `cp_after` and `stars_after` from `(15, 15, 15)` with the same `cp` and `appraisal` calls; the lowest-IV `apply` stays for Bottlecap and Vitamin.
- **`bot/ex_gift.py`:** `Use Golden Bottlecap (<n>)` (`ex_use_golden_bottlecap`) while held opens the EXG-12 picker with `ex_item='golden_bottlecap'`. `ex_preview_golden_bottlecap`: `deployed` → `Recall it from the gym first`; `perfect` → `Its IVs are already perfect. No Golden Bottlecap was used.`; none held → `You have no Golden Bottlecap. Nothing was used.`; else it records `ex_preview='golden_bottlecap'` and shows title `Use Golden Bottlecap` and the `render_preview` line form: `CP <a> → <b> · Appraisal <x> → <y> stars · uses 1 Golden Bottlecap (have <n>)`. Confirm (`ex_golden_bottlecap_confirm`) and Back as EXG-12; Confirm requires `ex_preview == 'golden_bottlecap'`, else `Preview the Golden Bottlecap before confirming.`; `used` → `<name>'s IVs are now 15 / 15 / 15.`
- **C3:** amend with the Golden Bottlecap effect and refusals. **C5:** preview and notices.

**Files.** Production: `pokewalker/services/iv_items.py`, `pokewalker/bot/ex_gift.py`. Tests: `tests/test_ex_items.py`, `tests/test_ex_gift_screens.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_items.py`:
- `test_golden_bottlecap_maxes_all_three_ivs_bumps_revision`
- `test_golden_bottlecap_quote_cp_and_appraisal_after`
- `test_perfect_target_refused_item_kept`
- `test_gym_deployed_target_refused`
- `test_golden_stale_and_missing_spend_nothing`
- `test_golden_replay_returns_used_after_ivs_and_stock_change`

In `tests/test_ex_gift_screens.py`: `test_golden_bottlecap_button_only_while_held`, `test_golden_preview_shows_cp_and_appraisal_change`, `test_golden_preview_refusals`, `test_golden_confirm_after_shiny_preview_or_none_spends_nothing`.

`tests/test_iv_items.py` passes unchanged (Bottlecap still raises only the lowest IV).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_items`, `ex_gift_screens`, `iv_items`, `storage`, `gym_screens`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** An existing IV-item test must change; `bot/iv_items.py` needs an edit; over 300 production lines.

**Do not touch.** `bot/iv_items.py`, `bot/storage.py`, other services.
