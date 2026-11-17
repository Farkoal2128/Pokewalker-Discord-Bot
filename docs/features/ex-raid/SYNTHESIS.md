# EX-Raid — pre-plan synthesis

Status: **intake open; Q1–Q3 answered; 3 review rounds applied, Must = 0 (2026-11-16)** (started at
`1ac1c07`). Paper only: no code, no PLAN.md, nothing committed until the owner approves.

Labels follow EX-Gift: **[O]** is the owner's spec. **[R]** is a recommendation that fills a gap;
the owner can override it. **[Q]** is an open question for the owner. A **recorded reading** is
Claude's interpretation of the spec, kept until the owner confirms it.

## 1. Outcome

Owners spawn an **EX-Raid** from the admin server, into one server or every server. The owner picks
the boss (any Pokémon) and can lock shiny, level and each IV; anything left open rolls per player
as raids do today. It lasts 60 minutes, or 1–24 hours if the owner sets a duration. An EX-Raid runs **beside** the regular World Legendary raid: neither blocks the
other, and `/raid` asks which one to open when both are live.

## 2. Owner spec

- **XR-1 [O]** A command on the **admin server**, similar to EX-Gift. It behaves like
  `/walker-admin force-raid`, but targets **one server or every server**.
- **XR-2 [O]** It opens a menu where the admin picks **any Pokémon** as the boss. Only the Pokémon
  is required.
- **XR-3 [O]** Optional locks: **shiny or not**; the **hidden level, 1–40**; **each of the three
  IVs, set separately**. Any field left alone is **rolled per player as usual**.
- **XR-4 [O]** With 1000+ species, paging dropdowns is unusable: use a better picker (§4, R1).
- **XR-5 [O]** Raid messages in servers say **"EX-Raid"**, never "Legendary raid", even when the
  boss is a Legendary.
- **XR-6 [O]** An EX-Raid **does not block** regular raids. If both are active in a server, `/raid`
  shows a **submenu to pick one**.
- **XR-7 [O]** An admin can start an EX-Raid while a regular raid is running, without errors.
- **XR-8 [O]** A force-raid or a player's **World Legendary Ticket still works** while an EX-Raid is
  live.
- **XR-9 [O]** (Q1, 2026-11-16) An EX-Raid lasts **60 minutes by default**, with an optional
  **duration of 1–24 hours**.
- **XR-10 [O]** (Q2, 2026-11-16) **Servers with raids turned off are skipped.**
- **XR-11 [O]** (Q3, 2026-11-16) "Any Pokémon" means **all 1,094 identities**, Mythicals, regional
  variants and forms included.

**Recorded reading of XR-9:** `duration` is a whole number of hours, 1–24. Leaving it out means
1 hour (60 minutes). Every server in one send gets the same `expires_at` (commit time + duration).

**Recorded reading of XR-2 + XR-4:** "opens a menu" is met by a slash command whose Pokémon option
autocompletes (R1) and whose locks are optional options, which then opens a **preview menu** with
Confirm and Cancel (R3). The admin never pages a dropdown. To change a choice, they cancel and run
the command again (Discord pre-fills nothing, but the command is one line).

**Recorded reading of XR-2 "only the Pokémon is required":** `pokemon` is the only required
option. The target is picked without a required option and never defaults to all servers:
giving `server_id` targets that server; leaving it out makes the preview menu ask for an explicit
**"All servers"** choice, and Confirm stays disabled until it is picked (R3).

## 3. Ground truth from the code (checked 2026-11-16 at `1ac1c07`)

