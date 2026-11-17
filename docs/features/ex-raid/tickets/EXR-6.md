# EXR-6 — announcements: EX title, failure isolation, bot-owned fan-out

**Tier:** seam (gateway messages; persisted state)

**Read:** PLAN D6; SYNTHESIS R8, R9; EXR-4; `services/raids.py:198-244`; `bot/client.py:125-133, :173-185, :220-246`; C5 "M8.2a"; `tests/test_raids.py:743-903`.

**Goal.** EX spawns announce as "EX-Raid", one failing server never stops the others, and one send's announcements run as a task the bot owns. C5 first.

- **`announce`** (:216-229): the title is `EX-Raid: <name>` when the claimed row's `kind` is `ex`, else `World Legendary: <name>`; the description stays "<name> is here! Despawns <UTC>. Join with /raid." A failed post (:228) logs one warning naming only the spawn ID and returns; the row stays `attempted`. Claim, nonce, mentions and the `sent` write are unchanged.
- **`resume_pending(bot, ex_raid_id=None)`** (:238-244): the pending query adds `AND (? IS NULL OR ex_raid_id=?)` and `ORDER BY spawned_at, spawn_id`. Each `announce` call is wrapped: an `Exception` (a failed claim or `sent` write) is logged and the loop goes on; `asyncio.CancelledError` propagates. With an ID this is the send's fan-out; without one it is today's startup recovery.
- **`WalkerBot.announce_ex_raid(ex_raid_id=None)`**: synchronous, so an `after_commit` observer may call it. It creates the task `raids.resume_pending(self, ex_raid_id)`, keeps it in `self._raid_fanouts` until done, returns it. `on_ready` (:185) calls it with no ID and awaits that task, so startup recovery is tracked too. `_drain` cancels and awaits these tasks beside `_gym_sweep` (:242-246), before the writer closes.
- **While stopping** (`_stopping`, set at :211): no task, returns None; the rows stay `pending` for the next startup.
- At-most-once is kept: `attempted` rows are never retried; rows that expired are never announced; an unannounced spawn stays joinable through `/raid`.
- **C5:** amend "M8.2a": the EX title, per-row isolation in `resume_pending`, the fan-out task and its shutdown rule. The accepted nonce-window risk is unchanged.

**Files.** Production: `pokewalker/services/raids.py`, `pokewalker/bot/client.py`. Tests: `tests/test_ex_raid.py`, `tests/test_client_lifecycle.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_raid.py`:
- `test_ex_announcement_titled_ex_raid_for_a_legendary_boss`
- `test_world_legendary_announcement_title_unchanged`
- `test_fanout_announces_only_that_sends_pending_live_rows_in_order`
- `test_failed_post_logged_stays_attempted_later_servers_announced`
- `test_failed_sent_write_logged_later_servers_announced`
- `test_resume_pending_isolates_a_failing_row`
- `test_attempted_rows_never_retried_by_fanout_or_restart`
- `test_restart_skips_pending_rows_whose_spawn_expired`
- `test_unannounced_spawn_stays_joinable`

In `tests/test_client_lifecycle.py`:
- `test_announce_ex_raid_returns_a_bot_owned_task_without_awaiting`
- `test_drain_cancels_a_fanout_blocked_on_a_slow_post` (later rows stay `pending`; the writer still closes)
- `test_commit_during_drain_schedules_no_task_rows_resume_at_startup` (`Writer.run(ex_commit, after_commit=...)` lands mid-drain; no task survives)
- `test_drain_cancels_slow_startup_recovery_later_rows_stay_pending`

`tests/test_raids.py`, `tests/test_admin_force_raid.py`, `tests/test_heartbeat.py` and `tests/test_share.py` pass unchanged. No command or button is added: no manifest, subcommand-set or schema pin moves.

**Verify.** Focused (staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid`, `raids`, `admin_force_raid`, `client_lifecycle`, `heartbeat`, `share`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** An existing announce test must change (name it); the drain order or its 20 s bound must change; a log line would carry message text, an exception message or a user ID; over 300 production lines.

**Do not touch.** `bot/bag.py:453`, `bot/admin_channels.py:463` `bot/heartbeat.py`, `db/**`.
