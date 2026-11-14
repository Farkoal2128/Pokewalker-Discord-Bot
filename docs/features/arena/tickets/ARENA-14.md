# ARENA-14 — `/walker-admin arena on|off reason`

**Tier:** seam (slash commands; persisted state)

**Read:** PLAN D2; REQUIREMENTS AR-35, AR-35a; ARENA-4, ARENA-8; `bot/admin_channels.py` `legendary_defenders` (:385-418), `sharing` (:223-250), `authorize` (:29), `check_actor` (:181); `tests/test_gym_legendary_setting.py:45`; `tests/test_admin_channels.py:128`.

**Goal.** A server switch for the Arena, on by default. Copy `gyms legendary` step for step; register it as a direct `/walker-admin` subcommand the way `sharing` is. C5 first.

- **Command:** `@app_commands.command(name="arena", ...)` on `WalkerAdmin`, parameters `on` (choices `on`/`off`) and `reason`.
  1. `defer(ephemeral=True)`; `authorize` (Manage Server, in a server, actor not excluded).
  2. `reason.strip()` must be non-empty → else "A reason is required."; `on` must be `on` or `off`.
  3. One writer job: `check_actor`; `INSERT OR IGNORE INTO guilds`; `UPDATE guilds SET arena_enabled=?`; one `mod_audit` row with `target_kind 'guild'`, the guild as target, action `arena_on` or `arena_off`, the reason, and `self.bot.walker.clock()` as the time.
  4. Reply with the new state: "The Arena is now on in this server." / "The Arena is now off in this server. Runs already started can be finished, and tickets can still be redeemed."
- **What off does** is already built: ARENA-8 `start` returns `off`; `fight`, `heal`, `set_order` and ARENA-10 `redeem` never read the flag. This row adds the tests that pin it end to end. Turning it back on changes nothing else: cooldowns, `arena_best_floor` and tickets are untouched.
- **C5:** append "`/walker-admin arena on|off reason`". **C3:** one line naming the `arena_on` / `arena_off` audit actions.
- **Delivery note:** the new subcommand changes the command manifest (`bot/client.py` `command_manifest_hash` :310), so Discord needs a command sync after deploy. That is an owner effect at G-F, never part of this row.

**Files.** Production: `pokewalker/bot/admin_channels.py`. Tests: `tests/test_arena_admin.py` (new). Contracts: `contracts/discord-commands.md`, `contracts/persisted-state.md`.

**Accept.** Tests pass, RED first:
- `test_arena_off_then_on_sets_flag_and_writes_audit_rows_with_reason`
- `test_arena_defaults_on_for_new_and_migrated_guilds`
- `test_reason_required_changes_nothing`
- `test_manage_server_required_and_excluded_actor_refused`
- `test_reply_names_new_state`
- `test_off_blocks_new_runs_only_live_run_and_redeem_continue`
- `test_on_again_keeps_cooldown_best_floor_and_tickets`
- `test_arena_subcommand_registered_in_client_manifest`

Existing `test_admin_channels`, `test_gym_legendary_setting` and `test_admin_reset_sharing` pass unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena_admin.py"`, `-p "test_admin_channels.py"`, `-p "test_gym_legendary_setting.py"`, `-p "test_admin_reset_sharing.py"`, `git diff --check`.

**Stop if.** `mod_audit` rejects the new actions (a constraint would need a migration: report it); the command needs a new permission or intent; any step would sync commands or touch Discord.

**Do not touch.** The other `/walker-admin` commands, `bot/client.py`, `services/arena.py`.