| Fact | Where | Consequence for EX-Raid |
|---|---|---|
| `/walker-admin force-raid reason` is a **per-server** moderator command (`WalkerAdmin`), not an admin-server command. It spawns in the server it runs in | `bot/admin_channels.py:431` | EX-Raid is a new `/admin` subcommand on the admin server, like `/admin gift` (`bot/admin.py:96`, registered only for the admin guild at `:229`). It reuses force-raid's service path, not its command. |
| Force-raid's 24-hour cooldown is the newest `mod_audit` row with action `force_raid` per server, cleared by the D67 `force_raid_reset_at` | `services/raids.py:163`, `:166`; `services/cooldowns.py:15` (choices), `:30` (reset write) | EX-Raid neither reads nor writes that row, so it neither uses nor is blocked by the force-raid cooldown (R6). |
| **One active spawn per server** is enforced twice: the partial unique index `world_spawns_active_guild ON (guild_id) WHERE ended=0`, and `_refusal`'s `active` check | `migrations/0015_raids.sql:17`; `services/raids.py:108` | Coexistence needs a spawn **kind** (`world`/`ex`) and the index on `(guild_id, kind)` (R4). Every "active" check becomes per kind. |
| `active_spawn(conn, guild_id, now)` returns **one** row; `join` uses it | `services/raids.py:22`, `:29` | `active_spawn` lists the live spawns; `join` takes the chosen `spawn_id` (R5). |
| `_new_spawn` picks a random non-Mythical Legendary; spawns last **3600 s** | `services/raids.py:114` | The EX path inserts the owner's identity and an `expires_at` from the chosen duration (XR-9, R6). Expiry everywhere reads the stored `expires_at`, never a fixed 3600 s. |
| `join` rolls per player: gender, shiny (lure ×4, Shiny Charm ×4; consumes one lure encounter), level from `raid_level_range` [20, 25], IVs 0–15. It saves tier `Legendary/Mythical`, marks the species seen, writes participation under receipt `raid:<spawn_id>:<user_id>` | `services/raids.py:47`–`:70`; `content/balance/catch.json:43` | Locks replace individual rolls; open fields keep these exact rolls (R2). |
| Raid encounters never flee because their tier is `Legendary/Mythical` and `legendary_flee_probability` is 0 | `domain/cp.py:57`; `catch.json` | Storing the same tier keeps EX-Raids flee-free with no catch-rule change (R7). |
| Raid encounters sit outside the 3-encounter queue (`raid_spawn_id IS NOT NULL`) | `migrations/0015_raids.sql:27`–`:38` | A player can hold one World Legendary and one EX-Raid encounter at once; no queue change. |
| Catch path: `throw` refuses `expired` on the encounter's own spawn; Walker refuses "The World Legendary left."; the catch screen shows "World Legendary · ends <UTC>" and the encounter tier | `services/catching.py:69`; `bot/walker.py:459`–`:465`, `:520`, `:587`; `bot/screens_catch.py:25` (tier), `:39` (raid line) | Expiry already works per spawn. Only the **wording** branches on kind (R8). |
| The announcement embed is titled "World Legendary: <name>"; at-most-once posting via `post_state` and `resume_pending` on startup | `services/raids.py:202`, `:218`, `:238`; `bot/client.py:185` | EX-Raid titles "EX-Raid: <name>" and reuses the same at-most-once machinery (R8, R9). |
| `/raid` joins the single active spawn after opt-out, exclusion and pending-catch checks | `bot/raid.py:15`–`:66` | `/raid` gets a chooser when two are live (R5). |
| The WLT refusal `active` says "A World Legendary is already active in this server." and is shared with force-raid | `bot/bag.py:15`–`:19` | Still correct once `active` is per kind; a live EX-Raid no longer triggers it (XR-8). |
| `checked_channel(guild, …)` needs the cached `discord.Guild` to check embed/send permission. It reads only the gateway cache, with no network call | `services/raids.py:189` | The commit job resolves targets and checks each one through `bot.get_guild` **inside** the writer transaction; a server the bot cannot see is skipped (R6). |
| `_refusal` calls `expire` for the guild **before** its guards, so even a refused spawn settles overdue rows | `services/raids.py:94`–`:97` | Settlement on an EX send is explicit (R6): overdue rows must be ended so the unique index admits the new spawn, and a refused one-server send rolls back. |
| Research auto-send moves a caught, unconfirmed Pokémon to research after 900 s, unless it is shiny or its **species** is Legendary/Mythical. The encounter's tier is not consulted | `services/research.py:114`–`:127` | An ordinary EX-Raid boss caught and left unconfirmed is auto-sent after 15 minutes, like a wild catch; a Legendary, Mythical or shiny one waits for the player (R7). |
| The privacy text promises a raid participation record kept after `delete-data` "at most 60 minutes" | `docs/features/pokewalker-bot/privacy.md:11`; C3 M8.4 | A 24-hour EX-Raid breaks that promise; the text and contract change (R10). |
| Player help describes `/raid` and the raids switch only as World Legendary features | `content/help.md:49`, `:51`, `:98`, `:107` | Help gains EX-Raid lines (R8). |
| Walker re-checks for a pending catch only for a fixed action list (`open_encounter`, `throw`, …) | `bot/walker.py:183`–`:185` | New chooser actions must join that list (R5). |
| EX-Gift's `OwnerView` classifies Confirm by the `gift_confirm:` prefix (5/min bucket); everything else takes the 30/min bucket. Drafts and commit settlement refer to gift registries and services | `bot/admin_gift.py:105`–`:107`, `:35`, `:268`–`:316` | Reuse needs small, named adaptations, not reuse "as is" (R3). |
| Catalog: **1,094** identities (1,025 species plus forms), all with unique `name_en` (e.g. "Alolan Raichu", "Red Flabébé"), `species_id` = National Dex number. CPM table covers levels up to 40 (`level_x2` 2–80) | `content/artifact/content.json`; `content/balance/cpm.json` | The picker searches `name_en` and Dex number over identities. Level locks 1–40 are valid CP inputs. |
| EX-Gift already has the admin-server pattern: `authorize` (admin guild, owner IDs, 5/min, exclusion), scope `all`/`server` validated with `config.snowflake`, in-memory drafts with a 15-minute deadline, a stable send ID, a per-owner 30/min callback bucket, `gift-history` recovery | `bot/admin.py:72`; `bot/admin_gift.py:52`–`:316`; `docs/features/ex-gift/SYNTHESIS.md` R4, R5, R14–R19 | EX-Raid reuses these rules and helpers rather than inventing new ones (R3). |
| No code uses autocomplete or modals yet. `discord.py==2.7.1` supports both (`@app_commands.autocomplete`, `discord.ui.Modal`/`TextInput`) | `requirements.lock:181` | R1 adds the repo's first autocomplete. |
| The Arena team picker pages the player's **owned** Pokémon with Prev/Next and a select | `bot/arena.py:142`–`:170` | Not reusable for 1,094 species: it is exactly the paging XR-4 rules out. |

