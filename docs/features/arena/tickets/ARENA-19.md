# ARENA-19 — economy model and report: Arena ticket income

**Tier:** seam (balance tables, C4)

**Read:** PLAN D19; REQUIREMENTS §2 economy values, AR-26, AR-32, AR-34, §6.1, §8; ARENA-17; `scripts/economy/model.py` `run_scenario` (`gym_income`); `scripts/simulate_economy.py` `render_report`.

**Goal.** The offline report states what Arena tickets pay, from the live tables, with and without a skip. Analytic, like the gym section: no fight is simulated and no table changes. C4 first.

- **`arena_income(balances)`** in `scripts/economy/model.py`; `run_scenario` returns it as `"arena_income"`:
  - `income_roll_value`: the weighted mean of the `gym_income_table` rows in Stardust (`conversion_rates` `stardust_per_unit`; a `stardust` row counts its quantity). `survivor_roll_value`: the same over `survivor_table`, plus `stardust_flat`. `unpriced`: items with no rate; they count 0 and are named.
  - `runs_per_day` = `86400 / rules.cooldown_seconds`.
  - `runs`: one dict per `(skip, floor cleared)` in `ARENA_RUNS = ((0, 10), (0, 20), (0, 30), (0, 40), (40, 40), (40, 60), (40, 80), (40, 100))`; the floors are REQUIREMENTS §6.1/§8 reference rows: assumptions, not predictions. Keys: `skip`, `floor`, `fights` (`3 * (floor - skip)`), `tickets` (`skip_tickets(floor)`, so no first-clear bonus), `at_start` (`skip_tickets(skip)`), `encounters_max` (`fill` = `encounter_queue`), `stardust`, `income_rolls`, `survivor_rolls`, `stardust_equivalent` (Stardust plus rolls at both values), `at_start_stardust_equivalent`.
  - A skip changes which floors are fought, not what floors `1..floor` pay. `(40, 40)` is start-and-back-out.
- **Report** (`render_report`): "## Arena ticket income" between the gym item table and "## Checks": the assumptions, both roll values, the unpriced items, then one row per run with every key above plus Stardust-equivalent per day. No PASS/FAIL line: no approved expectation exists for Arena income.
- **Regenerate** `docs/features/pokewalker-bot/economy-report.md`: `python scripts/simulate_economy.py --profile regular`. The committed file dates from 7a5f813, so the diff also carries later table drift (versions, manifest hash, totals); at 3ab843a no PASS/FAIL verdict changes. Name the moved non-Arena sections in the commit body. Keep its CRLF form (`git ls-files --eol`).
- **C4:** append the `arena_income` fields, the report section and its assumptions.

**Files.** Production: `scripts/economy/model.py`, `scripts/simulate_economy.py`. Generated: `docs/features/pokewalker-bot/economy-report.md`. Tests: `tests/test_economy_arena.py` (new; fixtures as `test_economy_d47.py`). Contract: `contracts/balance-tables.md`.

**Accept.** New tests pass, RED first:
- `test_arena_income_reproduces_requirement_payout_rows` (§6.1 rows 40, 80, 100)
- `test_skip_rows_split_start_paid_tickets_and_fights` (`(40, 40)`: 0 fights, all at start; `(40, 80)`: 120 fights)
- `test_roll_values_follow_live_tables_and_name_unpriced_items`
- `test_stardust_equivalent_and_daily_rate_use_cooldown`
- `test_report_arena_section_states_assumptions_and_lists_every_run`
- `test_existing_report_sections_unchanged_by_arena_section`

The committed report equals the CLI output: the same command with `--out <tmp>`, then `git diff --no-index --exit-code <tmp> <report>` exits 0.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above + report regeneration; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `economy_arena`, `economy_d47`, `economy_model`, `simulate_economy`; the regeneration check above; `git diff --check`.

**Stop if.** A PASS/FAIL verdict flips (fix the row, tune nothing); a balance table needs an edit; the model would have to simulate fights; a line-ending guard rejects the report (renormalize that file to LF in this commit and say so).

**Do not touch.** `content/balance/**`, `content/manifest.json`, `pokewalker/**`, other `docs/features/pokewalker-bot/` files.
