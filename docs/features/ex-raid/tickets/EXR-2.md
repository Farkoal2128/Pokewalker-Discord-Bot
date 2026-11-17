# EXR-2 — spawn rules per kind; `live_spawns`; `join` by spawn

**Tier:** seam (persisted state; slash commands)

**Read:** PLAN D3; SYNTHESIS XR-6..XR-8, R4, R5; `services/raids.py:22-44, :94-111`; `bot/raid.py:26-65`; `bot/bag.py:15-19`; C3 "M8.2a", "M8.3a", "Owner amendment: admin force raid".

**Goal.** A live EX-Raid no longer blocks a ticket or a force-raid, and `join` takes the spawn to join. No EX spawn can be created yet; tests insert one with EXR-1's columns. C3 first.

- **`_refusal`** (:108): the `active` check adds `AND kind='world'`. `spawn` and `force_spawn` are otherwise unchanged; `_insert` keeps its 12 columns (`kind` defaults to `world`).
- **`live_spawns(conn, guild_id, now)`** replaces `active_spawn`: every row of that server with `ended=0 AND expires_at>now`, `world` before `ex`, as dicts; `[]` when none.
- **`join(conn, guild_id, user_id, spawn_id, now, rng, content)`**: the spawn is read by `spawn_id`, `guild_id`, `ended=0` and `expires_at>now`; no row returns `{'status': 'none'}` before any other check. The rest keeps its order: `not_enrolled`, `excluded`, existing participation, receipt `raid:<spawn_id>:<user_id>`.
- **`bot/raid.py`** (:43): reads `live_spawns`; none gives the existing refusal text; else it joins the first row. The chooser and the new wording are EXR-8.
- **C3:** "M8.2a" and the force-raid amendment: `active` means a live World Legendary in that server. "M8.3a": `live_spawns` and the `join` signature; another server's spawn or an ended one is `none`.

**Files.** Production: `pokewalker/services/raids.py`, `pokewalker/bot/raid.py`. Tests: `tests/test_ex_raid.py` (new), `tests/test_raids.py`, `tests/test_admin_force_raid.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_raid.py`:
- `test_ticket_spawns_world_legendary_while_ex_raid_live` (XR-8)
- `test_live_world_legendary_still_refuses_a_second_ticket_as_active`
- `test_live_spawns_lists_world_then_ex_skips_ended_expired_foreign`
- `test_join_named_spawn_only_when_live_in_this_server` (another server's ID, ended, expired, unknown: `none`, nothing written)
- `test_player_joins_both_kinds_one_encounter_each`
- `test_expiry_of_one_kind_leaves_the_other_live`

In `tests/test_admin_force_raid.py`: `test_force_raid_spawns_while_ex_raid_live` (XR-8; cooldown and audit as today).

Pins moved in `tests/test_raids.py`, and only these:
- `:1021`, `:1197`: `active_spawn(...)` is None becomes `live_spawns(...)` equals `[]`.
- `join` calls at `:928`, `:934`, `:1204` and the helper `:984-987` pass the live spawn's ID.

Every other raid, ticket and force-raid test passes unchanged, including "A World Legendary is already active in this server." (`tests/test_raids.py:1425`, `tests/test_admin_force_raid.py:146`).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid`, `raids`, `admin_force_raid`, `capacity`, `catching`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** Another caller of `active_spawn` or `join` exists (`git grep -n "active_spawn\|raids()\.join(\|raids\.join(" -- pokewalker tests`; at `1ac1c07`: `services/raids.py:32`, `bot/raid.py:43` and the pins above); a ticket or force-raid test must change beyond the pins; over 300 production lines.

**Do not touch.** `bot/bag.py` (the `active` text stays, XR-8), `bot/admin_channels.py`, `bot/walker.py`, migrations.
