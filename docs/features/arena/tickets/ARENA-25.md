# ARENA-25 — `arena.json` `rules.x_items` and the manifest hash

**Tier:** seam (balance tables, C4)

**Read:** PLAN D20; AR-42, AR-43, AR-45, AR-46; ARENA-21; `contracts/balance-tables.md` "Arena leaderboard rules (version 2)"; `tests/test_balance_tables.py` `test_arena_rules_match_approved_requirements`.

**Goal.** The price, duration and multiplier of both X items live in the Arena table. Contract, tests first.

- **Payload:** `rules.x_items`, after `leaderboard`:

| Key | Value |
|---|---|
| `fights` | 3: the fights one use lasts |
| `multiplier` | 2: the stat factor while a counter is above 0 |
| `items` | `{"x_attack": {"stat": "attack", "stardust": 300}, "x_defense": {"stat": "defense", "stardust": 300}}` |

  - An `items` key is the `inventory` item id. `stat` is the `battle.Combatant` field the item multiplies. `stardust` is the price of one.
  - Neither id gets a `capacities.json` rare pocket (so it counts in `bag_units`) or a `conversion_rates.json` rate or purchase price (no Convert, AR-45). Those two tables do not change.
- **Envelope:** `version` 3; `source` gains `section 6.4 (owner ruling 2026-11-14)`, and its pinned `section 6.3` text stays; `checked` stays `2026-11-13`.
- **Manifest:** replace the `arena.json` hash in `balance_sha256` (`content/manifest.json`). Both files are LF. `artifact_sha256` does not change.
- **Report:** regenerate `docs/features/pokewalker-bot/economy-report.md` as ARENA-21 did: `python scripts/simulate_economy.py --profile regular`. Only its manifest hash line and `arena.json: v3` should move. Keep its CRLF form.
- **C4:** append "Arena X-item rules (version 3)": keys, units and the consumers (`buy_x` and `use_x` in ARENA-26, `fight` in ARENA-27, the screens in ARENA-28). State that the economy report does not model this Stardust sink, and that AR-46's figures come from an uncommitted scratch simulation.

**Files.** Production: `content/balance/arena.json`, `content/manifest.json`. Generated: `docs/features/pokewalker-bot/economy-report.md`. Tests: `tests/test_balance_tables.py`. Contract: `contracts/balance-tables.md`.

**Accept.** In `tests/test_balance_tables.py`, RED first:
- `test_arena_rules_match_approved_requirements` changes: the exact payload with `x_items`, `version` 3, `section 6.4` in `source`
- `test_every_table_has_source_checked_version` changes: `"arena": 3`
- `test_arena_x_items_are_bag_items_with_combatant_stats` (new: `fights`, `multiplier` and every `stardust` are positive ints; the `stat` values are `attack` and `defense`, each once, both `Combatant` fields; no item id is a `rare_pockets`, `stardust_per_unit` or `purchase_stardust` key)

`tests/test_content_integrity.py` `test_balance_hashes_match` passes and `artifact_sha256` is unchanged. The committed report equals the CLI output: the same command with `--out <tmp>`, then `git diff --no-index --exit-code <tmp> <report>` exits 0.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above + report regeneration; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `balance_tables`, `content_integrity`, `arena_domain`, `arena`, `economy_arena`, `simulate_economy`; the regeneration check above; `git -c core.whitespace=cr-at-eol diff --cached --check` (`test_balance_tables.py`, the contract and the report are committed with CRLF: do not convert them).

**Stop if.** The artifact hash or `content/artifact/content.json` would change; another report line moves (name it, tune nothing; the report was not re-run when this ticket was written); a consumer rejects the new key; a line-ending guard rejects the report (as ARENA-19: renormalize that one file to LF in this commit and say so).

**Do not touch.** Other balance tables; `content/build/**`, `content/artifact/**`; `pokewalker/**`; `scripts/**`; other `docs/features/pokewalker-bot/` files.
