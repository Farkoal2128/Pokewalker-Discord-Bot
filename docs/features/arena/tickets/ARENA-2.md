# ARENA-2 — balance table `content/balance/arena.json`

**Tier:** seam (balance tables, C4)

**Read:** PLAN D8; REQUIREMENTS §5, §6, AR-14a, AR-34; `contracts/balance-tables.md` "Common envelope and loader"; `tests/test_balance_tables.py`.

**Goal.** One authored table holds every Arena tuning number. Contract and tests first.

- **Envelope:** `source` cites `docs/features/arena/REQUIREMENTS.md` (owner approval 2026-11-13) and names the published reference used for the Ultra Beast and Paradox species lists; `checked` is the ISO date those lists were checked; `version` 1.
- **Payload `rules`:**

| Key | Value |
|---|---|
| `run_seconds`, `cooldown_seconds` | 64800, 64800 |
| `team_size` | 3 |
| `heal_items` | `razz_berry`, `pinap_berry` |
| `level_cap` | 40 |
| `iv_ranges` | `entry` [0,5], `middle` [5,10], `boss` [10,15] |
| `late` | `after_floor` 40, `step_floors` 5, `iv_steps_max` 15, `hp_step_x10` 1, `hp_cap_x10` 20, `uncapped_after_floor` 115, `uncapped_step_x10` 1 |
| `bst` | `base` 300, `span` 420, `span_floors` 31, `full` 720, `full_floor` 32, `boss_pct` 115, `decade_boss_pct` 150 |
| `special` | `ultra_beast_species` 793-799, 803-806; `paradox_species` 984-995, 1005, 1006, 1009, 1010, 1020-1023; `boss_chance_pct` 5; `decade_boss_chance_pct` 25 |
| `candy` | `per_knockout` 1, `special_boss_only` true |
| `tickets.tiers` | bronze / silver / gold / platinum / diamond: `encounters` 1 / 2 / `"fill"` / `"fill"` / `"fill"`; `stardust` 100 / 200 / 400 / 1000 / 3000; `income_rolls` 0 / 2 / 4 / 8 / 24; `survivor_rolls` 0 / 0 / 0 / 1 / 3 |
| `tickets.schedule` | bronze `floors` [5,15]; silver `floors` [10,20,30,40]; gold `from` 25 `every` 10; platinum `floors` [50,60,70]; diamond `from` 80 `every` 10 |
| `tickets.first_clear_tiers` | silver, gold, platinum, diamond |
| `skip` | `divisor` 2, `max` 40 (read in Phase 2) |

- Percentages are integers so the caps use integer math (D8).
- **Manifest:** add `"arena.json": <sha256 of the file bytes>` to `balance_sha256` in `content/manifest.json`, keys sorted (producer: `content/build/emit.py` `digest` :25, `balance_paths` :168, :234). Both files are LF (`.gitattributes`).
- **C4:** append "Arena table (`arena.json`)" with the payload and units above.

**Files.** Production: `content/balance/arena.json`, `content/manifest.json`. Tests: `tests/test_balance_tables.py`. Contract: `contracts/balance-tables.md`.

**Accept.** In `tests/test_balance_tables.py`, `TABLES` (:19) includes `"arena"` and these new tests pass, RED first:
- `test_arena_rules_match_approved_requirements` (exact payload)
- `test_arena_ultra_beasts_equal_milestone_first_catch_list` (same species as `milestones.json` `ultra_beast_first_catches`)
- `test_arena_special_identities_total_128_regular_966` (against `content/artifact/content.json`)
- `test_arena_schedule_gives_each_floor_at_most_one_known_tier` (floors 1-200)

`tests/test_content_integrity.py` `test_balance_hashes_match` passes and `artifact_sha256` is unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_balance_tables.py"`, `-p "test_content_integrity.py"`, `git diff --check`.

**Stop if.** The artifact hash or `content/artifact/content.json` would change; the special count is not 128; no published reference can be cited for the two species lists (report it, do not guess IDs).

**Do not touch.** Other balance tables, `content/build/**`, `content/artifact/**`.
