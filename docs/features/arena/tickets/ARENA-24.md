# ARENA-24 — `bot/arena.py`: Fight until hurt coordinator and result; help

**Tier:** seam (interaction responses)

**Read:** PLAN D4, D5, D14, D16, D19; AR-4a, AR-8, AR-10b, AR-15; ARENA-12, 17, 18; `walker.py` `route`; `share.py` `after_commit`.

**Goal.** One press resolves fights back to back, one committed writer job per fight. C5 first.

- **Button** `Fight until hurt` (`arena_until_hurt`), row 0, before the toggle; it joins `BREAK_ACTIONS`.
- **Handler** (dispatch transaction): check the `arena_break` phase, read `run_id` and `run_revision` from the selection as pressed, return `{'after_commit': chain}` only. No fight and no redraw: a redraw would save the current revision and let a stale screen fight (AR-4a).
- **`chain()`** runs after the dispatch commit, under the session lock, with no `bot/walker.py` change (D14). Loop:
  1. `walker.bot.writer.run(job)`. The job calls `service.chain_step` with the expected revision and a fresh `walker.clock()`, renders the screen for the fights so far plus this step, and saves `sessions.selection` (the new `run_revision`) in the same transaction.
  2. After the commit: keep that rendering; append a fought step; go on only when `status` is `won` and `stop` is `None`, at `run['revision']`.
- **Stops** (a break-screen notice unless said otherwise):
  - `hurt`, no fight in this chain: "<name> is below P%. Heal first, or use Fight."
  - `hurt` after a fight: "Stopped: <name> was revived at 1 HP." when revived, else "Stopped: <name> is below P%."
  - `ticket`: "Stopped: floor N paid a ticket."
  - `stale` with a live run: the STALE text. An ended run: the defeat screen.
  - `stale` or `excluded` without a run: REOPEN or EXCLUDED; session not written.
- **Drain.** `writer.run` raises `RuntimeError` after the drain closes the writer. If `walker.bot._stopping`: return the last committed rendering (or nothing) with content `RESTARTING`; else re-raise. Committed fights stay and none repeats.
- **Result block.** Fight and Heal all & fight keep the ARENA-12 block (revive text, raw HP; pins `test_arena_screens.py:392,407` unchanged). A chain shows one line per fight, in order: "Floor N <fight>: <enemy> · CP n · <Outcome> · n ticks · Candy +n <member>" (no Candy part when none), then the ARENA-12 ticket lines after a paying boss. Party lines show the order left. No level or IVs. Tickets every fifth floor cap a chain at 15 fights.
- **Help** (`content/help.md`, Arena): skip, Fight until hurt and stops, auto-order, threshold; update the pin `test_approved_text_verbatim`.

**Files.** Production: `pokewalker/bot/arena.py`. Docs: `content/help.md` (D16). Tests: `tests/test_arena_screens.py`, `tests/test_readme.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first (the `click` helper awaits `after_commit` like `Walker.route`):
- `test_until_hurt_one_writer_job_per_fight_lists_each_fight`
- `test_until_hurt_stop_notices_threshold_revive_ticket`
- `test_hurt_member_or_stale_screen_fights_nothing`
- `test_until_hurt_defeat_shows_defeat_screen_with_fights`
- `test_setting_change_elsewhere_stops_chain`
- `test_auto_order_chain_shows_order_left`
- `test_crash_mid_chain_keeps_finished_fights_repeats_none`
- `test_drain_mid_chain_returns_last_committed_screen`
- `test_fifteen_fight_chain_fits_embed_without_level_or_ivs`
- `test_chain_rechecks_expiry_and_exclusion_between_fights` (hour 18 or exclusion after a commit: no more receipts, rewards kept)
- `test_until_hurt_through_router_saves_run_revision` (`ArenaRouterTests`)
- `test_help_describes_skip_and_fight_until_hurt`

Pinned tests change only by the new action and button.

**Verify.** Focused, as ARENA-18. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_screens`, `readme`, `walker_router`; `git diff --check`.

**Stop if.** `walker.py` or `db/__init__.py` needs a change; a step needs a service change (ARENA-17 first); over 300 production lines.

**Do not touch.** `bot/walker.py`, `db/__init__.py`, `services/arena.py`, `domain/arena.py`.