## 4. Recommendations

- **R1 [R] Pokémon picker: slash-command autocomplete.** The `pokemon` option autocompletes. As
  the admin types, the bot returns up to Discord's 25 suggestions ranked: exact Dex number (`26` →
  Raichu and Alolan Raichu), then name prefix, then substring, then close spellings (stdlib
  `difflib`), case- and accent-insensitive. Each suggestion shows `#006 Charizard`; its value is the
  `identity_id`.
  - **Why this over a modal text input:** autocomplete matches live while typing, so a typo is
    fixed before submitting and the result is an exact ID. A modal needs submit, then a separate
    "did you mean" step for every ambiguous or misspelled name: two round trips instead of zero.
    Both are supported by discord.py 2.7.1; autocomplete is also less code (one callback over the
    in-memory catalog, no modal/view state).
  - **Trust boundary:** autocomplete is only a hint; a client can submit any text. On submit the
    value must be a known `identity_id`. Anything else is refused privately ("Pick a Pokémon from
    the list.") and nothing is written. There is no second free-text matcher on submit. The preview
    (R3) shows the sprite and name, which is the confirm step.
  - **Autocomplete has its own check.** The command's `authorize` does not cover autocomplete
    callbacks, and it defers a reply, which autocomplete cannot do. The autocomplete callback
    checks the admin guild and a configured owner ID (both in memory) and returns an empty list on
    any failure. Exclusion is a database check (`bot/admin.py:90`), so autocomplete skips it: it
    reveals only public species names, and exclusion is enforced at the command and at Confirm.
    Typing reads no database row and does not use the 5-per-minute bucket.
- **R2 [R] Locks and rolls.** Optional options `shiny` (true/false), `level` (1–40), `iv_attack`,
  `iv_defense`, `iv_stamina` (0–15 each), declared as Discord ranges and re-validated on the server.
  At join, each locked field uses the lock; each open field rolls exactly as `join` does today
  (level from `raid_level_range` [20, 25], IVs 0–15, shiny at the base rate with lure and Shiny
  Charm). Gender always rolls. With `shiny` locked, an active lure is **not consumed** (it could not
  change anything). The level stays hidden, as for raids. `roll_level_ivs` returns the level and all
  three IVs together, so `join` calls it once and then overwrites each locked field; the RNG draw
  count stays the same whatever is locked. `shiny=false` and IV `0` are locks, distinct from "not
  set" (NULL). Rolls are made once at join and frozen in the encounter: reopening never rerolls or
  spends a lure again.
- **R3 [R] Command and preview menu.**
  `/admin ex-raid pokemon:<autocomplete> [server_id] [shiny] [level] [iv_attack] [iv_defense]
  [iv_stamina] [duration]`. `pokemon` is the only required option (XR-2). `server_id` is checked
  with `config.snowflake`, as EX-Gift R14 does; an invalid or unknown ID is refused.
  - It opens a private preview: send ID, boss name and sprite, each lock or "rolled per player",
    the duration, the target, and provisional counts (servers targeted, servers that will get it,
    servers skipped by reason). Buttons: **Confirm** and **Cancel**.
  - **Target.** With `server_id`, the target is that server. Without it, the preview shows an
    **"All servers"** button and no target. Confirm stays disabled until the owner presses it. The
    press is a draft edit: it bumps the draft revision, and the preview then shows the global
    counts. Nothing ever defaults to all servers.
  - After commit the bot reports committed counts.
  - **Confirm order** (EX-Gift R4/R5, carried over): authorization and exclusion first; then look
    up the send ID, owner-bound; a found send returns its **recorded** result with no new
    targeting, guards or spawns, even if its spawns have expired or servers changed since. Only an
    unknown send ID goes on to validate, target and insert. Another owner's send ID is refused as
    unknown. The whole multi-server insert is one transaction, so a failure part-way writes
    nothing.
  - **A send that spawns nowhere is refused**, for one server or all: no `ex_raids` row, no spawn,
    and the reply lists the skip reasons.
  - **What is reused from EX-Gift, and what changes:** draft lifetime (15-minute absolute
    deadline), states, send-ID stability and the settlement of commit, deadline and cancel are
    kept as they are. Three small adaptations: Confirm is recognised by its own `ex_raid_confirm:`
    prefix so it takes the 5-per-minute bucket; the draft registry holds both draft kinds (or
    EX-Raid gets its own); and commit calls the raid service instead of `ex_gift`. Both features
    share each owner's two rate buckets.
  - `/admin ex-raid-history [send_id]` lists sends the way `gift-history` does, so a lost
    acknowledgement can be checked without spawning twice.
- **R4 [R] Data model for two live raids.** One migration:
  - `world_spawns.kind TEXT NOT NULL DEFAULT 'world' CHECK(kind IN ('world','ex'))`; existing rows
    become `world`.
  - The partial unique index becomes `(guild_id, kind) WHERE ended=0`: at most **one World
    Legendary and one EX-Raid** live per server.
  - `world_spawns.ex_raid_id` references a new owner-side `ex_raids` row: send ID, sending owner
    ID, identity, the five locks (NULL = rolled), duration, target (all servers or one server ID), commit time and
    committed counts. It never holds a player ID (EX-Gift R20).
  - `raid_participation`, `encounters.raid_spawn_id`, the queue triggers, `expire` and the sweep
    already work per spawn and need no change.
  - Tests that insert `world_spawns` without a column list (e.g. `tests/test_raids.py:907`) need
    a column list; the schema-version tests move to the new version.
- **R5 [R] `/raid` with two raids.** After the existing opt-out, exclusion and pending-catch checks:
  no live spawn → today's refusal, reworded "No raid is active here."; one live spawn → open it
  directly, as today; **two** → a private chooser with two buttons, "World Legendary: <name> · ends
  <UTC>" and "EX-Raid: <name> · ends <UTC>", through a normal Walker session. Clicking joins (or
  reopens) **that** spawn; if it ended meanwhile, "That raid has ended." `join` takes the chosen
  `spawn_id`, checked to be live and in this server. A player may join both, one encounter each.
  - The chooser saves the two displayed spawn IDs in the session selection. A click names one of
    them by kind (actions `raid_pick_world`, `raid_pick_ex`; the router allows only `[a-z_]+`,
    `bot/walker.py:29`), so a forged or foreign spawn ID is never accepted. If the saved spawn ended
    and a new one of that kind started, the click says "That raid has ended." rather than joining
    the new one; the player runs `/raid` again.
  - The chooser action joins Walker's pending-catch list (`bot/walker.py:183`–`:185`), so a catch made in
    another session after the chooser opened still shows its pending menu first.
  - A double click is safe: `join` replays its `raid:<spawn_id>:<user_id>` receipt.
