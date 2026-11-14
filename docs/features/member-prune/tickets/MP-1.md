# MP-1 — `/walker-admin prune reason [confirm=false]`

**Tier:** seam

**Read:** README PR1–PR11; PLAN §2, §3.1, §3.2.

**Goal.** `WalkerAdmin.prune` beside `reset`. Order: §3.2 contract paragraphs, RED tests, command, help line.

**Flow** (`admin_channels.py` only):
1. `deadline = self.bot.clock() + PRUNE_BUDGET_SECONDS` (`13 * 60`, monotonic). Defer privately, `authorize`, strip reason; blank: "A reason is required."
2. One writer job: `check_actor`, then this guild's `profiles.user_id` in fixed order. Start after `self.prune_after[guild]` (group dict) if set, and wrap.
3. Per user, at deadline: stop, saving the last checked ID (keep the old cursor if none checked). Else `_within(guild.fetch_member(int(uid)), remaining)` (D5, never cancels): member kept; `NotFound` code 10007 departed; None time stop; any other `Exception` stops.
4. Departed and `confirm`:
   - `gate(conn)`: `check_actor`, then raise module-private `_Gone(Exception)` if `profiles.get_profile` returns None.
   - Before the run's first deletion only: one writer job runs `gate`, then the guild-target audit insert used by `sharing` (action `prune`). `_Gone` skips the user; the audit stays unwritten.
   - `deletion.run_marker` as `reset` calls it, with `gate`, `kind="delete"`, actor, reason, and a `reactions` wrapper running `remove_own` via `_within` (D5). `_Gone` skips; `_Refused` stops; else propagates.
5. One `self.reply` with the D10 text.

**Help.** Add the PLAN §3.2 line after the `reset` line of `content/help.md`; keep its single backtick span.

**Tests.** New `tests/test_admin_prune.py`: copy the `AdminResetSharingTests` fixture; add `bot.clock`, three users, AsyncMock `guild.fetch_member`. Unknown Member is `discord.NotFound(<fake response>, {"code": 10007})` (PLAN §2).
- `test_shape_and_entry_refusals`: options `reason`, `confirm=False`; no permission, DM, excluded actor or blank reason: no member check, marker or audit (PR1).
- `test_defer_precedes_writer_and_member_checks` (PR4).
- `test_dry_run_counts_and_writes_nothing` (PR3).
- `test_confirm_deletes_only_departed_with_delete_markers`: kind, actor, stripped reason, profile ID; member kept; `remove_own` called; guild 999 untouched (PR5, PR6, PR9).
- `test_confirm_writes_one_guild_prune_audit`: two deletions, one row, no `reset` audit (PR7).
- `test_no_departed_writes_no_audit_or_marker` (PR7).
- `test_audit_survives_crash_between_marker_and_commit`: `deletion.apply` raises, `deletion.append_void` is a no-op; after `replay_markers` the profile is gone and one `prune` row exists (D3).
- `test_other_outcomes_stop_run_and_report_progress`: NotFound 10004/codeless, Forbidden, HTTP 500, `RateLimited(1.0)`, `OSError`; next user unchecked (PR2, PR9).
- `test_rerun_and_replay_delete_nothing_twice`: no new marker or audit; a fresh enrollment survives replay (PR8, PR11).
- `test_profile_gone_before_writer_job_is_skipped` (PR8, D6).
- `test_actor_excluded_mid_run_stops_before_next_marker` (PR1).
- `test_time_budget_stops_reports_and_next_run_resumes` (PR10, D7); zero-check stop keeps cursor.
- `test_stalled_fetch_and_cleanup_are_bounded`: reply by deadline, tasks not cancelled, late fetch ignored, deletion counted (D5).
- `test_prune_keeps_restrictions_opt_out_and_prior_audit` (PR11).
- `tests/test_readme.py`: count pin 25 to 26; new help.md sha256 (LF bytes).

**Files:** pokewalker/bot/admin_channels.py, content/help.md, tests/test_admin_prune.py, tests/test_readme.py, contracts/discord-commands.md, contracts/persisted-state.md

**Accept.** Every test above passes; PLAN §3.3 A, B and C exit 0; RED for A and B is recorded before the command exists; only the listed files change.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=PLAN §3.3 A, B, C; receipt=Tests-Focused on the staged tree; boundary=feature final (G-F)`.

**Stop if.** Any change under `pokewalker/services/`, `pokewalker/db/` or `bot/client.py`; a third production file; the help line fails the admin-page test beyond the two pins.
