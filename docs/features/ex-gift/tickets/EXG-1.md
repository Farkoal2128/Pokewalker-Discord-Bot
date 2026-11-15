# EXG-1 — `arena.json` `rules.ex_items` and the manifest hash

**Tier:** seam (item tables, C4)

**Read:** PLAN D5, D7; SYNTHESIS EX-14..EX-16, EX-26, R9, R12; `tests/test_balance_tables.py` `test_arena_rules_match_approved_requirements` (:79), `test_every_table_has_source_checked_version` (:419); `contracts/balance-tables.md` "Arena X-item rules (version 3)"; `docs/features/arena/tickets/ARENA-25.md` (same shape).

**Goal.** The voucher floor and the run-long EX boosts live in the Arena table. Contract and tests first.

- **Payload** `rules.ex_items`, after `x_items`:

| Key | Value |
|---|---|
| `voucher_floor` | 80: the voucher pays floors 1..80 and starts the run on 81 (EX-26) |
| `items` | `{"ex_attack": {"stat": "attack", "x_item": "x_attack"}, "ex_defense": {"stat": "defense", "x_item": "x_defense"}}` |

  - An `items` key is an EX-item id. `stat` is the `battle.Combatant` field doubled for a whole run; `x_item` is the regular X-item it replaces and blocks (R9). The factor is `x_items.multiplier` (EX-14: "the same ×2"), not a second number.
- **Envelope:** `version` 4 → 5; `source` appends `docs/features/ex-gift/SYNTHESIS.md EX-14..EX-16, EX-26 (owner 2026-11-15)`, keeping every pinned phrase; `checked` stays `2026-11-14`.
- **Manifest:** replace the `arena.json` hash in `content/manifest.json` `balance_sha256`. Both files are LF; `artifact_sha256` does not change.
- **Report:** regenerate `docs/features/pokewalker-bot/economy-report.md` with `python scripts/simulate_economy.py --profile regular`. Only its manifest hash line and `arena.json: v4` → `v5` move. Keep its CRLF.
- **C4:** append "Arena EX-item rules (version 5)": keys, units, consumers (EXG-14, EXG-16 services; EXG-15, EXG-17, EXG-19 screens). EX-items are gift-only with no Stardust price, so the economy report does not model them.

**Files.** Production: `content/balance/arena.json`, `content/manifest.json`. Generated: `docs/features/pokewalker-bot/economy-report.md`. Tests: `tests/test_balance_tables.py`. Contract: `contracts/balance-tables.md`.

**Accept.** In `tests/test_balance_tables.py`, RED first:
- `test_arena_rules_match_approved_requirements` changes: exact payload with `ex_items`, `version` 5, the new source phrase
- `test_every_table_has_source_checked_version` changes: `"arena": 5`
- `test_arena_ex_items_double_their_x_item_stat` (new): each `x_item` is an `x_items.items` key with the same `stat`; `attack` and `defense` once each; `voucher_floor` is a positive int, `domain.ticket_for(voucher_floor, rules)` is not None, and `domain.max_skip(voucher_floor, rules) == rules['skip']['max']` (EX-16: the voucher unlocks the full skip)

`tests/test_content_integrity.py` `test_balance_hashes_match` passes with `artifact_sha256` unchanged. The committed report equals the CLI output: the same command with `--out <tmp>`, then `git diff --no-index --exit-code <tmp> <report>` exits 0.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `balance_tables`, `content_integrity`, `arena_domain`, `arena`, `economy_arena`, `simulate_economy`; the regeneration check; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** The artifact hash would change; another report line moves (name it, tune nothing); a consumer rejects the new key; a line-ending guard rejects the report.

**Do not touch.** Other balance tables; `content/build/**`, `content/artifact/**`; `pokewalker/**`; `scripts/**`; other `docs/features/pokewalker-bot/` files.