- **R6 [R] Spawn rules, duration and limits.**
  - Each targeted server gets its own spawn. `expires_at` is commit time + duration (XR-9):
    60 minutes by default, up to 24 hours. World Legendaries keep their fixed 60 minutes.
  - Guards per server, in order: raids off (or no guild row) (XR-10), no raid channel, no
    permission (or the bot is not in the server), channel changed, **an EX-Raid already live**. A
    guarded server is **skipped and counted**, not an error, so one bad server never blocks a global
    send. A one-server send whose only target is skipped is refused with the reason and writes
    nothing.
  - A live World Legendary is **not** a guard (XR-7). A live EX-Raid does not block a ticket or a
    force-raid (XR-8).
  - **No cooldown.** EX-Raids are owner-only and already throttled by `authorize` (5/min). The
    one-live-EX-Raid-per-server guard stops stacking. Force-raid's cooldown is untouched either way.
  - **Overlap with long EX-Raids.** Because the index allows one World Legendary and one EX-Raid,
    a 24-hour EX-Raid never blocks regular raids: tickets and force-raids keep spawning beside it,
    one World Legendary at a time, as today. It does block a **second** EX-Raid in that server until
    it ends; a later global send skips that server and counts it as "EX-Raid already live". Ending
    an EX-Raid early is **not** in the spec and is deferred. The owner waits for expiry.
  - **Raids turned off mid-raid.** `/walker-admin raids off` only clears `raids_enabled`
    (`bot/admin_channels.py:414`), so a live spawn runs to its expiry. That stays true for EX-Raids,
    so a server can hold a live EX-Raid for up to 24 hours after turning raids off. It gets no new
    ones (XR-10).
  - **Expiry and cleanup need no change.** `expire` settles any spawn whose `expires_at <= now`
    (`services/raids.py:76`) on the existing 60-second sweep (`bot/client.py:191`), and `throw`,
    Walker and `/raid` all check the spawn's own `expires_at`. None assumes 3600 s. Participation,
    revealed encounters and the at-most-once announcement state simply live longer. A pending catch
    (caught, not yet confirmed) follows research auto-send as today (R7). Raid encounters stay
    outside the 3-encounter queue, so a day-long open EX-Raid encounter never blocks walking. Walker
    sessions still idle out after 15 minutes; `/raid` reopens the same encounter at any time.
  - **"Global"** means every persisted guild row read **inside the commit transaction**. Targets,
    raid settings and the cached channel permission are all resolved there, so a server that
    changes between preview and Confirm is judged as it is at Confirm. The preview counts are
    provisional. A server that joins or turns raids on later does **not** get that EX-Raid (as
    EX-Gift EX-6).
  - **Settlement.** Before its guards, the commit ends each target server's overdue spawns (the
    existing `expire`), so an expired but unswept EX-Raid never blocks the unique index. A live World
    Legendary is never touched. A refused send writes nothing: `Writer.run` rolls back only on an
    exception (`db/__init__.py:110`–`:131`), so guards judge liveness by `expires_at` and settlement
    runs only when a spawn will be inserted. It is set-based, not per spawn. The sweep settles
    refused servers' overdue rows within 60 seconds anyway. (Corrected at planning; PLAN D5.)
  - **Writer time.** A global send is one transaction over every guild. It uses set-based reads
    (one query for guild settings and live EX spawns) and one batched insert, not a per-guild call
    of the single-spawn guards. An offline benchmark at the expected guild count must keep the
    writer hold well under the 5 s health probe (`bot/heartbeat.py:69`), as EX-Gift R4 required.
  - The spawn, the `ex_raids` row and its counts commit in **one** writer transaction. EX-Raid writes
    no `mod_audit` row (it is an owner action, as EX-Gift R6 keeps owner/player actions out of the
    moderation log).
