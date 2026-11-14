# ARENA-22 — `settle`, the ranking read and the home call

**Tier:** seam (persisted player state; interaction responses)

**Read:** PLAN D18; AR-37..AR-41; ARENA-20, 21; `services/arena.py` `redeem` (inbox insert); `services/milestones.py` `claim`; `bot/walker.py` `home`.

**Goal.** A finished month pays its top places once, lazily; one read feeds the screen; home settles. C3, C5 first.

- **Ranking** (one private helper for both): a guild's score rows of one month joined to `profiles`, by `floor` descending, then `reached_at`, `profiles.created_at`, `profile_id` ascending. Profiles `excluded` in `restrictions` (guild, user) are left out; paused stay (AR-40).
- **`settle(conn, guild_id, now)`**; `RuntimeError` outside a writer transaction, as `state`. For each month before `month_key(now)` with score rows in this guild and no `arena_months` row, oldest first:
  1. Rank it. Rank `n` is place `n`, up to `len(rewards)`, paid only at `min_floor` or higher. An unpaid place stays empty: nobody moves up.
  2. Per paid place: one `inbox_items` row per item (`milestone_id` `arena_month:<YYYY-MM>:<place>`, `resource` `'item'`, `resource_id` the item, `remaining` 1, `created_at` `now`) and one `arena_month_places` row.
  3. Insert the `arena_months` row, also when nobody was paid.
  - Returns the months settled. A repeat call writes nothing: the `arena_months` row is the guard. No receipt, no ledger line (the claim writes one). It reads neither `arena_enabled` nor a session.
- **`leaderboard(conn, guild_id, profile_id, now)`**, read only → `{'month', 'rows', 'viewer', 'reset_at', 'last_month', 'last'}`. `rows`: the top `shown`, each `{'place', 'user_id', 'floor'}`. `viewer`: `{'place', 'floor'}` when the profile ranks below them, else `None`. `reset_at`: the next month's 00:00 UTC epoch. `last`: last month's `arena_month_places` rows in the same shape, by place; a deleted or now-excluded winner leaves a gap (paused stays).
- **`Walker.home`** (`bot/walker.py`): after the profile check, before the home state is built, `await settle(conn, session['guild_id'], self.clock())`, so `Rewards waiting` and the Inbox button count a fresh payout. Import the service under another name (`arena` is the bot module there). Onboarding and a recovered terminal return earlier, unsettled.
- **C3:** append "Arena monthly settlement (ARENA-22)". **C5:** the home call site.

**Files.** Production: `pokewalker/services/arena.py`, `pokewalker/bot/walker.py`. Tests: `tests/test_arena.py`, `tests/test_arena_screens.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena.py`:
- `test_settle_pays_three_places_and_records_them`
- `test_settle_repeat_or_same_month_writes_nothing`
- `test_ties_rank_by_time_created_at_profile_id`
- `test_below_floor_10_unpaid_nobody_moves_up`
- `test_unsettled_months_paid_oldest_first`
- `test_deletion_before_settlement_moves_others_up_after_leaves_gap`
- `test_settle_ignores_arena_off_pause_other_guilds`
- `test_excluded_player_unranked_next_moves_up`
- `test_claim_holds_reward_while_rare_pocket_full`
- `test_leaderboard_rows_viewer_reset_and_last_month` (incl. winner excluded after payout)
- `test_settle_requires_writer_transaction`

In `tests/test_arena_screens.py` `ArenaRouterTests`:
- `test_walker_open_settles_and_enables_inbox_also_arena_off`

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena`, `arena_screens`, `walker_router`, `milestones`, `deletion`; `git -c core.whitespace=cr-at-eol diff --cached --check` (keep CR line ends in `bot/walker.py` and `contracts/persisted-state.md`).

**Stop if.** `settle` needs a schema change (ARENA-20 first), a `claim` change or a receipt; the home needs more than one call; over 300 production lines.

**Do not touch.** `services/milestones.py`, `services/deletion.py`, `bot/screens.py`, `bot/arena.py` and `bot/milestones.py` (ARENA-23), `db/**`, `arena.json`.
