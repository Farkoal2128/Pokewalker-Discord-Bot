# EXG-4 — `services/ex_gift.py`: catalog, send, history

**Tier:** seam (item tables; persisted state; abuse controls)

**Read:** PLAN D1, D3, D5; SYNTHESIS EX-6..EX-10, EX-17, EX-27, R1, R4, R5, R13, R20; `bot/bag.py:22-26`.

**Goal.** New writer-transaction service; C3, C4 first.

- **`EX_ITEMS`** id → name: `time_gear_fragment` Time Gear Fragment, `shiny_patch` Shiny Patch, `golden_bottlecap` Golden Bottlecap, `ex_attack` EX-Attack, `ex_defense` EX-Defense, `arena_ex_voucher` Arena EX-Voucher.
- **`catalog(content)`** → `{category: [key]}` (D5), per call, from rate items minus `evolution_item`, rare pockets, `content['evolution_items']`, `rules.x_items.items`, `arena_ticket:<tier>`; deduplicated; 72 today. **`page(content, category, ex, n)`** → (keys, pages), 25 per page; `ex` lists `EX_ITEMS`. **`label(key, content)`**: EX names, `Bronze Arena Ticket`, else `bag.name`'s rule restated (services never import `bot`).
- **`target(conn, scope, guild_id, user_id)`** → `{'status': 'ok', 'servers', 'servers_with_recipients', 'recipients'}`, `unknown_server` or `no_profile` (user scope). `all` = every guild and profile; `server` = its profiles; `user` = its one profile. Restricted profiles count (R13).
- **`send(conn, *, send_id, owner_id, admin_guild_id, scope, guild_id, user_id, items, content, now)`** (D3), in order: owner excluded in the admin guild → `excluded`; an `ex_gifts` row for `send_id` → its stored result with `replayed: True` (another owner's → `invalid`); not 1-10 known keys → `invalid`; a `target` refusal; 0 recipients → `no_recipients`; else `INSERT ex_gifts` (no user ID) and `INSERT INTO ex_gift_recipients(gift_id,profile_id) SELECT ?,profile_id FROM profiles WHERE <scope>` → `{'status': 'sent', 'replayed': False}` plus the stored row fields. Duplicates stay separate slots. Log no IDs. Draft checks are the caller's, in the same job (EXG-6).
- **`history(conn, offset)`** → (10 newest, total); **`lookup(conn, send_id)`**.
- **C3:** "EX-Gift send". **C4:** "EX-Gift giftable catalog" (union, categories, pages, coverage test).

**Files.** Production: `pokewalker/services/ex_gift.py` (new). Tests: `tests/test_ex_gift.py` (new). Contracts: `contracts/persisted-state.md`, `contracts/balance-tables.md`.

**Accept.** New tests in `tests/test_ex_gift.py` pass, RED first: `test_catalog_covers_every_grantable_item` (weighted-row `item`s of every table, milestone bundles, leaderboard rewards, `starter_kit`, `purchase_stardust`; `evolution_item` expanded), `test_catalog_union_categories_and_25_option_pages` (IV items = `iv_items.ITEMS`), `test_ex_ids_match_schema_and_are_disjoint`, `test_send_all_snapshots_every_profile_once` (a user in two servers: two rows), `test_send_server_and_one_user_scopes`, `test_refusals_write_nothing` (unknown server, unenrolled user, user enrolled only elsewhere, zero recipients, 0 or 11 items, unknown key), `test_ten_slot_mixed_package_with_duplicates`, `test_same_send_id_sends_once_returns_stored_counts`, `test_excluded_owner_refused_before_lookup`, `test_profile_enrolled_after_send_gets_nothing`, `test_one_user_send_stores_no_user_id`, `test_owner_can_send_to_own_profile`, `test_history_newest_first_paged_and_lookup`.

**Benchmark** (evidence, not a test): an uncommitted script times one `scope='all'` `send` over 100,000 profiles in 1,000 guilds in `Writer.run`; the commit body records it. 100,000 is unverified (owner-run count: `sqlite3 <host db> "SELECT count(*) FROM profiles"`).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_gift`, `ex_gift_schema`, `balance_tables`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** The benchmark takes ≥1 s (a fifth of the 5 s probe, `bot/heartbeat.py:69`): report it, and the coordinator briefs a batching follow-up that keeps the snapshot. A balance table needs an edit; over 300 production lines.

**Do not touch.** Migrations, balance tables, `bot/**`, other services.