- **R7 [R] Catch and rewards.** An EX-Raid encounter is an ordinary raid encounter: tier stored as
  `Legendary/Mythical` so it **never flees**, catch rate from the species and the (locked or rolled)
  level, the normal balls and berries (Master Ball included), normal candy and Stardust for the
  species, Pokédex seen on join and caught on catch, storage-full handling unchanged. No extra
  reward. Research auto-send stays **species-based** as today: a non-shiny ordinary boss caught and
  left unconfirmed goes to research after 15 minutes, while a shiny, Legendary or Mythical one waits
  for the player. No change to `auto_send`.
- **R8 [R] Wording (XR-5).** Every player-visible string for an EX spawn says **EX-Raid**:
  announcement title "EX-Raid: <name>" ("<name> is here! Despawns <UTC>. Join with /raid."); catch
  screen "EX-Raid · ends <UTC>"; the tier line shows "EX-Raid" instead of "Legendary/Mythical";
  "The EX-Raid left."; "This EX-Raid ended; this encounter expired."; "You already joined this
  EX-Raid; it can be joined once." World Legendary wording is unchanged. Player help
  (`content/help.md`) gains a line on EX-Raids and the `/raid` chooser. The `/raid` description
  becomes "Join or reopen an active raid", and `/walker-admin raids`
  (`bot/admin_channels.py:388`) becomes "Enable or disable raids (World Legendary and EX-Raid) in
  this server"; both are in the command-manifest update.
