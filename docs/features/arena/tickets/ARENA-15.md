# ARENA-15 — go live: registration, home button, help, deletion and reset coverage

**Tier:** seam (interaction responses; persisted state deletion)

**Read:** PLAN D16; REQUIREMENTS AR-4b, §10 deletion and UI rows; ARENA-4, ARENA-8..14; `bot/walker.py` `Walker.__init__` (:71-87); `bot/screens.py` `home` (:34-35); `services/deletion.py` `apply` (:125), `replay_markers` (:158); `tests/test_deletion.py:256-271`; `tests/test_readme.py:17-48`.

**Goal.** Make the Arena reachable, and first prove that deleting or resetting a profile removes every Arena trace. C5 first. Deletion tests come before the two production one-liners.

- **Deletion and reset coverage** (tests only; `services/deletion.py` relies on the cascade and must not change):
  - `tests/test_deletion.py`: `populate` gains a live run, tickets, a fight receipt with an `arena_candy` ledger line, a redeem receipt and `arena:` inbox rows, made through the real services. The cascade test's table list (:260-262) gains `arena_runs` and `arena_tickets`.
  - Replay after restore: a database from before the deletion marker, replayed with `replay_markers`, ends with no Arena rows or receipts for that profile.
  - `tests/test_receipt_owner.py`: every Arena receipt action (`arena_start`, `arena_heal`, `arena_fight`, `arena_redeem`) stores `profile_id`.
  - `tests/test_admin_reset_sharing.py`: a reset removes runs and tickets; re-enrolling starts at best floor 0 with no cooldown or tickets.
- **Registration** (`bot/walker.py`): import `arena` with the other bot modules (:16-19); add `self.handlers.update(arena.handlers(self))` to the block at :76-87.
- **Home button** (`bot/screens.py:34`): add `('Arena', 'arena')` after Gyms. It is enabled exactly when the handler is registered (:35). Update the pinned label list in `tests/test_screens.py:33`; the view stays within 5 rows.
- **Help** (`content/help.md`, LF): a player section (team of 3, three fights a floor, carried HP, berry healing, the 18-hour run and cooldown, tickets, knockout Candy, and the gym, trade and research blocks) and an admin line for `/walker-admin arena on|off reason`. Describe only what Phase 1 built. Update the whole-file hash pinned in `tests/test_readme.py` (:42-44), keep every page within its size limits, and leave page one unchanged (`PAGE_ONE_SHA256` :18).
- **C5:** append the home button line.

**Files.** Production: `pokewalker/bot/walker.py`, `pokewalker/bot/screens.py`; help text `content/help.md` (counted as docs, D16). Tests: `tests/test_deletion.py`, `tests/test_receipt_owner.py`, `tests/test_admin_reset_sharing.py`, `tests/test_screens.py`, `tests/test_readme.py`, `tests/test_arena_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first:
- `test_delete_removes_arena_runs_tickets_receipts_ledger_and_inbox_rows` (`test_deletion`)
- `test_replay_after_restore_removes_arena_rows_and_receipts` (`test_deletion`)
- `test_every_arena_receipt_action_carries_profile_id` (`test_receipt_owner`)
- `test_reset_clears_arena_state_and_reenroll_starts_clean` (`test_admin_reset_sharing`)
- `test_home_has_arena_button_enabled_only_when_registered` (`test_screens`)
- `test_home_button_opens_arena_through_router`, `test_every_arena_action_is_registered` (`test_arena_screens`)
- `test_help_describes_arena_and_admin_switch_within_page_limits` (`test_readme`)

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `deletion`, `receipt_owner`, `admin_reset_sharing`, `screens`, `readme`, `arena_screens`, `walker_router`; `git diff --check`.

**Stop if.** Any Arena row, receipt, ledger line or inbox row survives a deletion (fix the producing service row; never edit `services/deletion.py` or weaken the test); the home view needs a sixth row; help page one would change.

**Do not touch.** `services/deletion.py`, `services/marker_log.py`, `bot/client.py`.
