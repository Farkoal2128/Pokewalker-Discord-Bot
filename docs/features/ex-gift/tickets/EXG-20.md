# EXG-20 — profile deletion discards drafts targeting it

**Tier:** seam (persisted player state; interactions)

**Read:** PLAN D9; SYNTHESIS R16, R20, §6 (deleted one-user recipient); EXG-5 (`discard`, `attach`), EXG-6 (send job rechecks); `services/deletion.py` `run_marker` (:75), `apply` (:125-131); `git grep -n "run_marker(" -- pokewalker` (four callers, none edited).

**Goal.** Deleting a profile, by delete, opt-out, reset or member prune, leaves no live draft naming that user, and a Confirm racing the deletion cannot send to a re-enrolled profile. C3 and C5 first.

- **`services/deletion.py`:** module-level `_listeners = weakref.WeakValueDictionary()` and `listen(obj)`: `_listeners[id(obj)] = obj` (a dict subclass is weak-referenceable but unhashable, so no `WeakSet`). `apply` calls `obj.profile_deleted(guild_id, user_id)` for each `list(_listeners.values())` after each profile delete (:129-131), inside the job. An early discard on rollback is harmless; replay at startup finds no drafts.
- **`bot/admin_gift.py`:** `attach` makes `gift_drafts` a `Drafts(dict)` and calls `deletion.listen(gift_drafts)`. `Drafts.profile_deleted(guild_id, user_id)` calls `discard` (EXG-5) on every draft whose `(guild_id, user_id)` matches, so its View stops and its IDs clear; a `sending` draft's job then finds it unregistered and sends nothing (EXG-6).
- **C3:** M4.1b notes the listener (no persisted change). **C5:** drafts end when their target profile is deleted.

**Files.** Production: `pokewalker/services/deletion.py`, `pokewalker/bot/admin_gift.py`. Tests: `tests/test_deletion.py`, `tests/test_admin_gift.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_deletion.py`:
- `test_listen_registers_dict_subclass_weakly` (registration does not raise; the entry goes after the object is collected)
- `test_profile_delete_notifies_listeners_with_guild_and_user`
- `test_replay_calls_listeners_harmlessly`

In `tests/test_admin_gift.py`:
- `test_new_bot_registers_drafts_without_error` (startup through `attach`)
- `test_delete_discards_matching_one_user_drafts_only`
- `test_delete_and_reenrol_while_confirm_waits_sends_nothing` (Confirm held in its exclusion check; the new profile gets no recipient row)
- `test_retained_controls_after_delete_change_nothing`
- `test_deleted_recipient_id_absent_owner_id_kept` (no EX-Gift table, receipt, ledger or captured log line holds the user ID; `ex_gifts.owner_id` stays)

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `deletion`, `replay`, `admin_gift`, `account`, `admin_prune`, `prune`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `apply` cannot notify listeners without changing its callers; `services/marker_log.py` needs a change; over 300 production lines.

**Do not touch.** `bot/admin.py`, `bot/account.py`, `bot/admin_channels.py`, `services/marker_log.py`, other services.