- **R9 [R] Announcements at scale.** Announcing happens **after** commit, never inside the
  transaction, using the existing `pending → attempted → sent` states.
  - The fan-out is scheduled as one background task owned by the bot **as soon as the commit
    returns**, before the receipt is sent. So a failed or cancelled receipt reply cannot strand the
    announcements. The task posts one message per server in sequence and is cancelled on shutdown,
    like other bot tasks.
  - **Failures are isolated per server.** A failed post or a failed `sent` write is logged and
    the task moves on to the next server. (Today `announce` lets a failed `sent` write escape, which
    would stop `resume_pending` before later rows; the EX fan-out and `resume_pending` both catch
    per row.)
  - The existing at-most-once rule is kept: a row left `attempted` (the post may have gone out) is
    never retried. On restart, `resume_pending` posts only rows still `pending` whose spawn is still
    live. Rows that expired meanwhile are never announced.
  - A failed or skipped post leaves that spawn joinable through `/raid`, as today.
- **R10 [R] Retention disclosure.** Participation is kept after `delete-data` until the raid
  leaves; for an EX-Raid that is up to 24 hours. The privacy text
  (`docs/features/pokewalker-bot/privacy.md:11`, delivered by `/walker-account privacy`) and C3
  M8.4 change to: "…until that raid leaves: at most 60 minutes for a World Legendary, at most 24
  hours for an EX-Raid." `ex_raids` holds only aggregate counts, never a participant ID.
  `/walker-account privacy` serves the file at `POKEWALKER_PRIVACY_PATH` (`bot/account.py:15`),
  not necessarily the repository copy. Updating the deployed file and reloading the bot is an
  owner-held delivery step, checked separately from the repository-text tests.

## 5. Code each requirement touches

| Req | Code |
|---|---|
| XR-1, XR-2, R1, R3 | `bot/admin.py` (new `ex-raid`, `ex-raid-history` subcommands, autocomplete with its own check); a new `bot/admin_ex_raid.py`; `bot/admin_gift.py` `OwnerView` confirm prefix and draft registry (R3 adaptations); `config.snowflake` |
| XR-3, R2 | `services/raids.py` `join` (locks over one `roll_level_ivs` call); `domain/encounters.py` unchanged |
| XR-6, XR-7, XR-8, R4, R6 | new migration 0031; `services/raids.py` `active_spawn`, `_refusal`, `_insert`, a new set-based EX commit beside `force_spawn`; `bot/bag.py` refusal text stays |
| XR-6, R5 | `bot/raid.py`; `bot/walker.py` chooser actions and the pending-catch list at `:184` |
| XR-5, R8 | `services/raids.py` `announce`; `bot/walker.py:465`, `:520`, `:587`; `bot/screens_catch.py:25`, `:39`; `bot/raid.py` strings and description; `content/help.md` |
| R7 | none beyond `join` (catch path is per spawn already: `services/catching.py:69`; auto-send unchanged) |
| R9 | `services/raids.py` `announce`/`resume_pending`, `bot/client.py:185`, a background fan-out task |
| R10 | `docs/features/pokewalker-bot/privacy.md`, C3 M8.4 |
| Tests | `test_raids` (incl. the column-less insert at `:907`), `test_admin_force_raid`, `test_catching`, `test_research`, `test_readme`, schema-version tests, both computed command-manifest hashes (admin guild and global; no literal pin, both syncs needed at delivery), and the only literal pin, the admin subcommand set (`tests/test_client_lifecycle.py:678`) |

