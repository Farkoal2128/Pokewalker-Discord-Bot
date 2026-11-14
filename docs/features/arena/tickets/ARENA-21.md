# ARENA-21 — `arena.json` `rules.leaderboard` and the manifest hash

**Tier:** seam (balance tables, C4)

**Read:** PLAN D18; AR-38, AR-40, AR-41; ARENA-2, 19; `contracts/balance-tables.md` "Common envelope and loader", "Arena table"; `tests/test_balance_tables.py` `test_arena_rules_match_approved_requirements`.

**Goal.** Leaderboard minimum floor, board size and rewards live in the Arena table. Contract, tests first.

- **Payload:** `rules.leaderboard`, after `skip`:

| Key | Value |
|---|---|
| `min_floor` | 10: the lowest month score that can win a reward |
| `shown` | 10: rows on the screen |
| `rewards` | by place: `["master_ball", "shiny_lure", "world_legendary_ticket"]`, `["master_ball", "shiny_lure"]`, `["master_ball"]` |

  - One of each listed item. The number of paid places is the length of `rewards`: 3, and nothing below (AR-41).
  - The item is `shiny_lure`, the consumable. The Shiny Charm is not a reward (owner correction, AR-38).
  - All three items are `capacities.json` `rare_pockets` keys, cap 1, so the existing claim holds a reward back while its pocket is full.
- **Envelope:** `version` 2 (the loader rule: a rule change needs a version change); `source` also names section 6.3 (owner ruling 2026-11-14); `checked` stays `2026-11-13`, because the species references were not rechecked.
- **Manifest:** replace the `arena.json` hash in `balance_sha256` (`content/manifest.json`). Both files are LF (`.gitattributes`). `artifact_sha256` does not change.
- **Report:** regenerate `docs/features/pokewalker-bot/economy-report.md` as ARENA-19 did: `python scripts/simulate_economy.py --profile regular`. Its Inputs block prints the manifest hash and `arena.json: v2`. At 8e6a7bf the committed file equals the CLI output, so only those two lines move. Keep its CRLF form.
- **C4:** append "Arena leaderboard rules (version 2)": keys, units, the paid-place rule and the consumers (`settle` in ARENA-22, the screen in ARENA-23). State that the economy report does not model these rewards: at most 3 Master Balls, 2 Shiny Lures and 1 World Legendary Ticket per server and month.

**Files.** Production: `content/balance/arena.json`, `content/manifest.json`. Generated: `docs/features/pokewalker-bot/economy-report.md`. Tests: `tests/test_balance_tables.py`. Contract: `contracts/balance-tables.md`.

**Accept.** In `tests/test_balance_tables.py`, RED first:
- `test_arena_rules_match_approved_requirements` changes: the exact payload with `leaderboard`, `version` 2, section 6.3 in `source`
- `test_every_table_has_source_checked_version` changes: `"arena": 2` in `versions`, and an `arena` branch (`checked` 2026-11-13) before the generic 2026-11-05 check
- `test_arena_leaderboard_rewards_are_rare_pocket_items` (new: items are `rare_pockets` keys, none twice in a place; `min_floor`, `shown` positive ints)

`tests/test_content_integrity.py` `test_balance_hashes_match` passes and `artifact_sha256` is unchanged. The committed report equals the CLI output: the same command with `--out <tmp>`, then `git diff --no-index --exit-code <tmp> <report>` exits 0, and the report diff is those two lines.

**Verify.** Focused, plus report regeneration (`Tests-Focused` on the staged tree; boundary G-F). Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `balance_tables`, `content_integrity`, `arena_domain`, `economy_arena`, `simulate_economy`; the regeneration check above; `git -c core.whitespace=cr-at-eol diff --cached --check` (`test_balance_tables.py`, the contract and the report are committed with CRLF: do not convert them).

**Stop if.** The artifact hash or `content/artifact/content.json` would change; another report line moves (name it, tune nothing); a consumer rejects the new key; a line-ending guard rejects the report (as ARENA-19: renormalize that one file to LF in this commit and say so).

**Do not touch.** Other balance tables; `content/build/**`, `content/artifact/**`; `pokewalker/**`; `scripts/**`; other `docs/features/pokewalker-bot/` files.