## 6. Contract and migration impact

| Contract | Amendment |
|---|---|
| C3 `persisted-state.md` | Migration 0031: `world_spawns.kind`, `ex_raid_id`, the `(guild_id, kind)` index, the `ex_raids` table. Amend M8.1a (one live spawn **per kind**), M8.2a/M8.3a (`active_spawn` returns live spawns; `join` takes a spawn and applies locks), the force-raid amendment (`active` is per kind), M8.4 (EX participation retained up to 24 h, R10). |
| C5 `discord-commands.md` | `/admin ex-raid` and `/admin ex-raid-history` (M4.5a owner administration rules); the `/raid` chooser and reworded no-raid refusal (M8.3b); EX-Raid wording in announcements and catch screens (M8.2a, M8.1c). Command manifest gains the new subcommands. |
| C4 `balance-tables.md` | None: EX-Raids use `catch.json` as is. |

New spawn columns default so that every existing row and path behaves exactly as today.

## 7. Acceptance cases the plan must cover

- Autocomplete: Dex number, prefix, substring, misspelling, accents, forms; exactly 25 results
  maximum; empty for a non-admin guild and a non-owner; an excluded owner may see suggestions but
  is refused at the command; typing never uses the 5-per-minute bucket.
- Submit: a known `identity_id` previews; free text and an unknown ID are refused with nothing
  written. The serialized command has `pokemon` as its only required option.
- Target: with `server_id` the preview can confirm at once; without it Confirm is disabled until
  "All servers" is pressed; an invalid or unknown `server_id` is refused; a stale preview from
  before the "All servers" press cannot confirm.
- Bosses end to end: an ordinary species, a Mythical, a regional form and a gender-variety species;
  check identity, CP, catch rate, rewards, no flee and Pokédex.
- Pending EX catches: a non-shiny ordinary boss is auto-sent after 15 minutes; shiny, Legendary and
  Mythical ones are not.
- Locks frozen: `shiny=false` and IV `0` act as locks; partial locks differ correctly across two
  players; reopening does not reroll or spend a lure; a rolled-back join leaves nothing.
- Duration: omitted (60 min), 1 h, 24 h, 0 and 25 refused; one global send shares one
  `expires_at`; a 24 h EX-Raid with a World Legendary spawned, expired and spawned again beside it;
  sweep expiry at exactly `expires_at`; raids turned off while a long EX-Raid is live.
- Every lock combination: none, all five, each alone; level 1 and 40; IV 0 and 15; shiny locked
  with an active lure (lure kept) and unlocked (lure consumed).
- EX-Raid while a World Legendary is live; World Legendary Ticket and force-raid while an EX-Raid is
  live; a second EX-Raid into a server with one live (skipped).
- Global send: mixed servers (raids off, no channel, no permission, bot not present, EX-Raid live),
  counts per reason; a one-server send whose target is skipped writes nothing; an all-server send
  where every server is skipped writes nothing; a server whose settings change between preview and
  Confirm is judged at Confirm.
- Settlement: an expired but unswept EX-Raid does not block a new one; a refused send with overdue
  rows writes nothing; a live World Legendary is untouched.
- `/raid` with zero, one and two live spawns; joining both; a chooser click after its spawn ended
  and after a new spawn of that kind replaced it; a forged position or spawn ID; a double click; a
  catch made in another session before the chooser click (pending menu first).
- Back with both raids joined and an ordinary encounter queued: Back from Master Ball confirm,
  shiny Run confirm and storage-full confirm returns to the **selected** raid encounter, keeps
  items and rolls, and leaves the other raid's encounter untouched. After the selected spawn
  expires (before and after cleanup), Back follows the existing fallback (C5 M8.1c): the ordinary
  queue or Home, with confirmation flags cleared and the other raid untouched.
- Expiry of one kind leaves the other live; a catch committed before expiry stays readable.
- Every EX string says EX-Raid, including for a Legendary boss; World Legendary strings unchanged;
  help and the `/raid` description updated.
- Confirm: retried confirm, a replay after its spawns expired or servers changed (returns the
  recorded result, spawns nothing), another owner's send ID, a failure part-way through the
  multi-server insert, lost acknowledgement recovered through history, restart before confirm,
  forged or other-owner callback, owner excluded after preview or while Confirm waits, draft past
  its deadline, cancel during commit, EX-Gift and EX-Raid sharing one owner's rate buckets.
- Fan-out: scheduled before the receipt; a failed or cancelled receipt reply still announces; a
  slow post; shutdown mid-fan-out; a failed post and a failed `sent` write, each followed by later
  servers that still get announced (and the same through `resume_pending`); `attempted` rows never
  retried; restart after some remaining spawns expired.
- Writer benchmark: a global send at the expected guild count, measured against the health probe.
- Retention: delete-data, opt-out and reset during a 24-hour EX-Raid keep participation until it
  ends; re-enrolling cannot join again; `ex_raids` holds no participant ID; the repository privacy
  text says 24 hours. Separately (owner-held, at delivery): the configured privacy file says 24
  hours and the running bot serves it.
- Migration: existing spawns become `world`; the unique index holds per kind; column-less test
  inserts updated.

## 8. Open questions for the owner

Answered: Q1 → XR-9, Q2 → XR-10, Q3 → XR-11.

No questions are open. One consequence of XR-9 the owner may want to revisit: with no early-end
command, a 24-hour EX-Raid blocks the next EX-Raid in that server until it expires (R6).

## 9. Intake log

| Date | Input |
|---|---|
| 2026-11-16 | Initial spec: admin-server EX-Raid, any-Pokémon boss, optional locks, EX-Raid wording, coexistence with regular raids (XR-1..XR-8). |
| 2026-11-16 | Answers Q1–Q3: 60-minute default with a 1–24 hour duration option (XR-9); skip raids-off servers (XR-10); all 1,094 identities (XR-11). |

## 10. Review log

| Round | Reviewer | Must | Should | Nit | Result |
|---|---|---|---|---|---|
| 1 | Codex `gpt-6-astra` | 3 | 11 | 1 | All 15 accepted. Added R10 and the new §3 rows. #3 was first answered with a reading that kept `scope` required; round 2 rejected that. |
| 2 | Codex `gpt-6-astra` | 1 | 3 | 1 | 10 of 15 round-1 fixes verified. All 5 accepted: `scope` dropped (Pokémon is the only required option, explicit "All servers" in the menu); runtime privacy-file delivery check; Back cases with both raids; fan-out scheduled before the receipt with per-server failure isolation; `/walker-admin raids` description. |
| Plan 1 | Codex `gpt-6-astra` | 1 | 2 | 1 | PLAN.md + EXR-1..14. All 4 accepted: no fan-out task while stopping (EXR-6); set-based settlement and a two-scenario benchmark (EXR-4, G-B); three settlement tests (EXR-11); `walker.py:29` anchor. |
| Plan 2 | Codex `gpt-6-astra` | 1 | 1 | 0 | All 4 round-1 fixes verified. Both accepted: startup recovery tracked and drained (EXR-6); the mid-drain test drives `Writer.run` and the real Confirm test moves to EXR-11. |
| Plan 3 | Codex `gpt-6-astra` | 0 | 0 | 0 | Both round-2 fixes verified. GO. Loop stopped. |
| 3 | Codex `gpt-6-astra` | 0 | 1 | 0 | All 5 round-2 fixes verified (one partly). The Should (Back after the selected spawn expires follows the existing M8.1c fallback) is accepted and applied in §7. Loop stopped: Must = 0. |
