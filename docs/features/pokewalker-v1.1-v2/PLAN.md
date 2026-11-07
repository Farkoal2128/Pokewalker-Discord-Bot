# Plan: pokewalker-v1.1-v2 — depth (v1.1) and gyms (v2)

**Status:** approved — in execution (owner approved for build 2026-11-05, G-A)
**Review:** round 4 2026-11-05 (MUST 0, SHOULD 1, NIT 1 — loop stop condition met; earlier rounds: MUST 12, SHOULD 19, NIT 1) — fixes applied, see §7; re-review pending (owner workflow, README.md:433-446). **Amendment M6.8a–i:** 5 rounds, final MUST 0 SHOULD 0 NIT 0 (§7). **Amendment 2 (M6.8j–q):** round 1 MUST 9 SHOULD 1 — fixes applied; round 2 MUST 2 — fixes applied; round 3 MUST 1 SHOULD 1 — owner-accepted / fixed; round 4 MUST 0 SHOULD 0 NIT 0 (§7). **Amendment 3 (Q22, M6.8r–z):** drafted 2026-11-06 at 3e56b30; round 1 MUST 6 SHOULD 3 NIT 1, round 2 MUST 3 — fixes applied; round 3 MUST 0 SHOULD 0 NIT 1 — fixed, "Ship" (§7).
**Home:** feature/pokewalker-v1.1-v2 · none — owner decision 2026-11-05: cut from `docs/pokewalker-v1.1-v2-plan` (which descends from `feature/pokewalker-bot-drive` at 648bb37); not yet created when recorded (`git branch --list` 2026-11-05); planning docs stay on `docs/pokewalker-v1.1-v2-plan`
**Inputs:** [requirements D1–D61](../pokewalker-bot/README.md) · [v1 plan](../pokewalker-bot/PLAN.md) (closed, rules inherited) · [PIPELINE.md](../../../PIPELINE.md) · [research: gyms](../../research/gyms/README.md), [go-systems](../../research/go-systems/README.md), [forms](../../research/data-visuals/pokeapi-forms.md)

## 1. Outcome

Two releases of D35 on top of the built v1 bot (648bb37), each playable alone in one server:

- **v1.1 depth** (README.md:78): evolution with Candy by stage depth (D40), form-aware routes and
  kept gender conditions (D54), the pin-derived evolution-item set with drops and the 500-Stardust
  purchase (D55), Shedinja catch-only (D56); Star Piece; storage and bag expansion (D44); route
  unlocks (D45); the full 10,000-weight find table (D21 "from v1.1"); v1.1 conversion rates (D61).
- **v2 gyms** (README.md:79): per-server gyms with `/walker-admin gyms` commands; deploy, recall,
  auto-simulated battles with text results and hotlinked sprites (D49); 8-hour tenure with hourly
  weakening (D24, D32); hourly gym income (D13, D23); survivor roll, World Legendary Ticket,
  `/raid`, `/walker-admin raids` (D60); `/walker-mod gym-recall` (D31); Legendaries attack but never
  defend (D41); companion and deployed-Pokémon restrictions (D30).

Binding owner decisions (2026-11-04, not reopened): no image rendering in any version — every
picture is the hotlinked pinned sprite and lists stay text (README.md:59 D49); Shiny Lure = next
10 generated encounters (PLAN v1 :585-590, built); ❗ on every message that queues an encounter
(README.md:19 D3, built). Delivery is local-only (owner instruction 2026-11-05). Owner decisions
2026-11-05 settle every G-A and G-6 question (§4.1).

## 2. Non-goals

- **Later** (README.md:80): peer visits, dowsing presentation, interactive battle turns, raid
  *battles*, trading, Candy XL, events/featured routes. Research's interactive alternative
  (battle-system.md:67-80) and gym themes/access channels (discord-gym-design.md:31-47) are out.
- **Owner-only open question stays open** (README.md:404-411): Legendary pacing / a featured
  Legendary group; no row decides it. Research send from the catch screen (README.md:413-415) is
  decided by Q18 (owner decision 2026-11-05); README stays owner-only and is not edited.
- No new content source: D51 pin unchanged; v2 moves are bot type templates, not imported GO move
  data (move-data-sources.md:45-51). No GO Game Master, PoGoAPI or PvPoke import.
- No publication, integration or deployment: local branch only (owner instruction 2026-11-05).
- Multi-process, PostgreSQL, battle images, gym badges, leaderboards, daily reward budgets (D9).

## 3. Verified code map — verified at 648bb37

Grep evidence: `rg -n "evolution|evolve" pokewalker/` → no production evolution code (only
`services/milestones.py:44-48,73-76` evolution-line milestones); `rg -n "gym|raid|star_piece"
pokewalker/` → none; `rg -n "pokemon_evolution" content/build/` → only `fetch.py:21` (fetched,
never read). `rg -n "DELETE FROM step_events" pokewalker deploy` → none (lifetime steps are
summable from `step_events`). Local pinned cache `build/pokeapi/e5b79b2e/` holds
`pokemon_evolution.csv` (676 rows, 641 `is_default=1`; 50 distinct trigger+held item ids; the one
trigger-4 `shed` row is id 155 → species 292) but no `items.csv`/`item_names.csv`/`type_efficacy.csv`;
`content/build/__main__.py:20-21` fetches only when the cache manifest is absent (`python` count
and read 2026-11-05).

Round-1 evidence (2026-11-05):
- **Owned-Pokémon resolver.** `rg -n "identify\(" pokewalker/` → `services/storage.py:4-10` is
  the only one (callers bot/research.py:56,:86,:114; bot/share.py:25; bot/storage.py:75;
  bot/walker.py:189,:298; services/powerup.py:23; research.py:29,:59; stepping.py:126).
  `rg -n 'content\["identities"\]' pokewalker/` also hits catching.py:86 (encounters only),
  pokedex.py:13, profiles.py:42 (tier pools), :107, walker.py:164.
- **Branch targets.** graph.py:190-191 excludes D52 branch forms; `content/manifest.json`
  `excluded` lists form 10228 (pokemon 10126, Lycanroc Midnight), 10311 (10152, Dusk), 10360
  (10191, Urshifu Rapid Strike) — the only non-cosmetic, non-default-only evolution targets outside
  retained identities (`python` over cache + manifest; targets 10107–10110 are D52 default-only and
  collapse to species defaults under Q1).
- **Recipes.** Milcery→Alcremie: 63 default rows, 7 held sweets (item ids 1167–1173), every target
  a cosmetic form → one target `869:869`. Distinct (target form, item, gender) per source before
  collapse: Milcery 63, Spewpa 20, Scatterbug 20, Eevee 8.
- **Nonce.** `.venv/Scripts/python.exe -c "import inspect,discord; print(discord.__version__,
  'enforce_nonce' in inspect.signature(discord.abc.Messageable.send).parameters)"` → `2.7.1 False`;
  `.venv/Lib/site-packages/discord/http.py:206-208` sets `payload['enforce_nonce'] = True` whenever
  a nonce is passed; `send` (abc.py:1534 `nonce`) has no `**kwargs`, so `enforce_nonce=` would
  raise `TypeError`.
- **Round 2.** `services/catching.py:79` binds a local `items` list inside `throw`, so a module
  call there must use a directly imported name. Pinned evolution `gender_id` values are 1/2
  (`python` over the cache: Combee→Vespiquen row is 1), while `pokemon.gender` and
  `encounters.gender` store `'male'|'female'|'genderless'` (0001_core.sql:69, :112). Positional
  `INSERT INTO <table> SELECT` fixtures break when a migration adds a column (in-memory
  reproduction: "has 3 columns but 2 values were supplied"): encounters — test_walker_encounter.py:88,
  test_walker_ack.py:41, test_route.py:92 (M8.1a); pokemon — test_catching.py:95, :279,
  test_storage.py:31, test_walker_encounter.py:251 (M7.4a). v1 tests pinned to table limits or
  open routes: test_conversion.py:71, test_storage.py:373, test_milestones.py:173 (profile CHECK
  ≥ 250 forbids their values), test_route.py:38-136 (0 steps).
- **Round 3.** Ordinary sources with both a region-null and a region-specific default row (12;
  `python` over the cache): Pikachu (rows 17/517), Exeggcute, Cubone, Koffing, Mime Jr.,
  Quilava, Dewott, Petilil, Rufflet, Goomy, Bergmite, Dartrix; the 25 regional identities whose
  species has children all have explicit `required_pokemon_form_id` rows. `WalkerBot.clock` =
  `time.monotonic` (client.py:74) vs `Walker.clock` = `time.time` (walker.py:43).
  tests/test_receipt_owner.py:46-70 rebuilds a pre-0003 schema by dropping later tables/columns
  and re-runs every migration (:88, :90-95). In-memory probes (SQLite 3.45.1): a composite FK to
  `(profile_id, guild_id)` backed by a unique index rejects a cross-guild row and cascades;
  `DROP COLUMN` works on an FK column but fails on a column a trigger uses. The mini
  `pokemon_evolution.csv` is header-only (`id,evolved_species_id`).
- **Deletion.** FKs are on (db/__init__.py:32, :59); delete-data runs `DELETE FROM profiles`
  (deletion.py:73), so `ON DELETE SET NULL` fires. 0002_reaction_encounter.sql:1 is the
  `ADD COLUMN … REFERENCES … ON DELETE` precedent.
- **Amendment evidence — verified at 1ac0157 / be1672d (2026-11-05).**
  - *Alcremie in the pin* (`python` over the gitignored cache `build/pokeapi/e5b79b2e/`):
    `pokemon_forms.csv` holds 63 forms on `pokemon_id` 869 — 869 (default,
    `vanilla-cream-strawberry-sweet`), 10346–10353, 10449–10502 — plus Gmax 10392 on pokemon
    10223 (battle-only). English names: "<Cream> <Sweet> Alcremie". `pokemon_evolution.csv` has
    63 default rows to species 869 (ids 441, 620–681): `held_item_id` 1167–1173 (7 sweets) × 9
    distinct `evolved_pokemon_form_id`; cream depends only on stripped conditions.
    Species 868/869 `has_gender_differences=0`.
  - *Today:* graph.py:197-201 reports the 62 non-default forms "cosmetic-equivalent";
    evolutions.py:47-48 falls back to the default, so Milcery has 7 recipes
    `868:868>869:869|<sweet>|-` labelled "Vanilla Cream Strawberry Sweet Alcremie / <Sweet>"
    (evolutions.py:64-65). Limits: ≤ 25 recipes per source (evolutions.py:73-75,
    emit.py:103-104); largest today Eevee 8.
  - *Identity by `pokemon_id` only:* `pokemon` has no form column (0001_core.sql:104-121);
    `identify` matches `pokemon_id` (storage.py:7) and receives `sqlite3.Row` objects (no
    `.get`; walker.py:192, :301) as well as dicts; `evolve` writes `pokemon_id` (evolution.py:71).
    No identity/target record is a non-default form, and no `pokemon_id` carries two records
    except the gender `male` copies, so form keys and form-exact `identify` change no output.
  - *Sprites:* URL key is `pokemon_id` (emit.py:67) → every form would get `869.png`.
    Coordinator check 2026-11-05 at sprites commit `1b3b7c0a…`: HTTP 200 for
    `sprites/pokemon/869-<form_identifier>.png` and `shiny/869-<form_identifier>.png` for all 62
    forms (124 URLs); the default stays `869.png`.
  - *Simulation* (scratch copy of `content/build` at 1ac0157, `alcremie` in `EVOLUTION_ONLY`,
    per-item limit, in memory): `evolution_targets` 65, `evolution_edges` 587, no pending,
    artifact 1,468,816 bytes; Milcery `edges[0]` and `edges[-1]` are both Strawberry Sweet.
  - *"King�s Rock":* zero `EF BF BD` bytes in the 1ac0157 tree, the HEAD artifact and
    `pokewalker.sqlite3`/`-wal`; the artifact holds U+2019; `_read` is strict `utf-8-sig`
    (graph.py:39). Python on this host prints U+2019 to a pipe as cp1252 `0x92`, shown as "�" —
    the sighting was this terminal artifact (coordinator-confirmed).
  - *v2 persistence of Pokémon fields* (be1672d): only `services/gyms.py:204-205`
    `_battle_snapshot` copies a field list (into the `battle:` receipt); bot/gyms.py:127-150
    renders results from it. Deployments store `pokemon_uid` only.
  - *Schema-pinned tests* (be1672d): test_capacity.py:79 expects `user_version` 15 at 9840247,
    test_gyms.py:388 14; test_gyms.py:362-388 compares the whole upgraded `pokemon` row.
  - *Raids (M8.1c landed, 1f21148):* `open_encounter` skips raid rows unless a selection flag names
    one, so shortcut returns must name the encounter.
  - *QoL seams:* storage-full catch screen walker.py:404-411; expand storage bot/storage.py:119-143;
    research bot/research.py:41-76, :131-141; inbox render bot/milestones.py:95-129; bag
    expand/convert bot/bag.py:139-210; `buy_evolution_item` items.py:186-219; one writer job =
    one transaction (db/__init__.py:110-121); capacities.json:19-27; evolution.json:12.
  - *Drift since 1ac0157* (`git diff --stat 1ac0157 be1672d -- pokewalker tests`): walker.py +1
    line, bot/milestones.py gym labels, items.py `RARE` from capacities, `0014_gyms.sql` (next
    free migration 0015).

Amendment 2 code map — verified at a08f349 (tree identical to 6f7d5e6; `git diff --stat a08f349
c48701b` → PLAN.md only):

- Router: walker.py:114-147 (owner/guild :129-131, expiry/revision :132-133, exclusion :134-135,
  opt-out :136-137, handler lookup :138-140, revision + selection write :141-146).
- Fresh `/walker`: walker.py:68-112; `home` runs outside the router at :107; `before_home` =
  `recover_terminal` (:65, :184-187, :208-220; selection UPDATE :215-217); `ack` :222-231.
- Throw: walker.py:403-443 (master confirm :407-418; `catching.throw` :419-421; read-only
  :422-424; terminal :427-428; `storage_full` notice + Storage / `catch_expand_storage` /
  `catch_research` buttons :429-443); `open_encounter` :268-304 (`catch_return` :277, :284).
- Service order: services/catching.py:64-71 (exclusion, terminal/stale, raid expiry), :72-75
  (storage refusal), :115-120 (Pokémon insert); services/research.py:36-79 (`send`, receipt
  `research:<preview id>` :48).
- `render_terminal` (screens_catch.py:65-80) callers: `rg -n "render_terminal\(" pokewalker` →
  walker.py:220, :339, :376, :398, :428; raid.py:59; share.py:77.
- Superseded handlers: bot/research.py:68, :81-83, :147, :152-154; bot/storage.py:88, :123-138,
  :149, :165-166, :250 (`rg -n "catch_research|catch_expand_storage|catch_return" pokewalker
  tests` → walker.py:277, :284, :440, :442, research.py, storage.py, test_capacity.py only).
- `/raid`: raid.py:25-59; `raids.join` (services/raids.py:29-69) creates the encounter and
  participation and spends a Lure charge (:62-64) — so the lock runs before it.
- Migrations end at `0016_pokemon_form.sql` (`git ls-tree --name-only HEAD
  pokewalker/db/migrations/`); M6.8k adds **`0017_storage_overflow.sql`**. Version pins count
  migration files (`rg -n user_version tests/`: test_db.py:72, test_capacity.py:79,
  test_gyms.py:397, test_raids.py:437, test_pokemon_forms.py:49, test_milestones.py:635,
  test_receipt_owner.py:109); test_route_unlocks.py:146, :219 and test_deletion.py:563 pin
  prefixes. Whole-row profile comparisons: test_capacity.py:74-77; `legacy_schema`
  test_receipt_owner.py:46-93.
- Writer: db/__init__.py:112-119 (`BEGIN IMMEDIATE`, commit, rollback on raise).
- Sweep: bot/client.py:148-153 (`_sweep_once`: one writer job, one `walker.clock()` read,
  `gyms.settle` then `raids.expire`), :155-161 (tick, then `sleep(60)`), :137-146 (`on_ready`
  starts the loop once; its first tick runs at once). Pinned by test_raids.py:1753 (one job),
  :1773 (one clock read), :1756-1764 (one-job rollback) and test_gyms.py:746-830.
- Sessions expire 900 s after opening (walker.py:83) and the router refuses expired ones
  (:132-133), so no click-driven path can meet a 15-minute deadline (review r2 #1).
- Members: client.py:79-80 (no Members intent); `interaction.user` carries the role IDs of the
  interaction payload (.venv discord/interactions.py:288, member.py:323), so
  `check_actor` (admin_channels.py:117-121) cannot see a later role change; `Guild.fetch_member`
  (.venv discord/guild.py:2528-2562) is an HTTP read raising NotFound/Forbidden/HTTPException.

**Amendment 3 code map — verified at 3e56b30** (M6.8k built at 166660b; M6.8j at 0d3fb40):

- Catch: services/catching.py:50 (`throw`), :65-71 (exclusion, terminal/stale, raid expiry),
  :72-75 (storage refusal), :76 (selection), :96-144 (`compute`), **:116-120 (`INSERT INTO
  pokemon … SELECT … FROM encounters` — the only catch-time row write; `rg -n "INSERT INTO
  pokemon" pokewalker` → catching.py:116 and the starter, profiles.py:127)**, :121-124 (Pokédex
  `caught_at`, `check_and_award`), :125-139 (rewards), :146 (`with_receipt`); :90-92 (the
  encounter's species must be in content).
- Encounter row = Pokémon row: 0001_core.sql:59-81 (`encounters`: species, level, IVs, gender,
  `shiny` :70, `state` :74, `resolved_at` :79, `acknowledged_at` :80) vs :104-121 (`pokemon`;
  `source_encounter_id UNIQUE` :115; `state CHECK IN ('owned','sent')` :117). `render_terminal`
  and `_embed` already render from the encounter when no row exists (screens_catch.py:19, :69);
  `identify` accepts an encounter row and returns `(identity, sprite)` (walker.py:369-370;
  services/storage.py:4-12).
- Walker (M6.8k in): router :115-148 (handler lookup :139-141); `home` :176-207 (`before_home`
  :185-188); `overflow` :209-213; `overflow_choice` :215-241 (label "Send to research" :235);
  `catch_upgrade` :243-258; `recover_terminal` :260-274 (query :263-266, selection write
  :269-271); `ack` :276-285 (UPDATE :281-283); `open_encounter` :322-358 (`catch_return` :331,
  :338); `encounter_state` :360-387 (pokemon :366-368, share :380, `pokemon` key :382); `throw`
  :457-497 (service :473-475, read-only :476-478, terminal :481-482, notices :483, shortcut
  buttons :488-496); `master_confirm` :499-500. screens_catch.py:65-82 (`render_terminal`;
  `recovery` hides the five disabled catch controls :74-76 and Share :80); its callers (`rg -n
  "render_terminal" pokewalker`): walker.py:222, :274, :393, :430, :452, :482; raid.py:59;
  share.py:77.
- `acknowledged_at` writers: `rg -n "acknowledged_at" pokewalker` → walker.py:264 (recovery
  read), :281-283 (`ack`, the only write) and the schema. Done (`ack`), M6.8j's post-send Done
  and M6.8k's Upgrade (→ `ack` :258) are the only paths; Later (:413-418), recovery, `/raid`
  reopen (raid.py:52-59) and share.py never acknowledge.
- Invisible while pending: no `pokemon` row exists, so no `pokemon` reader sees or counts it
  (`rg -n "FROM pokemon" pokewalker`); the owned filters (`rg -n "state='owned'" pokewalker` →
  storage.py:16, :26, :34; catching.py:72; services/research.py:23, :25; walker.py:193, :212,
  :223; share.py:59; gyms.py:99; admin_channels.py:139) also exclude `sent` rows.
- Research: services/research.py:9-17 (`protected_reason`: deployed, favorite, companion, shiny,
  `is_legendary`/`is_mythical`), :20-33 (`candidates`), :36-79 (`send`; replay :48-52 before
  expiry :53-54); bot/research.py:85-93 (`catch_send`), :95-123 (`review`), :125-143 (`single`),
  :151-163 (`confirm`), :165-173 (`cancel`), :175-180 (`research`).
- Raids: raid.py:25-59 (`open_raid`); services/raids.py:29 (`join`; encounter :57-60), :75-83
  (`expire` deletes queued/revealed only); `rg -n "DELETE FROM world_spawns" pokewalker` → 0.
- Sweep: client.py:148-153, :155-161, :137-141; pins test_raids.py:1748-1813, test_gyms.py:746-830.
- Deletion/opt-out: services/deletion.py:131 (profile delete cascades encounters and pokemon
  alike); docs/features/pokewalker-bot/privacy.md:12 (opt-out deletes the profile) — no opt-out
  clause needed in the sweep.
- Migrations: `0001`–`0017` at HEAD (`git ls-tree --name-only HEAD pokewalker/db/migrations/`);
  **no new migration** in amendment 3.
- **Do not touch (:177 replaced):** `services.research.send` (M6.8r/x add `send_pending`,
  `send_pending_reviewed`, `auto_send` beside it), services/capacity.py, services/raids.py,
  share.py, `0017_storage_overflow.sql`, the M6.8h inbox `back`, services/deletion.py, closed
  tickets M6.8f/g/j/k, superseded tickets M6.8l/m/n/q, README.md.

### 3.1 Reuse anchors (file:line)

| Anchor | Fact | Used by |
|---|---|---|
| content/build/fetch.py:17-23; emit.py:32-47 | `REQUIRED_CSVS`; `verified_inputs` hashes every required CSV into `csv_sha256` | M6.1a |
| content/build/emit.py:110-206, :116-117, :137-140, :144-151, :152-156, :191-205 | `build_content`; stats/families; species+sprites; routes; artifact keys; counts+manifest | M6.1b |
| content/build/graph.py:30, :131-148, :160-200 | `GENDER`; `identity()`; D52 policy (`EVOLUTION_ONLY` :190-191) | M6.1b |
| content/build/families.py:28-72 | parent edges, depth, family | M6.1a |
| contracts/content-artifact.md:14-62, :64-68 | C1 invariants; additive fields allowed | M6.1a/b |
| tests/test_content_integrity.py:24-73; tests/test_content_emit.py:159 | hash, literal counts :45-49, balance hashes :65; mini pair must equal rebuild | M6.1a/b, M6.2, M7.1 |
| content/balance/find_table.json:5-61, gym_income_table.json:5-73 (`evolution_item` :67), conversion_rates.json, capacities.json:5-17, routes.json | v1 tables | M6.2, M7.1, M7.4a |
| contracts/balance-tables.md:57, :61, :62, :65, :154-155 | find exclusions; conversion; capacities; gym table "data only" | C4 |
| tests/test_conversion.py:161-168 | v1 refuses `star_piece`, `evolution_item`, `world_legendary_ticket` | M6.4a |
| pokewalker/db/migrations/0001_core.sql:13-27, :59-91, :104-140 | profiles; encounters + queue triggers :83-91; pokemon/inventory/candy/pokedex | migration rows |
| 0006:4, 0007:1-33, 0009:1-14 | effect kind CHECK; copy-rebuild; `ADD COLUMN` | M6.5a, M8.1a |
| pokewalker/db/__init__.py:34-46, :72-83, :158-176 | migrations; `Writer.run`; `with_receipt` | all |
| services/items.py:10, :13-16, :19-40, :43-45, :48-80, :128-163, :166-207 | `RARE`; `bag_units`; `grant`; `roll_find`; `apply_finds`; `convert`; lure | M6.4a, M6.5a, M6.6b, M7.3 |
| services/powerup.py:19-38, :41-74 | quote; receipt + stale | M6.3a, M7.7b |
| services/catching.py:49-148 (:68-71 storage, :117-120 pokedex, :121-134 rewards) | throw | M6.5b, M6.6b, M8.3a |
| services/milestones.py:95-108, :131-181 (:152-158 caps) | `check_and_award`; `claim` | M6.6c, M7.3 |
| services/stepping.py:98-121, :126, :135 | mint; companion `identify`; `apply_finds` | M6.4a |
| services/profiles.py:58-80, :90-143; storage.py:4-35; research.py:9-16 | profile/queue_size; `identify`; `protected_reason` | M6.3a, M6.7a, M7.7a, M8.1a |
| services/deletion.py:68-92 | profile delete | M7.8, M8.4 |
| domain/cp.py:14-41; domain/encounters.py:65-111 | cpm/cp/hp; rolls | M6.3a, M7.2, M8.3a |
| bot/walker.py:27, :50-61, :111-157, :172-199, :201-213, :261-286, :288-315, :344-410 | id; registration; route; home; recovery; `open_encounter`; `encounter_state`; run/throw (confirm flags :357, :383; cleared :282-283) | M6.3b, M6.6d, M7.5a, M8.1c |
| bot/screens.py:9-37; screens_catch.py:32-89; bot/storage.py:18-170 (paging :29-39, :122-128); bot/bag.py:12-147; bot/route.py:9-42 | UI | UI rows |
| bot/admin_channels.py:16-32, :116-120, :160-188; bot/mod.py:15-19, :47-81, :125-159; bot/research.py:88, :116 | admin/mod patterns; research refusals | M7.4c, M7.7a, M7.8, M8.1b |
| bot/share.py:66-71, :82-104 | permission check; reserve then send | M8.2b |
| bot/client.py:83-89, :131-136, :152-197; bot/heartbeat.py:30-41 | commands; `on_ready`; drain; task start/stop | M7.4c, M8.2b, M8.3b, M8.4 |
| bot/account.py:15-23 | privacy text read from `POKEWALKER_PRIVACY_PATH` | G-F2 |
| tests/test_lure.py:1-45; tests/test_walker_router.py:39-64 | SQLite + fake-interaction harness | tests |

Research anchors: battle-system.md:14-23, :25-33, :39-65, :84-88; discord-gym-design.md:23, :27,
:31, :43, :70, :94; move-data-sources.md:45-49; candy-transfer-evolution.md:117-121;
items-and-catching.md:91-92, :97, :116; storage-and-data-model.md:39-41; adaptation.md:74-76;
pokeapi-forms.md:296, :315-334, :338-346. README: D13 :36, D23 :53, D24 :54, D28 :60, D30 :62,
D31 :98-110, D32 :64, D40 :147-155, D40b :161-162, D41 :163-164, D44 :177-178, D45 :179-183,
D49 :59, D54 :225-230, D55 :231-234, D56 :235-236, D60 :315-373 (nonce :346-347), D61 :377-400.

### 3.2 Do-not-touch

Everything in the v1 list (PLAN v1 :62-68) plus: `docs/features/pokewalker-bot/**` (closed v1
plan and tickets; **README.md and privacy.md are owner-only** — a changed number or sentence is an
owner edit, never a row edit). Generated pairs `content/{artifact/content.json,manifest.json}` and
`tests/fixtures/content_mini/content/**` change only by rebuild (`python -m content.build`;
the mini pair via `write_artifacts`, test_content_emit.py:159) in **M6.1a, M6.1b, M6.2, M7.1**;
`tests/test_content_integrity.py:45-49` counts only in M6.1b; `content/balance/*.json` only in
M6.2/M7.1; `deploy/**` unchanged (the sweep is in-process); migrations `0001`–`0010` immutable (C3).
Amendments M6.8a–i: generated pairs also change by rebuild in **M6.8d** (M6.8a leaves them
unchanged); `tests/test_content_integrity.py:45-49` counts also in **M6.8d**; migrations
`0001`–`0016` immutable (amendment 2 adds `0017`).

### 3.3 Layout (new files)

```
content/build/evolutions.py  M6.1a   services/evolution.py M6.3a   bot/evolve.py M6.3b
content/balance/{evolution,battle,survivor_table}.json  M6.2/M7.1   services/capacity.py M6.6a
domain/battle.py M7.2   services/gyms.py M7.4a/M7.4b/M7.6a   bot/gyms.py M7.5a/M7.6b
services/raids.py M8.2a/M8.3a/M8.4   bot/raid.py M8.3b   contracts/gym-battle.md (C7) M7.2
pokewalker/db/migrations/00NN_{star_piece,capacity,route_unlock_backfill,gyms,raids}.sql
                                                M6.5a, M6.6a, M6.7b, M7.4a, M8.1a
pokewalker/db/migrations/0016_pokemon_form.sql  M6.8b   (0015_raids.sql landed with M8.1a)
pokewalker/db/migrations/0017_storage_overflow.sql  M6.8k (landed 166660b; unused since Q22, always NULL)
```

## 4. Decisions

### 4.1 Planner choices (numbers the requirements leave open; Q-series, after v1's P1–P17)

Owner decisions 2026-11-05 (owner chat, relayed by the coordinator) settle every G-A and G-6
question; each item below is marked **Decided**. The owner numbered G-A questions in brief
order: G-A Q1 = sweets (here Q2), Q2 = Star Piece (Q3), Q3 = expansion (Q4), Q4 = thresholds and
Q5 = locked current routes (Q5); G-6 Q6–Q11 match Q6–Q11 here.


- **Q1 Evolution recipes (D40, D54, D55, D56).** From `pokemon_evolution.csv` rows with
  `is_default=1` (pokeapi-forms.md:334) whose source and target resolve: source = the
  `required_pokemon_form_id` form when it is a retained identity, else the species default; target
  = the `evolved_pokemon_form_id` form when it is a retained identity or an **evolution-target
  record**, else the default identity of `evolved_species_id`. A null `required_pokemon_form_id`
  (wildcard) row attaches only to the species default identity, never to a regional source
  (pokeapi-forms.md:319-332; all 25 regional sources with children have explicit rows).
  `region_id` is stripped like other conditions, so an ordinary source keeps both its ordinary
  and its regional target as branch choices (12 such sources at the pin, §3 Round 3). The three D52 branch forms
  (§3 Branch targets) and, from M6.8d, the 62 non-default Alcremie forms (Q15) become
  `evolution_targets` records — full identity shape (stats, family,
  names, sprites), kind `form`, never in `identities`, so routes, tier pools and starters never see
  them; `storage.identify` resolves them. Kept condition: `gender_id` only, mapped at import to
  the strings `pokemon.gender` stores (1 → `'female'`, 2 → `'male'`; 0001_core.sql:112). Item =
  `trigger_item_id` or `held_item_id`. Identical normalized recipes (source, target, gender, item)
  are deduplicated; each keeps a stable `edge_id`, and preview/confirm carry the `edge_id`, never
  the target alone (Alcremie: 63 recipes, one per sweet × cream, Q15). More than 25 distinct
  items per source, or more than 25 recipes for one (source, item), makes the build PENDING
  (Discord select limit); a source with more than 25 recipes is chosen item first, then a recipe
  of that item (Q15). The `shed` row is dropped (D56); Phione/Manaphy have no edge.
  Candy: family max depth 1 → 50; depth 2 → 25 for 0→1, 100 for 1→2 (D40). Gender varieties
  (graph.py:30) resolve the target `pokemon_id` by the Pokémon's own gender.
- **Q2 Evolution items.** Kinds = distinct item identifiers from Q1 (≤ 50 ids at the pin). Each
  kind is an ordinary one-unit bag item. One shared resolver `items.resolve_item` turns the table
  placeholder `evolution_item` into one uniform kind (items-and-catching.md:97; none → 100
  Stardust) for **every** table roll: finds (M6.4a) and gym income (M7.4b). The Bag sells any kind
  for 500 Stardust (D55); conversion 100 each (D61). Kind pickers page 10 per screen (bot/storage.py
  paging). **Decided (owner decision 2026-11-05, G-A):** held sweets count as evolution items and the player picks which
  sweet/recipe to use (the per-sweet `edge_id` choice of Q1).
- **Q3 Star Piece — Decided (owner decision 2026-11-05, G-A): count model like the Lure.** ×1.5 Stardust, floored, on the
  player's next **10 Stardust rewards** (catch Stardust and find `stardust` bundles only); a
  persisted counter `active_effects.remaining_rewards` is decremented in the same transaction that
  grants the boosted Stardust; the effect ends at 0; one active, re-activation refused without
  consuming; coexists with a Lure. The 30-minute / `expires_at` model is dropped. Star Piece rows
  keep `remaining_encounters = 0`, so the lure's one-active index (0007:24) and lure queries
  (items.py:166-170, :188) never see them.
- **Q4 Expansion (D44).** `profiles.storage_limit` / `bag_limit` (default 250): +50 storage for
  5,000 Stardust up to 1,000; +50 bag units for 2,500 up to 1,000 (storage-and-data-model.md:39-41);
  never charge at the cap; rare pockets unchanged. Every `limits()['storage'|'bag_units']` reader
  moves to the profile value (M6.6b–e).
  At owned ≥ limit `catching.throw` returns `storage_full` and spends nothing unless the Q22
  storage warning was confirmed for that encounter revision (catching.py:72-75; M6.8v). A
  confirmed catch is pending (Q22) and not counted: at limit 300 the catch from 299 stores on
  Done, the next throw warns, and a confirmed catch at 300/300 offers only Send for research or
  Upgrade storage. Nothing is ever stored over the limit.
  **Decided (owner decision 2026-11-05, G-A):** prices and caps approved as planned.
- **Q5 Route unlocks (D45) — Decided (owner decision 2026-11-05, G-A).** Lifetime awarded steps in this server =
  `SUM(awarded_c)` over `step_events` (never pruned). Refreshing Field and Noisy Forest free;
  `unlock_steps`: Rugged Road 1,000, Beautiful Beach 2,500, Suburban Area 5,000, Dim Cave
  **8,000**, Blue Lake **12,000**, Volcano Path **18,000**. A player whose current route is locked
  under these thresholds is **moved to Refreshing Field** when unlocks ship, by one idempotent
  backfill migration (M6.7b); queued encounters keep their frozen `route_id`. Afterwards a
  current route is always unlocked (steps never decrease; switching needs an unlocked target).
- **Q6 Battle ruleset (v2).** battle-system.md §3 values in `battle.json`: fast power 6 / +10
  energy / 1 tick; charged 60 / −50 / 2 ticks; charge-when-affordable both sides; STAB 1.2; type
  factors super 1.6, **neutral 1.0**, resisted 0.625, immune 0.390625 from the pin's
  `type_efficacy` (200/100/50/0); damage `floor(0.5×power×atk/def×STAB×eff)+1`; simultaneous
  completion ticks, substitution without a tick; 120-tick draw. **Moves are type templates:** each
  combatant's fast and charged move has its own first type, so no move roster, import or
  provenance question exists (move-data-sources.md:45-49 is thereby reduced, not contradicted).
  Combat Attack/Defense/HP = `(base+iv)×cpm` as cp.py:25-41. Defender battle HP per D32, frozen at
  Start. Deterministic: the simulation runs **inside the writer job** (≤ 120 ticks × ≤ 3 attackers;
  no leased worker, battle-system.md:86 is unnecessary at this size). **Decided (owner decision 2026-11-05, G-6):**
  type-template moves approved.
- **Q7 Gym shape.** Individual holders; one defender per gym; one held gym per player per server
  (D23); ≤ 10 gyms per server, names 1–32 chars unique per server (discord-gym-design.md:23, :31);
  `/walker-admin gyms create|remove|list` (Manage Server, reason, audit, README.md:89-96). Players
  use `/walker → Gyms` only (ephemeral; no channel binding; D10). Attackers ≤ 3, ordered, picked
  from paged lists (≤ 25 options per select); 600 s cooldown after a completed battle (D40b); one
  battle per gym at a time (writer serializes). The party preview saves the defender's
  `deployment_id`; Start refuses `stale` if the gym's active deployment differs; Recall and Rewards
  likewise recheck the saved `deployment_id` and its holder inside the confirm job (M7.5a). Win: defender ends
  `defeated`; the pre-chosen nominee deploys if the cap still allows, else the result says
  "cleared". Loss/draw: nothing changes. **Server boundary (D10):** `gym_deployments` and
  `gym_battles` carry `guild_id` with composite FKs to `gyms(gym_id,guild_id)` and
  `profiles(profile_id,guild_id)`, and every gym read/write filters by the session's `guild_id`
  (M7.4a–M7.6a); a foreign-server gym id is refused with nothing written. **Decided (owner decision 2026-11-05, G-6):** ≤ 10
  gyms per server approved.
- **Q8 Gym income (D13, D23) — Decided (owner decision 2026-11-05, G-6), changed: to the reward inbox.** One receipt per
  completed hour `gym_hour:<deployment_id>:<n>`; roll → `items.resolve_item` (Q2) → rows in
  `inbox_items` under `milestone_id='gym_income:<deployment_id>:<n>'`, claimed with the existing
  **Claim** like milestones and the survivor roll (D59: what fits moves; nothing converts) — **not**
  `items.grant`, so review-8 #6's "finds and `/checkin` only" rule is unchanged. The inbox shows
  "Gym income: <gym> hour n" (M7.5b); the home line reads "Rewards waiting: N" (M7.4b). Paid on **Rewards**, on any end, and by the sweep when it
  ends a tenure. An ended deployment is immutable: no later payout, no second end, so a
  return freezes eligibility and an exclusion's forfeit is permanent (M7.4b).
- **Q9 Survivor roll (D60).** On `expired` without defeat: one roll from `survivor_table.json` +
  500 Stardust into `inbox_items` under `milestone_id='survivor:<deployment_id>'`; WLT is a rare
  pocket of 1, so a second waits in the inbox. **Decided (owner decision 2026-11-05, G-6):** as planned.
- **Q10 Expiry.** `gyms.settle(conn, now, rng)` runs before every gym read/mutation and in a 60 s
  in-process sweep task through the writer; restarts never extend tenure (discord-gym-design.md:70).
  Raid expiry rides the same sweep job (M8.4); ticket use first settles its own guild's expired
  spawn (M8.2a), so `/raid` and ticket use never disagree between sweeps. **Decided (owner decision 2026-11-05, G-6):** as
  planned.
- **Q11 Announcement at most once (D60).** Three writer jobs: (1) spend + insert spawn with
  `post_state='pending'` and the **checked `channel_id`** (the transaction refuses `channel_changed`
  if the configured channel differs from the one whose permission was checked); (2) set `attempted`
  **before** `channel.send(embed, nonce=<first 25 hex chars of spawn_id>)` — discord.py 2.7.1 adds
  `enforce_nonce: true` to every nonce'd send (§3 Nonce); (3) `sent` + message id. Announcement
  and restart recovery use the stored `channel_id`. `attempted` is never posted again; `pending`
  at startup means no send started. No refund ever. A library without automatic `enforce_nonce` is
  an owner stop (dependency or README change), never a `nonce`-only fallback. **Decided (owner decision 2026-11-05, G-6):**
  at most once, no refund on a failed post, as planned.
- **Q12 Raid encounters.** Rows in `encounters` with `raid_spawn_id`; the queue triggers,
  `queue_size` and `open_encounter` exclude them, except that Back from a Master Ball or shiny-Run
  confirmation reopens the selected raid encounter. `/raid` renders the saved encounter by state
  (catch panel, terminal result, or "already joined" when the encounter was deleted with a profile).
  `raid_participation(guild_id,user_id,spawn_id)` has no profile FK; its `encounter_id` is
  `ON DELETE SET NULL`; rows are deleted at spawn expiry (D28). `world_spawns.spawned_by_profile_id`
  is `REFERENCES profiles ON DELETE SET NULL` (D28 without cancelling the spawn, D60).
- **Q13 Moderation and deletion.** exclude → `end_deployment('excluded')` forfeits unpaid hours
  (README.md:103); reset/delete-data cascade the deployment rows, paying nothing (D28);
  `gym-recall` → `mod_recall` pays completed hours (README.md:106), survivor forfeited (D60);
  deployed Pokémon cannot be sent, powered up, evolved or made companion (D30) — SQL triggers in
  the gyms migration plus UI refusals (M7.7a–c).
- **Q14 Help text.** `content/help.md` (2,087 bytes; ≤ 4,096 chars, client.py:39-40) gains one line
  per new feature in the row that adds it (docs, not production).
- **Q15 Alcremie forms (D49, D52, D54) — Decided (owner decision 2026-11-05, G-6 smoke).**
  Evolving Milcery with a sweet sets the topping; the player picks one of the 9 creams; all 63
  forms are reachable. The 62 non-default forms become `evolution_targets` like the D52 branches
  (graph `EVOLUTION_ONLY`), still excluded from encounters, routes and pools; the pin's 63 rows
  give 63 recipes. Recipe limit: ≤ 25 items per source and ≤ 25 recipes per (source, item); a
  source with > 25 recipes picks the item, then a recipe of that item only. `pokemon.form_id`
  (nullable, NULL = default form) persists the form; `identify` reads it from rows and dicts;
  evolution writes the target's `pokemon_id` and `form_id`; gym battle snapshots carry it. Each
  form hotlinks its verified `869-<form_identifier>.png` / `shiny/…`; the default keeps
  `869.png`. No new content source. Existing evolved Alcremie (`form_id` NULL) stay Vanilla Cream
  Strawberry Sweet. Labels name the exact form. README D52 lists only Lycanroc and Urshifu;
  README is owner-only, so this extension lives here.
- **Q16 In-context actions — Decided (owner decision 2026-11-05, G-6 smoke).** No new prices,
  services or receipts. (1) **Buy & evolve (500 Stardust)**: `items.buy_evolution_item` then
  `evolution.evolve` in one writer job; any refusal raises, so the purchase rolls back; rechecks
  revision, recipe, item still missing and Candy; a full bag refuses as Buy does.
  (2) *Superseded by Q22 (owner decisions 2026-11-05 second batch, 2026-11-06).* M6.8f/g shipped
  storage-full **Expand storage** / **Send for research** shortcuts back to the same encounter;
  M6.8v replaces that screen with the Q22 warning and M6.8w deletes `catch_expand_storage`,
  `catch_return`, `catch_research` and the research `resume` return. The closed M6.8f/g tickets
  are not edited. (3) Inbox with non-rare items
  waiting: **Expand bag (+50, 2,500 Stardust)** and **Convert items** return to the inbox (no
  auto-claim). Numbers come from `capacities.json` / `evolution.json`.
- **Q17 "King�s Rock" — owner request 2026-11-05; terminal artifact.** The pin, importer,
  artifact and DB hold U+2019 (§3). M6.8a adds the cheap guard (no `name_en` contains U+FFFD);
  no importer change.
- **Q18 Caught result: Send for research — Decided (owner decision 2026-11-05).** Every caught
  result — the fresh throw result, `/walker`/`home` recovery and `/raid` reopen, i.e. every
  `render_terminal` caller (§3) — shows row-1 **Send for research** (`catch_send`) while the
  Pokémon linked by `source_encounter_id` is `owned`; fled, ran and sent results do not. The
  button lives in `render_terminal`, so no caller is missed. `catch_send` sends only that
  Pokémon through the Details single flow (bot/research.py `single` :115-132 → `review` with its
  Candy → `storage_send_confirm` → services/research.py `send`): Unlock for shiny/legendary,
  favorite/companion/deployed refusals, 120-second expiry and `research:<preview UUID>` receipts
  unchanged. The flow carries `caught: {encounter_id}`; with it, **New review** rebuilds the
  single review of that same Pokémon (never the bulk picker), confirm shows "Sent 1 Pokémon ·
  +1 <family> Candy · 0 Stardust." with **Done** (`ack`: acknowledge, next result or home), and
  Cancel returns via `home` (recovery shows the result again). Recovery still shows no Share or
  catch controls. No new price, receipt type or service (M6.8j).
  A pending catch (Q22) shows the same button; its send goes through `send_pending_reviewed`
  and inserts the Pokémon as `sent`, never owned (M6.8r, M6.8t). Unlock, expiry and receipt rules
  as above.
- **Q19 Full storage: warn, catch over the limit, forced choice — Superseded by Q22 (owner
  decision 2026-11-06).** The owner rejected catches sitting in storage before the result menu
  is confirmed. Kept, under Q22: the pre-throw warning ((1) → Q22 (3), M6.8v); the Send/Upgrade
  pair and `capacity.expand` reuse ((3) → Q22 (2), M6.8s reworks M6.8k's `catch_upgrade`); the
  sweep placement, cadence and restart catch-up ((5) → Q22 (5), M6.8x). Dropped: the over-limit
  catch and `profiles.overflow_uid` as the pending record ((2): `0017` landed at 166660b and
  stays, always NULL); the allowlist lock ((4) → Q22 (4)); receipt `research:overflow:<uid>` (→
  `research:auto:<encounter_id>`). M6.8l, M6.8m, M6.8n and M6.8q are superseded unbuilt; their
  ticket files are not edited (as M6.8f/g). M6.8k (built) is reworked by M6.8s.
- **Q20 Home Claim button removed — Decided (owner decision 2026-11-05).** `screens.home` drops
  `('Claim', 'claim')` (bot/screens.py:32); home keeps Inbox (N) (:34-36); the inbox's Claim
  (bot/milestones.py:154) is the only claim entry; the `claim` handler stays (:196) (M6.8o).
- **Q21 `/walker-admin channels add-all <reason> [count=true]` — Decided (owner decision
  2026-11-05).** Entry gate as `add` (admin_channels.py:25-33). Before the writer job the
  handler fetches the member (`interaction.guild.fetch_member`, HTTP — the bot has no Members
  intent, client.py:79-80) and requires Manage Server from those fresh roles; a fetch failure
  refuses with nothing written. Exclusion is rechecked inside the job as `change` does (:54-55).
  Residual window: a role removed between the fetch and the commit (writer queue only) is not
  seen — **owner-accepted 2026-11-06** (amendment 2 review round 3 #1; same rule as `add`/`remove`). `channels add`/`remove` keep their current check (possible follow-up, out of scope).
  Reason rule and per-channel upsert as `add` (:41-78).
  Eligible: the guild's text and announcement channels (`guild.text_channels`;
  voice/stage/forum/category/threads excluded) where the bot has View Channel, not already
  enabled. One writer job; one `mod_audit` row `channels_add` per newly enabled channel (none
  for skips, so a repeat writes nothing). Reply "Enabled N channels; skipped M (no access); K
  already enabled. Channels created later are not added automatically." No new table or
  receipt. New subcommand of the global group: the owner runs `python -m pokewalker
  sync-commands --global --yes` (README.md:188-198) after delivery; never a row action (M6.8p).
- **Q22 Pending catch: the result menu decides where a caught Pokémon goes — Decided (owner
  decisions 2026-11-06). Replaces Q19.**
  (1) *Pending.* A caught Pokémon is pending until its result menu is confirmed. **Pending =
  `encounters.state='caught' AND acknowledged_at IS NULL AND NOT EXISTS (SELECT 1 FROM pokemon
  WHERE source_encounter_id=encounters.encounter_id)`** — the `pokemon` row is written only by
  Done/Upgrade (owned) or by research (`sent`). With no row, a pending Pokémon is not in storage,
  not counted toward `storage_limit` and not listed or selectable anywhere (§3 amendment 3 map).
  The encounter already holds every column the catch copied into `pokemon` (catching.py:116-120)
  and the result screen already renders from it (screens_catch.py:19, :69), so **no schema
  change**. Pokédex `caught_at`, `check_and_award` and catch rewards stay in the throw receipt
  (catching.py:121-139). Rejected: a new `pokemon.state` value — the CHECK (0001_core.sql:117)
  needs a table rebuild, and `DROP TABLE pokemon` under `foreign_keys=ON` (db/__init__.py:32)
  fires `ON DELETE SET NULL` on `profiles.companion_uid` (0001_core.sql:18) and `ON DELETE
  CASCADE` on `gym_deployments` (0014_gyms.sql:16) inside the migration transaction
  (db/__init__.py:45-46); a flag column — every `state='owned'` reader would need the filter; a
  staging table — duplicates the encounter; `profiles.overflow_uid` (M6.8k, landed) as the
  pointer — its FK to `pokemon(pokemon_uid)` can only name an existing row (the column stays,
  always NULL, to avoid a migration; M6.8k landed 166660b before Q22, and dropping the column would need a migration nobody needs).
  (2) *Menu* (M6.8s, M6.8t). Room (owned < limit): **Done** (`ack`: inserts the row from the
  encounter with `caught_at = resolved_at`, acknowledges, home) or **Send for research**
  (`catch_send`, the Q18 flow; the Pokémon is inserted as `sent` with Candy, ledger and
  `research:<preview UUID>` receipt). Full: "Storage is full (owned/limit)." + **Send for
  research** or **Upgrade storage space (+50, 5,000 Stardust)** (`catch_upgrade` →
  `capacity.expand` with the limit the menu showed; same price, step and
  `expand:<session>:<revision>` receipt; disabled with "Not enough Stardust." / "Storage is at
  the maximum capacity."; success stores, acknowledges, home). Done on a stale screen at full
  storage is refused and re-renders the menu. Both menus render with the recovery flag
  (screens_catch.py:74, :80): no disabled catch controls. A throw that leaves a pending catch
  answers with this menu directly (walker.py:481-482 → `pending_menu`, M6.8s), so the first
  screen after a catch is the menu. **Share — decided (owner decision 2026-11-06, owner chat,
  relayed by the coordinator):** Share is only after Done, from Storage details ("Share this
  Pokémon", D19 at docs/features/pokewalker-bot/README.md:42; the Storage button,
  bot/storage.py:66); the pending menu has no Share (`share.allowed` needs an owned row,
  share.py:16), and **no result screen shows Share**: M6.8z deletes Share from
  `render_terminal` (screens_catch.py:80-81, its only result-screen producer), so a stored catch
  replayed from an older screen (walker.py:476-482) has none either, and drops the then-unread
  `share_allowed` key (walker.py:380; `rg -n "share_allowed" pokewalker`). This narrows D19's
  "Share this catch" on the fresh result; README.md is not edited, and share.py keeps its
  result branch (share.py:55-77) with no producer (no third file).
  Stored, unacknowledged results (existing data) keep M6.8j's Done + Send.
  (3) *Warning* (M6.8v). As Q19 (1): after exclusion, terminal/stale and raid expiry
  (catching.py:65-71), at owned ≥ limit the throw returns `storage_full` (nothing spent) unless
  `selection.storage_confirm` equals the revision; Walker shows "Storage is full (owned/limit)."
  with **Confirm throw** / **Back**; Back and reopen clear the flag; every revision re-warns.
  (4) *One pending catch* (M6.8s, M6.8y). `recover_terminal` sends a pending catch to its menu
  (M6.8s) and recovers it before any other unacknowledged result (M6.8y; query
  walker.py:263-266), so a fresh `/walker` (`open` → `home` → `before_home`, :107-108, :185-188)
  and Home from any valid session open **directly on the menu** with working buttons
  (amendment-2 review r1 #4). The router (M6.8y), after the handler lookup (:139-141), sends
  `open_encounter`, `select_ball`, `select_berry`, `pick_ball`, `pick_berry`, `throw`,
  `master_confirm`, `run`, `run_confirm` to the menu while a catch is pending ("confirm first");
  `/raid` (M6.8y; after opt-out, and only for a member with a profile: exclusion, then the
  pending lookup, before `raids.join`; no profile → `raids.join` as today) opens it in a new session
  without joining. Storage, Bag, gyms, research picker and Pokédex stay usable — the pending
  Pokémon is invisible there. The lock only reads.
  (5) *Fallback* (M6.8x). The 60-second sweep (client.py:148-161) calls the session-free
  `research.auto_send(conn, now, content)` after `raids.expire`, same writer job and
  `Walker.clock()` `now` (one-job/one-clock pins unchanged). Every pending catch with
  `resolved_at + 900 ≤ now` that is not shiny (`encounters.shiny`) and whose species is not
  `is_legendary`/`is_mythical` (content identity) is sent to research — `send_pending`, receipt
  `research:auto:<encounter_id>`, action `research`, profile owner — and its encounter
  acknowledged in the same transaction; an excluded profile is skipped and retried. **Exempt
  catches are never auto-sent**: they stay pending, holding the lock, until the player confirms.
  Cadence one tick per 60 s; the first tick runs at once on ready, so a catch that fell due while
  the bot was down is sent on the first tick after restart; sent at most one tick (plus writer
  queue) after the 15-minute deadline; until then Done, Send and Upgrade still resolve it and the
  first commit wins (one writer). A failing tick rolls back whole (gym settlement and raid
  expiry included) and the next tick retries (client.py:155-161). No notice. "Confirmed" =
  `acknowledged_at` set — only `ack` writes it (walker.py:281-283): Done, post-send Done and
  Upgrade; Later, recovery, `/raid` reopen and Share do not count — or the Pokémon is no longer
  pending (sent).
  (6) *Existing data.* Every catch at 3e56b30 wrote its row inside the throw receipt
  (catching.py:116-120), so no existing caught encounter matches the pending predicate: nothing
  becomes pending, hidden or swept; stored unacknowledged results recover as today. No migration,
  no backfill, no activation timestamp. Tests model such rows with a legacy stored-result fixture
  (M6.8u), separate from the pending fixture.
  (7) *Raids* (M6.8y). `raids.join` creates the raid encounter (services/raids.py:57-60); the
  throw is `catching.throw` (walker.py:473-475), so a raid catch is pending like any other;
  `raids.expire` deletes only queued/revealed raid encounters (:83) and nothing deletes
  `world_spawns`, so a pending raid catch survives expiry; `/raid` with it opens its menu. A
  World Legendary catch is exempt from the sweep and stays pending — and holds the lock,
  including against joining the next spawn — until Done, Send or Upgrade. Only raid.py's entry
  changes.
  (8) Q16 (2) stays superseded: M6.8v removes the shortcut screen, M6.8w its handlers.
  Row shape: nine rows of ≤ 2 files (r services/research.py; x services/research.py +
  client.py; s walker.py + screens_catch.py; z screens_catch.py + walker.py; t
  bot/research.py; y walker.py + raid.py; u catching.py; v catching.py + walker.py; w
  bot/research.py + bot/storage.py). Activation (M6.8u)
  is one five-line deletion placed after the menu, send, lock and sweep exist; the warning
  (M6.8v) cannot precede it — a confirmed throw at full storage would store over the limit
  through the still-present insert — and the handler deletion (M6.8w) follows its producer's
  removal. Review r1 split the sweep off M6.8r (→ M6.8x) and moved recovery order, the router
  lock and `/raid` off M6.8s/t (→ M6.8y) to keep every ticket ≤ 4,096 bytes; review r2 split
  the result-screen Share removal off M6.8s into M6.8z (same two files) for the same reason.

### 4.2 Contracts

| Contract | Change | Row |
|---|---|---|
| C1 content-artifact.md | append `evolutions` (with `edge_id`), `evolution_targets`, `evolution_items`, `type_chart`, counts; `importer_version` 2; `schema_version` 1 | M6.1a, M6.1b |
| C3 persisted-state.md | star_piece effect; capacity columns; evolution transition; gyms/deployments/battles + triggers; spawns (channel, SET NULL attribution)/participation/raid encounters | M6.5a, M6.6a, M6.3a, M7.4a, M8.1a |
| C4 balance-tables.md | full find table, v1.1 rates, `evolution.json`, expansion, `unlock_steps`; `battle.json`, `survivor_table.json`, gym/WLT capacities | M6.2, M7.1 |
| C5 discord-commands.md | per UI/command row | each UI row |
| C7 `contracts/gym-battle.md` (new) | engine inputs/outputs, determinism, tick rules, D32 HP | M7.2 |
| C1 content-artifact.md | ≤ 25 items per source and ≤ 25 recipes per item; non-default-form sprite key; 62 Alcremie targets, counts 65/587 | M6.8a, M6.8d |
| C3 persisted-state.md | `pokemon.form_id`; evolution sets it; battle snapshots carry it | M6.8b, M6.8c, M6.8i |
| C5 discord-commands.md | `evolve_group` + group-bound pick, `evolve_buy_confirm`, `catch_expand_storage`, `catch_return`, `catch_research`, `inbox_expand_bag`, `inbox_convert` | M6.8d–h |
| C5 discord-commands.md | `catch_send` on every caught result (M6.8j, landed :13-16, :44, :326-328, :431-432); M6.8k paragraph (:340-351) rewritten for the pending menu, Done stores, Upgrade, throw response (M6.8s) and recovery first, router lock (M6.8y); Share (:43-45) "no result screen shows Share" (M6.8z); :326-328, :431-432 "owned" → "owned or pending" and the pending send sentence after :431-432 (M6.8t); M8.3b (:3-20) `/raid` opens the menu (M6.8y); sweep tick sentence (`rg -n "Each tick serializes gyms.settle"` → :826) adds `research.auto_send` (M6.8x); storage warning (:307 "Storage placeholder" sentence) and M6.8f/g paragraphs marked superseded (M6.8v); home without Claim; `channels add-all` | M6.8s, M6.8z, M6.8t, M6.8x, M6.8y, M6.8v, M6.8o, M6.8p |
| C3 persisted-state.md | research receipt sentence (:271-275) names `send_pending`, new paragraph "M6.8r pending send" (M6.8r); paragraph "M6.8x auto-send", sweep order (:939-942) (M6.8x); `0017` paragraph (:251-255) → "unused since Q22, always NULL" (M6.8s); M1.8 catching (:195-220): `CatchResult.pokemon` None, the throw commits no Pokémon row, the row is written later manually (Done/Upgrade owned, Send `sent`) or automatically (M6.8x sweep, `sent`), pre-M6.8u receipts and stored results stay valid and never pending (M6.8u); M1.9 acknowledgment (:222-228): `ack` or the sweep's `auto_send` sets `acknowledged_at` once (M6.8x); recovery shows the row or else the pending encounter, Done/Upgrade store + acknowledge + session in one transaction (M6.8s); Send writes the `sent` row, Candy, ledger and receipt in one transaction and its Done acknowledges (M6.8t); pre-M6.8u throw receipts keep the Pokémon UID, later ones hold none (:227, M6.8u); :206 and :656-658 "full storage" → "full storage without a confirmed storage warning" (M6.8v) | M6.8r, M6.8x, M6.8s, M6.8t, M6.8u, M6.8v |

Producer/consumer greps are in each ticket's Read line.

### 4.3 Verification decision (Decide before dispatch)

Owner/repo reconciliation: PIPELINE.md:10 `test_cmd` and AGENTS.md:12-25 do not conflict; the
owner's standing exception (plan-skill Step 3 skipped) concerns review, not tests. `lint_cmd:
none`. Focused row coverage = the row's named tests via `python -m unittest discover -s tests -p
"test_<module>.py"` plus `git diff --check`; rebuild rows add `python -m content.build --check`.
RED evidence in the row's commit body.

- **SI-1 (explicit source increment):** rows M6.1a–M6.7b. Usable outcome: v1.1 playable in the test
  guild. Audience: owner smoke at G-6 and the reviewer. Reason: v1.1 ships alone per D35 and v2
  reuses its seams. Checkpoint: independent GO + exact-tree full `test_cmd` at G-6.
- **Final feature:** all rows; checkpoint at G-F2. Live Discord checks are owner smoke, never a row
  Accept. Themes M6/M7/M8 and lettered sub-rows are not increments.
- **Amendments M6.8a–q:** focused Verify per ticket (`boundary=final feature (G-F2)`); SI-1 stays
  qualified at 1ac0157 and is not re-run; no new source increment — the G-F2 exact-tree full
  `test_cmd` and `content.build --check` cover them.
- **Amendment 3 (M6.8r–z):** focused Verify per ticket (`boundary=final feature (G-F2)`); M6.8u
  runs the whole unit suite as its focused coverage because its fallout crosses modules; no new
  source increment; G-F2's exact-tree full `test_cmd` covers all rows.

### 4.4 Row bounds, order and briefing

Every impl row has a ticket (`tickets/<ID>.md`, ≤ 4 KB, no status). **Production file** = any
shipped file under `pokewalker/` or `content/build/`, SQL migrations included, wiring lines
included; JSON tables, regenerated artifacts, fixtures, tests, contracts and docs are listed but not
counted. Every row is `seam`: ≤ 2 production files and ≤ 300 production lines, measured over the
whole row (`git diff --numstat <base> -- <listed production files>`); a third file or line 301 is a
stop and a re-split, never an abstraction added to save files. Rows run in table order in one
checkout. The only parallel pair is **M7.2 ∥ M7.3, after M7.1 is done** (M7.2 reads `battle.json`;
M7.3 reads `capacities.json`); their production files are disjoint (AGENTS.md:72-79). A row needing
a new owner decision ends its batch at a 🚦.

**Cross-row rules** (each affected ticket repeats the one it needs):
- *Clock:* gameplay time is `Walker.clock()` (UTC epoch, walker.py:43); `WalkerBot.clock` is
  `time.monotonic` (client.py:74) for drain deadlines only. Sweeps, gym, raid and command
  handlers never call `bot.clock()` or `time.time()` for deadlines; tests inject both clocks
  with different values.
- *Receipt replay first:* ownership and exclusion → an authorized existing receipt returns its
  saved result → only then state, revision, balance, deployment, channel or holder guards
  (powerup.py:44-58; persisted-state.md:280-289). A new guard never changes a replay.
- *Confirm rechecks:* every confirmation re-reads, inside its writer job, what its preview
  showed (revision, holder + `deployment_id`, limit, channel, guild) and refuses `stale`.
- *Schema/signature fallout:* a migration that adds a column updates positional `INSERT …
  SELECT` fixtures and `tests/test_receipt_owner.py:46-70` `legacy_schema`; a signature change
  updates every test caller found by `rg` over `tests/`; new renderer state keys use `.get()`
  defaults that reproduce v1 output (literal-state tests: test_route.py:158,
  test_conversion.py:203-210, test_storage.py:395-402, test_screens.py:82).

### 4.5 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` — PIPELINE.md:15; plugin default agrees; no feature exception. |
| Candidate | Final accepted v2 feature. SI-1 (§4.3) is for owner review, not delivery. |
| Action scope and targets | **Local branch only** (owner instruction 2026-11-05): no push, no PR, no release/tag, no installation, no deployment, no consumer migration. Repository `Farkoal2128/Pokewalker-Discord-Bot`, `origin` as `git remote -v`; main `main`; feature-branch policy (PIPELINE.md:14). Q21 adds a slash subcommand: after the feature lands the owner runs `python -m pokewalker sync-commands --global --yes` (README.md:188-198). Not a row action; G-F2 lists it as an owner smoke prerequisite. |
| Predicates and workflow | Independent integration GO; exact-tree full `test_cmd` PASS on the final candidate; `python -m content.build --check` PASS; ancestry on `feature/pokewalker-bot-drive` (648bb37) through `docs/pokewalker-v1.1-v2-plan`; owner-committed privacy.md disclosure of raid-participation retention (D28). |
| Owner authority | G-A approved 2026-11-05: implementation on the local Home `feature/pokewalker-v1.1-v2`. Integration/publication/deployment: **unresolved**; G-F2 records the local-only outcome and asks nothing further. |

**G-P:** inapplicable — explicit local-only/no-publication scope (plan-structure.md, "Approved-plan
publication before build"). The plan author never pushes.

### 4.6 Gate record

Decision maker is `owner` for G-A and G-6, `coordinator` for G-F2's technical predicates with
`owner` holding delivery authority and the privacy text. Evidence is an owner message naming the
gate; silence, review GO and headers grant nothing.

## 5. Step table

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A plan approval and implementation Home; Q1–Q5 **decided** (owner decision 2026-11-05, §4.1) | 🚦 | — | — | ✅ approved for build (owner 2026-11-05); Home `feature/pokewalker-v1.1-v2` cut from `docs/pokewalker-v1.1-v2-plan` |
| 2 | [M6.1a](tickets/M6.1a.md) evolution CSVs + `evolutions.py` loader: recipes, items, type chart; C1 | impl | seam | M | ✅ done · 643f741 · GO review r2 |
| 3 | [M6.1b](tickets/M6.1b.md) evolution-target records + artifact keys/counts; C1 | impl | seam | M | ✅ done · c5037e5 · GO review r1 |
| 4 | [M6.2](tickets/M6.2.md) v1.1 balance tables + manifest rebuild; C4 | impl | seam | S | ✅ done · 8ed32cc · GO review r1 |
| 5 | [M6.3a](tickets/M6.3a.md) evolution service; `identify` resolves targets (D40, D54, D15) | impl | seam | M | ✅ done · f28e617 · GO review r1 |
| 6 | [M6.3b](tickets/M6.3b.md) evolve screens + handler registration | impl | seam | M | ✅ done · 2ce157a · GO review r1 |
| 7 | [M6.4a](tickets/M6.4a.md) evolution items: shared resolver, purchase, conversion (D55, D61) | impl | seam | M | ✅ done · 9d4b613 · GO review r1 |
| 8 | [M6.4b](tickets/M6.4b.md) Bag: kind names, paged buy and convert pickers | impl | seam | S | ✅ done · 121933b · GO review r1 |
| 9 | [M6.5a](tickets/M6.5a.md) Star Piece migration + effect service (Q3) | impl | seam | M | ✅ done · 5ba6765 · GO review r1 |
| 10 | [M6.5b](tickets/M6.5b.md) Star Piece catch boost + Bag activation | impl | seam | S | ✅ done · fc4e695 · GO review r1 |
| 11 | [M6.6a](tickets/M6.6a.md) capacity migration + `capacity.py` (D44) | impl | seam | S | ✅ done · 4670e5e · GO review r1 |
| 12 | [M6.6b](tickets/M6.6b.md) catch storage check and `grant` bag cap from the profile | impl | seam | S | ✅ done · 8ed398d · GO review r1 |
| 13 | [M6.6c](tickets/M6.6c.md) Claim caps from the profile; ordinary units via `bag_units` | impl | seam | S | ✅ done · 8848093 · GO review r1 |
| 14 | [M6.6d](tickets/M6.6d.md) Storage/Details: Evolve entry, limit header, Expand storage | impl | seam | S | ✅ done · 1f29d8e · GO review r1 |
| 15 | [M6.6e](tickets/M6.6e.md) Bag units line + Expand bag | impl | seam | S | ✅ done · bb3b76e · GO review r1 |
| 16 | [M6.7a](tickets/M6.7a.md) route unlocks by lifetime steps (D45, Q5) | impl | seam | S | ✅ done · e0e8532 · GO review r1 |
| 17 | [M6.7b](tickets/M6.7b.md) route-unlock backfill: locked current routes → Refreshing Field (Q5) | impl | seam | S | ✅ done · 8135622 · GO review r1 |
| 18 | G-6 SI-1 checkpoint: independent GO + full `test_cmd`; owner v1.1 smoke; open questions restated (Q6–Q11 already **decided**, owner decision 2026-11-05, §4.1) | 🚦 | — | — | ✅ SI-1 technical GO; full PASS 1ac0157; owner smoke 2026-11-05/06 on 4ed0965: all checks PASS except storage-full catch (redesigned → Q22; retest in G-F2 smoke) |
| 19 | [M7.1](tickets/M7.1.md) v2 tables: `battle.json`, `survivor_table.json`, gym/WLT capacities; manifest rebuild; C4 | impl | seam | S | ✅ done · dd82ee7 · GO review r1 |
| 20 | [M7.2](tickets/M7.2.md) battle engine `domain/battle.py`; C7 (after M7.1; ∥ M7.3) | impl | seam | M | ✅ done · 95770bb · GO review r1 |
| 21 | [M7.3](tickets/M7.3.md) rare pockets from `capacities.json` (after M7.1; ∥ M7.2) | impl | seam | S | ✅ done · 52d44d5 · GO review r1 |
| 22 | [M7.4a](tickets/M7.4a.md) gyms migration (guild-scoped FKs) + `services/gyms.py` lifecycle | impl | seam | M | ✅ done · 746d973 · GO review r1 |
| 23 | [M7.4b](tickets/M7.4b.md) gym income + survivor roll | impl | seam | M | ✅ done · 5d4554b · GO review r1 |
| 24 | [M7.4c](tickets/M7.4c.md) `/walker-admin gyms` + 60 s settle sweep | impl | seam | M | ✅ done · d5445aa · GO review r2 |
| 25 | [M7.5a](tickets/M7.5a.md) player gym screens + registration | impl | seam | M | ✅ done · 06a7004 · GO review r2 |
| 26 | [M7.5b](tickets/M7.5b.md) home **Gyms** button + survivor inbox label | impl | seam | S | ✅ done · 9ba7cfa · GO review r2 |
| 27 | [M7.6a](tickets/M7.6a.md) battle transaction | impl | seam | M | ✅ done · 9171ca7 · GO review r2 |
| 28 | [M7.6b](tickets/M7.6b.md) paged party, outcome and result screens | impl | seam | M | ✅ done · 7b4a7ff · GO review r1 |
| 29 | [M7.7a](tickets/M7.7a.md) research `deployed` reason (D30) | impl | seam | S | ✅ done · 7871aab · GO review r1 |
| 30 | [M7.7b](tickets/M7.7b.md) power-up and evolve refuse deployed (D30) | impl | seam | S | ✅ done · 55472bd · GO review r1 |
| 31 | [M7.7c](tickets/M7.7c.md) Details: deployed line, disabled actions, companion refusal (D30) | impl | seam | S | ✅ done · 2a80799 · GO review r1 |
| 32 | [M7.8](tickets/M7.8.md) `/walker-mod gym-recall`, exclude hook, status line (D31, D28) | impl | seam | S | ✅ done · a967288 · GO review r2 |
| 33 | [M8.1a](tickets/M8.1a.md) raids migration + `queue_size` (D60) | impl | seam | M | ✅ done · e94e447 · GO review r1 |
| 34 | [M8.1b](tickets/M8.1b.md) `/walker-admin raids on\|off` | impl | seam | S | ✅ done · af65fca · GO review r1 |
| 35 | [M8.1c](tickets/M8.1c.md) walker: raid rows outside the queue; confirm Back keeps the raid | impl | seam | S | ✅ done · 1f21148 · GO review r1 |
| 36 | [M8.2a](tickets/M8.2a.md) spawn, expiry settlement, at-most-once announcement (Q11) | impl | seam | M | ✅ done · f80feaf · GO review r3 · supervisor accepts duplicate risk if library retry exceeds Discord nonce window |
| 37 | [M6.8a](tickets/M6.8a.md) recipe limit per item, form-specific sprite keys, U+FFFD guard (Q15, Q17); C1 | impl | seam | S | ✅ done · 86e7b5d · GO review r1 |
| 38 | [M6.8b](tickets/M6.8b.md) `pokemon.form_id` migration `0016` + form-exact `identify` (Q15); C3 | impl | seam | S | ✅ done · 0353b65 · GO review r1 |
| 39 | [M6.8c](tickets/M6.8c.md) evolution writes and resolves the exact target form (Q15); C3 | impl | seam | S | ✅ done · 90ce464 · GO review r2 |
| 40 | [M6.8d](tickets/M6.8d.md) Alcremie 63 sweet × cream targets + sweet → cream picker; rebuild; C1, C5 | impl | seam | M | ✅ done · 0f4828c · GO review r1 |
| 41 | [M6.8e](tickets/M6.8e.md) Evolve **Buy & evolve** in one atomic confirm (Q16); C5 | impl | seam | S | ✅ done · d65858e · GO review r1 |
| 42 | [M6.8f](tickets/M6.8f.md) catch storage-full **Expand storage**, back to the same encounter (Q16); C5 | impl | seam | S | ✅ done · c0b294c · GO review r1 |
| 43 | [M6.8g](tickets/M6.8g.md) catch storage-full **Send for research**, back to the same encounter (Q16); C5 | impl | seam | S | ✅ done · de0294a · GO review r2 |
| 44 | [M6.8h](tickets/M6.8h.md) inbox **Expand bag** and **Convert items**, back to the inbox (Q16); C5 | impl | seam | S | ✅ done · cf381f3 · GO review r2 |
| 45 | [M6.8i](tickets/M6.8i.md) gym battle snapshots carry `form_id` (Q15); C3 | impl | seam | S | ✅ done · 03bbb76 · GO review r1 |
| 46 | [M8.2b](tickets/M8.2b.md) Bag WLT use + startup resume | impl | seam | S | ✅ done · d2bf09e · GO review r1 |
| 47 | [M8.3a](tickets/M8.3a.md) raid join + expired-throw refusal (Q12) | impl | seam | M | ✅ done · 139e6c5 · GO review r1 |
| 48 | [M8.3b](tickets/M8.3b.md) `/raid` command, reopen by state | impl | seam | M | ✅ done · 43b42e3 · GO review r1 |
| 49 | [M8.4](tickets/M8.4.md) raid expiry sweep + cleanup and retention acceptance cases | impl | seam | S | ✅ done · f3432ca · GO review r1 |
| 50 | [M6.8j](tickets/M6.8j.md) every caught result: **Send for research** (Q18); C5 | impl | seam | M | ✅ done · 0d3fb40 · GO review r1 |
| 51 | [M6.8k](tickets/M6.8k.md) over-limit record `0017_storage_overflow.sql`, Send/Upgrade choice (Q19); C3, C5 | impl | seam | M | ✅ done · 166660b · GO review r1 — superseded by Q22: M6.8s reworks its walker.py code; `0017` stays unused |
| 52 | [M6.8r](tickets/M6.8r.md) pending send service: `send_pending`, `send_pending_reviewed` (Q22 (2), (5)); C3 | impl | seam | S | ✅ done · 303929c · GO review r2 |
| 53 | [M6.8x](tickets/M6.8x.md) 15-minute auto-send in the 60-second sweep (Q22 (5)); C3, C5 | impl | seam | S | ✅ done · 8642d58 · GO review r1 |
| 54 | [M6.8s](tickets/M6.8s.md) pending catch menu: Done stores, Upgrade, recovery, throw response (Q22 (1), (2), (4)); C3, C5 | impl | seam | M | ✅ done · 6b2c968 · GO review r1 |
| 55 | [M6.8z](tickets/M6.8z.md) no Share on any result screen (Q22 (2)); C5 | impl | seam | S | ✅ done · 239211e · GO review r1 |
| 56 | [M6.8t](tickets/M6.8t.md) Send for research on a pending catch (Q22 (2), Q18); C3, C5 | impl | seam | S | ✅ done · c0abf80 · GO review r1 |
| 57 | [M6.8y](tickets/M6.8y.md) one pending catch: recovery first; router and `/raid` open its menu (Q22 (4), (7)); C5 | impl | seam | M | ✅ done · 6f7809b · GO review r1 |
| 58 | [M6.8u](tickets/M6.8u.md) activation: the catch no longer stores — the result is pending (Q22 (1), (6)); C3 | impl | seam | M | ✅ done · cf42ae1 · GO review r1 |
| 59 | [M6.8v](tickets/M6.8v.md) storage-full warning before the throw; storage-full shortcut screen removed (Q22 (3), Q4, Q16 (2)); C3, C5 | impl | seam | M | ✅ done · 187d4e9 · GO review r2 |
| 60 | [M6.8w](tickets/M6.8w.md) superseded M6.8f/g shortcut handlers deleted (Q16 (2)) | impl | seam | S | ✅ done · 75b39fb · GO review r1 |
| 61 | [M6.8o](tickets/M6.8o.md) home without the Claim button (Q20); C5 | impl | seam | S | ✅ done · cc1f9fa · GO review r1 |
| 62 | [M6.8p](tickets/M6.8p.md) `/walker-admin channels add-all` (Q21); C5 | impl | seam | S | ✅ done · 6213681 · GO review r1 |
| 63 | G-F2 final: independent GO, exact-tree full `test_cmd`, owner privacy disclosure, owner v2 smoke; local only | 🚦 | — | — | ✅ local technical GO (6985a03; post-review full test_cmd PASS on ab9beb7); owner privacy disclosure approved and committed (c2a3eb2); owner v2 smoke 2026-11-06 on c2a3eb2 PASS (home without Claim, channels add-all + repeat, gym create/battle win+loss/deploy/mod recall/inbox Claim, raids on, WLT spawn + single announcement, /raid join/Master Ball catch/pending reopen/Done, expiry sweep); draw and post-expiry throw covered by tests only |

Order and tree after each row (every row green; no control points at a missing handler):
- **50 (j):** new key `caught` keeps the M6.8g `resume` flow and the storage-full shortcuts
  working unchanged.
- **51 (k)** built: `0017` and the `overflow_uid` choice; nothing sets the pointer, so it is inert.
- **52 (r)** needs j: `send_pending` and `send_pending_reviewed` exist with no caller.
- **53 (x)** needs r: the sweep calls `auto_send`, live but finding no pending catch in
  production until 57; tests seed one.
- **54 (s)** replaces M6.8k's pointer code: the menu (Send renders, works from 56), Done stores,
  Upgrade, recovery to the menu, the throw response; inert for the same reason.
- **55 (z)** independent of s: Share leaves every result screen (live at once — stored results
  lose it; Storage details keep it).
- **56 (t)** needs r, s: pending Send; inert.
- **57 (y)** needs s, x: recovery order, router lock and `/raid` entry; inert.
- **58 (u)** needs r–t, x, y, z: one five-line deletion makes every new catch pending behind the
  menu, send, lock and sweep already in place (service → sweep → menu → send → entry points →
  activate). Full storage still refuses the throw and the M6.8f/g shortcut screen still works on
  owned rows for one row.
- **59 (v)** needs u: the warning replaces the refusal; a confirmed catch at full storage answers
  with the Send/Upgrade menu. v cannot precede u (over-limit insert).
- **60 (w)** needs v: handlers without a producer are deleted.
- **61 (o), 62 (p):** independent one-file rows.

## 6. Briefs

Impl rows 2–17 and 19–62 have ticket files. Gate briefs:

- **G-A:** `owner`. **Q1–Q5 decided** (owner decision 2026-11-05, §4.1: sweets count and the
  player picks the recipe; Star Piece count model; expansion as planned; thresholds 1,000 /
  2,500 / 5,000 / 8,000 / 12,000 / 18,000; locked current routes move to Refreshing Field).
  **Approved for build (owner 2026-11-05)**; implementation Home `feature/pokewalker-v1.1-v2`,
  cut from `docs/pokewalker-v1.1-v2-plan`. Accept: that owner message (recorded in the row). README is owner-only; the decided numbers live in
  PLAN Q2–Q5 and the tables, not in README. Stop if: the owner wants publication — then G-P is
  re-planned, not improvised.
- **G-6:** `owner` + `coordinator`. **Q6–Q11 decided in advance** (owner decision 2026-11-05,
  §4.1; Q8 changed to inbox income). Technical: SI-1 independent GO and `Tests: tree <sha>
  <test_cmd> PASS` on the M6.7b candidate; `content.build --check` PASS. Owner: smoke v1.1 in the
  test guild (evolve incl. a branch, an Alcremie sweet and a gender gate; buy an item from page 2;
  Star Piece over its 10 boosted rewards; expand; locked route; a pre-unlock profile moved to
  Refreshing Field); restate that Legendary pacing/featured group and catch-screen research send
  remain undecided and no v2 row depends on them. Stop if: the owner wants a curated move roster —
  M7.1/M7.2 are re-briefed with a content-source ADR first (PIPELINE.md:73).
- **G-F2:** `coordinator` verifies §4.5 predicates. **Prerequisite (owner):** a committed
  `docs/features/pokewalker-bot/privacy.md` edit disclosing that a raid participation record
  (server, user, spawn) survives delete-data until the spawn expires (D28; wording proposed in the
  M8.4 commit body; the runtime text is the operator file read by bot/account.py:15-23). Without it
  G-F2 stays `pending`. The owner also runs `python -m pokewalker sync-commands --global --yes`
  (README.md:188-198) before smoking `channels add-all`. `owner` smokes v2 (create gym, deploy, battle win/loss/draw, recall +
  rewards to the inbox + Claim, survivor inbox, raids on, WLT spawn, `/raid` join/catch/reopen/expiry)
  and the v1.1 amendments (Milcery → a sweet, then a cream; the form's own picture; Buy & evolve;
  a fresh catch shows Done / Send for research and is absent from Storage and its count until
  Done stores it; Send sends it (never in Storage) and its Done goes home; with a catch left
  unconfirmed, a new `/walker`, Home's Open encounter and `/raid` land on its menu and both
  buttons work; a throw at full storage → "Storage is full (N/N)" with Back (same encounter, also
  a raid) and Confirm throw; the confirmed catch answers with only Send for research / Upgrade
  storage space; Upgrade adds 50 slots, stores it and goes home; an ordinary catch left alone for
  15 minutes is sent to research within about a minute with no click, while a shiny, Legendary or
  Mythical one (a raid Legendary) stays on its menu; no result screen shows Share, and Share
  appears on Storage details after Done; home has no Claim and Inbox → Claim still claims;
  `/walker-admin channels add-all` enables the visible text channels; inbox with items waiting → Expand bag and Convert items, back to the
  inbox; a gym battle with a cream Alcremie shows its form) and records the local-only outcome.
  No integration, publication or deployment is asked.

## 7. Review responses

### Round 1 — 2026-11-05 (MUST 6, SHOULD 11, NIT 0)

| # | Finding | Disposition |
|---|---|---|
| 1 | Branch targets missing from the artifact | Fixed: Q1; M6.1b emits `evolution_targets` (3 records, §3); M6.3a `identify` resolves them; tests evolve to each branch and reopen details. |
| 2 | Target does not identify the recipe | Fixed: Q1 dedupe + `edge_id` (M6.1a); M6.3a/b carry `edge_id`; one-sweet test. |
| 3 | Selects exceed 25 options | Fixed: Q1 ≤ 25 recipes (M6.1b PENDING); M6.4b paged buy/convert; M7.6b paged slots; ≤ 25 assertions. |
| 4 | Gym income grants the placeholder | Fixed: Q2/Q8 shared `items.resolve_item` (M6.4a), used by M7.4a (now M7.4b after round 2); forced-roll test. |
| 5 | Spawn attribution survives deletion | Fixed: M8.1a `REFERENCES profiles ON DELETE SET NULL`; M8.4 test keeps the spawn. |
| 6 | Permission checked for another channel | Fixed: Q11; M8.1a `world_spawns.channel_id`; M8.2a `channel_changed`; announce/resume use it. |
| 7 | Stale defender has no comparison value | Fixed: Q7; M7.6b saves `deployment_id`; M7.6a compares it. |
| 8 | Type factor sets contradict | Fixed: Q6/M7.1 four factors incl. neutral 1.0; neutral test in M7.2. |
| 9 | Claim counts WLT as bag space | Fixed: M6.6c uses `items.bag_units`; M7.3 makes it data-driven; 999 + ticket case. |
| 10 | Raid confirm Back leaves the raid | Fixed: M8.1c `open_encounter` reopens the selected raid while a confirm flag is set; tests with and without a queued encounter. |
| 11 | Completed raid renders as catchable | Fixed: Q12; M8.3b renders by state; participation `encounter_id` SET NULL → "already joined". |
| 12 | Nonce fallback changes D60 | Fixed: verified (§3 Nonce); fallback removed; M8.2a asserts the library payload; owner stop otherwise. |
| 13 | Privacy disclosure not a prerequisite | Fixed: §4.5 predicate and G-F2 owner prerequisite. |
| 14 | M6.2 must rebuild the manifest | Fixed: §3.2 authorizes M6.2/M7.1 (and M6.1a/b) rebuilds; M6.2 text corrected. |
| 15 | Wiring hides files from bounds | Fixed: §4.4 counting rule (migrations count); split M6.1, M6.3–M6.6, M7.4–M7.7, M8.1–M8.3 into lettered rows (36 impl rows, each ≤ 2 production files); whole-row line bound in every Stop if. Old M6.6a–c content regrouped as M6.6a–e; Evolve button moved to M6.6d; raid `open_encounter` clause moved to M8.1c; M7.3 drops its bag.py edit (bag.py:17, :28, :113 already read `items.RARE`). |
| 16 | Parallel batch has dependencies | Fixed: §4.4 M7.1 first, then M7.2 ∥ M7.3. |
| 17 | Capacity test off by one | Fixed: Q4; M6.6b: 299 → 300 succeeds, next refused, nothing spent. |

### Round 2 — 2026-11-05 (MUST 3, SHOULD 4, NIT 1)

| # | Finding | Disposition |
|---|---|---|
| 1 | `items.boost` hits the local `items` list | Fixed: M6.5b imports `boost` directly (no cycle) and forbids `items.boost`; a successful-catch test with and without a Star Piece. |
| 2 | Recipe vs Pokémon gender values | Fixed: Q1 and M6.1a map `gender_id` 1/2 to `'female'`/`'male'` (the stored strings); C1 records it (M6.1b); M6.3a tests the emitted Combee edge through `options`. |
| 3 | Gym transactions lack a server boundary | Fixed: Q7; M7.4a composite FKs to `gyms(gym_id,guild_id)` and `profiles(profile_id,guild_id)`, every gym read/write filtered by session `guild_id`; cross-guild refusal tests in M7.4a (deploy/retire/end), M7.4b (pay), M7.4c (remove by name), M7.5a (view/deploy/recall/rewards), M7.6a (battle). The extra text split old M7.4a into M7.4a (schema + lifecycle) and M7.4b (income + survivor); admin + sweep is now M7.4c. |
| 4 | Capacity/route tickets omit v1 test updates | Fixed: M6.6b (test_storage.py:373-381, 250-row boundary), M6.6c (test_milestones.py:173-178; :213-223 stays unchanged — the round-1 claim was wrong), M6.6e (test_conversion.py:71-73), M6.7 (test_route.py:38-136 seed 40,000 steps; field-name format kept). |
| 5 | Raid migration breaks positional fixtures | Fixed: M8.1a makes the three encounter fixtures explicit and runs their suites; M8.1c's "unchanged" promise corrected. Same root cause found for the new `pokemon` column: M7.4a updates four pokemon fixtures. |
| 6 | Expired spawn blocks a ticket until the sweep | Fixed: `expire` moved into M8.2a and run first by `spawn` for its guild; test for ticket use after expiry with cleanup pending; M8.4 now schedules it and proves the acceptance cases. |
| 7 | Evolve both absent and disabled | Fixed per coordinator preference (disabled with an explanation, since the button belongs on Details): M7.7b leaves `options` unchanged and refuses `evolve`; M7.7c keeps four disabled buttons with a "recall it to …" line. Reviewer's "absent" alternative not taken. |
| 8 | Survivor inbox shows a UUID | Fixed: M7.5b maps category `survivor` to "Gym survivor reward" in bot/milestones.py `_milestone_name` (:44-68), with a display test. |

### Round 3 — 2026-11-05 (MUST 3, SHOULD 4, NIT 0)

| # | Finding | Disposition |
|---|---|---|
| 1 | Sweep uses the monotonic bot clock | Fixed: M7.4c `_sweep_once` uses `self.walker.clock()` (UTC, walker.py:43), never `bot.clock` (`time.monotonic`, client.py:74); M8.4 reuses that `now`; fake-clock tests with deliberately different clocks in both. |
| 2 | Region rule drops ordinary branches | Fixed: Q1 and M6.1a — wildcard rows attach only to the species default; `region_id` stripped; 12 ordinary sources keep both targets (§3 Round 3); M6.1b `test_committed_pikachu_chooses_raichu_or_alolan_raichu`. |
| 3 | Recall confirm lacks a holder check | Fixed: Q7; M7.5a saves `deployment_id` at view and rechecks deployment + holder (and guild) inside the recall-confirm and rewards jobs; replaced-holder test. |
| 4 | No payout cutoff after return | Fixed: Q8; M7.4b makes ended deployments immutable (no later `pay_hours`, `end_deployment` a no-op); late-reward, repeated-end and post-exclusion tests. |
| 5 | Deployed guard changes receipt replay | Fixed: M7.7b orders ownership/exclusion → receipt replay → deployed guard; power-up → deploy → replay and evolve → deploy → replay tests. |
| 6 | Mini fixture cannot feed the loader | Fixed: M6.1b replaces the header-only mini `pokemon_evolution.csv` with the pinned header and the 1→2, 2→3 rows, updates its hash, keeps the mini-rebuild test green; branch cases run on the committed artifact. |
| 7 | `apply_finds` test caller missed | Fixed: M6.4a updates tests/test_finds.py:35 (`self.content`); `convert` callers in tests keep working through `content=None`. |

**Round 3 self-pass** (same classes, all rows; recorded as §4.4 cross-row rules):
- *Clock:* M7.4c admin gym times, M7.5a handlers, M7.6b battle start, M7.8 gym calls (mod.py uses `time.time()` at :57, :134), M8.2b spawn/`resume_pending`, M8.3b `/raid` join and session expiry now name `walker.clock()`.
- *Receipt replay before new guards:* M6.3a evolve, M6.4a buy, M6.5a Star Piece (guards inside `compute`, as `activate_lure`), M6.6a expand, M7.4a deploy, M7.6a battle (before `settle`), M8.2a spawn (before `expire`).
- *Confirm rechecks:* M6.6a `expand(..., expected_limit, ...)` refuses `stale`; M6.6d/M6.6e pass the previewed limit and re-preview.
- *Schema fallout:* tests/test_receipt_owner.py:46-70 `legacy_schema` must drop each new migration's additions — assigned to M6.6a, M7.4a, M8.1a (M8.1a restores the 0001 triggers because a column a trigger uses cannot be dropped; M6.5a needs nothing, `active_effects` is already dropped there).
- *Signature/state fallout:* bare `Walker(SimpleNamespace(content=...))` fixtures (test_receipt_owner.py:41, test_finds.py:182) constrain M6.3b/M7.5a handler registration; literal-state renderer tests (test_route.py:158, test_conversion.py:203-210, test_storage.py:395-402, test_screens.py:82) stay unchanged via `.get()` defaults in M6.4b, M6.5b, M6.6d, M6.6e, M6.7, M7.5b, M7.7c, M8.2b.

### Round 4 — 2026-11-05 (MUST 0, SHOULD 1, NIT 1; final pass)

| # | Finding | Disposition |
|---|---|---|
| 1 | Deploy confirm can target a removed gym | Fixed: M7.4a `deploy` requires the gym to exist in the session's guild with `retired_at IS NULL` after receipt replay, else `stale` with nothing written; tests in M7.4a (service) and M7.5a (confirm after removal). |
| 2 | Gym audits render the server as `user:` | Fixed without a new kind: gym create/remove keep the existing `target_kind='guild'` (v1 `sharing` precedent, admin_channels.py:176-181; 0009 CHECK `user|channel|guild`) with the gym name in the action, so no `mod_audit` rebuild is needed for a display-only kind; M7.8 renders `guild` targets as `server:<id>` (mod.py:120) with a display assertion. |

### Owner decisions G-A/G-6 — 2026-11-05 (owner chat, relayed by the coordinator)

Recorded as **Decided** in §4.1 (Q2–Q11) and in the G-A/G-6 rows and briefs; plan approval and
the implementation Home (G-A) and the G-6 technical checkpoint and smoke stay `pending`.

| Decision | Plan effect | Tickets changed |
|---|---|---|
| G-A Q1 sweets count; player picks the recipe | Q2 default confirmed; per-sweet `edge_id` unchanged | none |
| G-A Q2 Star Piece count model (next 10 Stardust rewards) | Q3 rewritten; `remaining_rewards` column + one-active index; decrement inside the granting transaction | M6.2, M6.5a (also updates test_lure.py:294-295 positional fixture), M6.5b |
| G-A Q3 expansion as planned | Q4 decided | none |
| G-A Q4 thresholds 8,000 / 12,000 / 18,000 for the last three | Q5 numbers | M6.2, M6.7a |
| G-A Q5 locked current route → Refreshing Field | Q5; new backfill migration row | **M6.7b (new)**; M6.7 renamed M6.7a; migrations renumbered: M7.4a → `0014_gyms`, M8.1a → `0015_raids` |
| G-6 Q6, Q7, Q9, Q10, Q11 as planned | decided | none |
| G-6 Q8 income to the inbox, not `items.grant` | Q8 rewritten; review-8 #6 widening removed | M7.4b, M7.5a, M7.5b (gym-name labels need a DB lookup in the inbox handlers), M6.6b, M7.8 (wording) |

Forced splits/re-scopes: the move-to-Refreshing-Field backfill is a SQL migration, a third
production file for the route row, so M6.7 split into M6.7a (screens + lifetime steps) and M6.7b
(backfill only). README is owner-only and was not edited; the decided numbers live in PLAN and
the balance tables.

### Round 5 — 2026-11-05 (MUST 0, SHOULD 1; final pass) and G-A approval

| # | Item | Disposition |
|---|---|---|
| 1 | Run can keep an expired raid encounter | Fixed: M8.1c `run` (also reached by shiny Confirm Run) refuses a raid encounter whose spawn has expired, inside the writer job and before the `ran` update, leaving it `revealed` for cleanup; confirm Back skips an expired raid; tests `test_run_after_raid_expiry_refused_encounter_stays_revealed`, `test_shiny_run_confirm_after_raid_expiry_refused_encounter_stays_revealed`; M8.4 adds `test_run_and_shiny_run_after_expiry_then_cleanup_removes_encounter_no_terminal_result`. |
| — | Home "Rewards waiting: N milestones" with hourly inbox income (own flagged risk) | Fixed: M7.4b (the row that adds gym income to the inbox) changes screens.py:17 to "Rewards waiting: N" and deliberately updates test_milestones.py:232; M7.4b is now 2 production files. |
| — | G-A | Recorded: owner approved the plan for build on 2026-11-05; Home `feature/pokewalker-v1.1-v2` cut from `docs/pokewalker-v1.1-v2-plan`; header `approved — in execution`; G-6 and G-F2 stay pending. |

### Owner decisions from the G-6 smoke — 2026-11-05 (owner chat, relayed by the coordinator)

| Decision | Plan effect | Tickets changed |
|---|---|---|
| A. Sweet sets the topping, player picks the cream; 63 forms; exact sprite or none | Q15; recipe limit per item; `pokemon.form_id`; 62 targets; two-step picker; labels replaced; battle snapshots carry the form | **M6.8a–d, M6.8i (new)**; form migration `0016_pokemon_form.sql` (M8.1a landed as `0015_raids.sql`); M7.7b re-anchors `evolve` (guard order unchanged) |
| B. Buy & evolve; catch storage-full Expand storage / Send for research; inbox Expand bag / Convert items | Q16; reuse only | **M6.8e–h (new)**; M8.1c (fallout below); M6.3b's "Buy in Bag" sentence replaced in C5 by M6.8e (closed ticket not edited) |
| C. "King�s Rock": fix decoding, add a test | Q17: cp1252 terminal artifact; guard test only | M6.8a (guard) |

Forced splits: Alcremie needs content build (evolutions.py, emit.py, graph.py), schema
(migration, storage.py), evolve (evolution.py, bot/evolve.py) and gym snapshots (gyms.py) — seven
production files — so five rows, each leaving the tree green. Catch storage-full touches
walker.py, storage.py and research.py, so two rows. README stays owner-only.

### Owner decisions, second batch — 2026-11-05 (owner chat, relayed by the coordinator)

| Decision | Plan effect | Tickets changed |
|---|---|---|
| D. Send for research on every caught result, recovered and reopened ones included | Q18; Details single flow reused; button in `render_terminal` | **M6.8j (new)** |
| E. Full storage: warn before the throw, catch over the limit, forced Send/Upgrade, lock, 15-minute fallback (owner confirmed); M6.8f/g shortcuts superseded | Q19, Q4, Q16 (2), §2; C3 `0017_storage_overflow.sql` and the fallback receipt; C5 | **M6.8k, M6.8l, M6.8q, M6.8m, M6.8n (new)**; M6.8f/g closed tickets not edited |
| F. Home Claim button removed | Q20 | **M6.8o (new)** |
| G. `/walker-admin channels add-all` | Q21; owner `sync-commands` after delivery (§4.5, G-F2) | **M6.8p (new)** |

Forced splits: Q18/Q19 touch bot/research.py, screens_catch.py, a migration, walker.py, raid.py,
services/research.py, client.py, catching.py and storage.py — nine production files — so six
rows of ≤ 2 files. The order keeps every tree coherent: the old shortcut screen goes (m)
before its handlers (n), and over-limit catching (m) only after its record (k), lock (l) and
timed fallback (q). The record/choice and the lock are separate rows because together they
exceeded the 4 KB ticket limit (plan-structure split rule); the fallback is its own row
because its two files (services/research.py, client.py) fit no other row. Q20 (screens.py) and Q21 (admin_channels.py) would be a third file
anywhere else, so they are one-file rows.

**UNVERIFIED (paper):** line estimates (j ≈ +25, k ≈ +50 and 1 SQL line, l ≈ +30, q ≈ +25,
m ≈ +25/−20, n ≈ −35, p ≈ +55); SQLite add/drop of a `REFERENCES` column checked only on the
local Python SQLite 3.45.1, not the bot's patched build; that Discord's single-member GET
(`fetch_member`) needs no privileged intent (library docstring read, API not exercised);
discord.py `guild.text_channels` including announcement channels (reported by review r1, not
re-read). Owner preferences not asked: no notice after the fallback send; an excluded player's
overdue choice stays pending until inclusion (`send` refuses excluded members); `/raid` shows
the choice even when no raid is active; Cancel in the catch flow goes through home's recovery.

### Amendment 2 review round 1 — 2026-11-05 (MUST 9, SHOULD 1; amend2-review-1.md)

| # | Finding | Disposition |
|---|---|---|
| 1 (MUST) | Fallback can send the wrong Pokémon | Fixed: explicit `profiles.overflow_uid` (`0017_storage_overflow.sql`, M6.8k) set in the crossing catch's receipt `compute` (M6.8m); pending = that UID still owned, never "oldest unacknowledged". Test `test_catch_to_limit_then_raid_over_limit_locks_only_crossing_catch` (A to 300/300, `/raid` B to 301/300: choice and fallback name B only). |
| 2 (MUST) | The lock leaves bypass routes | Fixed: router-level guard after the existing checks and before every handler, with an allowlist bound to the pending encounter (M6.8l); fresh `/walker` via `recover_terminal` (M6.8k) and `/raid` before `raids.join` (M6.8l). Tests click every other registered action from old Home, Storage and Details sessions (favorite, companion, deploy, Open encounter included) and `/raid`. |
| 3 (MUST) | Expired preview's New review opens the picker | Fixed: the catch flow carries `caught`; `research` (New review) with `caught` rebuilds the single review of that Pokémon (M6.8j `test_catch_send_expired_preview_new_review_rebuilds_same_pokemon`; pending variant in M6.8k). Picker actions are not allowlisted, and sending another Pokémon cannot end pending (it is the UID, not the count). |
| 4 (MUST) | Fresh `/walker` recovery does not save the selection | Fixed: `overflow_choice` writes `sessions.selection` itself, as walker.py:215-217 (M6.8k); `test_overflow_fresh_walker_open_saves_choice_and_both_buttons_work` clicks both rendered buttons. |
| 5 (MUST) | Warning runs before terminal, stale and expired-raid handling | Fixed: the warning is the service's `storage_full`, returned only after exclusion, terminal/stale and raid expiry (catching.py:64-71) and only without a confirmed flag (M6.8m); tests `test_storage_warning_after_terminal_stale_and_expired_raid`, `test_storage_warning_back_keeps_raid_with_and_without_queue`, `test_master_ball_at_limit_confirms_each_once`. |
| 6 (MUST) | Recovery results omit Send | Fixed: the button is in `render_terminal`, so all seven callers (walker.py:220, :339, :376, :398, :428; raid.py:59; share.py:77) show it for an owned caught Pokémon; test_walker_ack.py:56, :180 and test_raids.py:1595 updated; `test_catch_send_from_fresh_walker_recovery`, `test_catch_send_raid_reopen_legendary_unlock_then_done` (M6.8j). |
| 7 (MUST) | Row order breaks controls and leaves an unresolved-state gap | Fixed: re-split into j–n (§5 order notes): the old shortcuts keep working until m removes their screen and n their handlers; over-limit catching (m) lands after its record (k) and lock (l); pending no longer depends on `acknowledged_at`. |
| 8 (MUST) | Contradictory rules and an impossible smoke check | Fixed: exact replacement text above for Q4 (:251-252), Q16 (2) (:340-344), G-F2 (:508, :511-512), C3 :266-267, and also §2 (:33-34), header (:4), §4.3 (:379), §6 (:487); C3 :206/:650-652 and C5 :14/:44/:325/:402-414/:704-718/:774 in the tickets. Review records (§7 rounds, amend-review-*.md) untouched. |
| 9 (MUST) | Batch omits the permission recheck | Fixed: the add-all job calls `WalkerAdmin.check_actor` (admin_channels.py:117-121) first; `test_add_all_permission_lost_while_queued_writes_nothing` and `test_add_all_exclusion_committed_while_queued_writes_nothing` (M6.8p). |
| 10 (SHOULD) | Blanket test deletion removes valid coverage | Fixed: M6.8m deletes only tests entered from the removed screen (test_capacity.py:568-662, :683-761, :763-854, :867-930; test_storage.py:452-460) and keeps the helper :563-566 and tests :664-682, :856-865, :932-982; M6.8n removes only `'catch_expand_storage', 'catch_return'` from the mixed test at :960, :967. |

### Amendment 2 review round 2 — 2026-11-05 (MUST 2, SHOULD 0; amend2-review-2.md)

Round-1 items 1–8 and 10 confirmed fixed by the reviewer; round-1 #9 stayed open as round-2 #2.

| # | Finding | Disposition |
|---|---|---|
| 1 (MUST) | The lazy fallback misses the 15-minute deadline (sessions expire 900 s after opening, walker.py:83, :132-133) | Fixed: new row **M6.8q** (step 53, before activation M6.8m): session-free `services.research.settle_overflow(conn, now, content)` runs in the existing 60-second sweep's writer job after `raids.expire` (client.py:148-153), same `now`, so the one-job and one-clock-read pins (test_raids.py:1753, :1773) hold. Same `research:overflow:<pokemon_uid>` receipt via the unchanged `send`; acknowledgment and record clear in the same transaction. Cadence 60 s; restart catch-up on the first tick after ready (client.py:137-146, :156-158). Lazy click path dropped (not free); the lock (M6.8l) only reads. Tests: `test_overflow_sweep_sends_overdue_choice_without_interaction_once`, `test_overflow_choice_before_sweep_wins`, `test_overflow_sweep_catches_up_after_restart`, `test_overflow_sweep_refused_stays_pending_then_retries`; M6.8k/l drop their fallback tests. Order: record (k) → lock (l) → fallback (q) → activate (m). |
| 2 (MUST) | add-all rechecks stale member roles | Fixed: before the writer job M6.8p fetches the member (`interaction.guild.fetch_member`, HTTP; no Members intent, client.py:79-80) and requires Manage Server from the fresh roles; `HTTPException` (NotFound/Forbidden included) refuses with nothing written; exclusion stays rechecked inside the job. `check_actor` is no longer used there (it reads the payload's role IDs). Tests `test_add_all_role_removed_after_interaction_refused` (interaction member unchanged) and `test_add_all_member_fetch_failure_refused_nothing_written`. Residual fetch→commit window and the unchanged `channels add` check are recorded in the ticket and Q21 as a possible follow-up. |

### Amendment 2 review round 3 — 2026-11-06 (MUST 1, SHOULD 1)

| # | Finding | Disposition |
|---|---|---|
| 1 | add-all fresh member fetch runs before the writer-queue wait; a role removed while queued is not seen | **Owner-accepted 2026-11-06** (owner chat): fetch before the job as drafted, same rule as `channels add`/`remove`; recorded in Q21 and M6.8p. |
| 2 | Fallback's atomic cleanup has no failure-after-send test | Fixed: M6.8q adds `test_overflow_sweep_failure_after_send_rolls_back_then_retries_once`. |

### Amendment 2 review round 4 — 2026-11-06 (MUST 0, SHOULD 0, NIT 0; amend2-review-4.md)

| # | Finding | Disposition |
|---|---|---|
| — | MUST 0, SHOULD 0, NIT 0 — "Ship as a paper amendment" | Confirmed by the reviewer: round-3 #1 owner acceptance (Q21, M6.8p, round-3 table) and #2 failure-after-send rollback test (M6.8q) confirmed; M6.8p/M6.8q trims keep the required behavior. |

Paper reviews only. Full records: amend2-review-1.md … amend2-review-4.md.

### Owner decisions, third batch — 2026-11-06 (owner chat, relayed by the coordinator)

| Decision | Plan effect | Tickets changed |
|---|---|---|
| H. Pending catch: a caught Pokémon is not in storage, counted or selectable until its result menu is confirmed (Done / Send for research; Send / Upgrade at full storage); pre-throw warning kept; one pending catch at a time — a fresh `/walker`, Open encounter and `/raid` open directly on its menu; unconfirmed 15 minutes → research by the existing sweep, shiny and Legendary/Mythical exempt forever; existing data unaffected; raids on the same model | Q22 (replaces Q19); Q4, Q16 (2), Q18 touched; C3/C5 per §4.2; G-F2 smoke | **M6.8r–z (new)**; M6.8l/m/n/q superseded unbuilt (tickets kept); M6.8k (built 166660b) reworked by M6.8s; M6.8j, o, p unchanged |
| I. Share is only after Done, from Storage details ("Share this Pokémon", D19); the pending menu has no Share | Q22 (2) (decided; the draft's owner hold is removed); G-F2 smoke | M6.8s (no Share on the menu), M6.8z (no Share on any result screen), M6.8u (test_share.py `caught()` fixture) |

Drive note: the drive overran its pause instruction and landed M6.8k (166660b) before Q22; its walker.py code is reworked by M6.8s and `0017` is kept unused. A half-built M6.8l was stopped and kept only in a local git stash (not part of the plan).

### Amendment 3 review round 1 — 2026-11-06 (MUST 6, SHOULD 3, NIT 1; amend3-review-1.md)

| # | Finding | Disposition |
|---|---|---|
| 1 | MUST: a fresh full-storage catch bypasses the menu — `throw` returns `render_terminal` (walker.py:481-482) | Fixed: M6.8s `throw` sends a pending `caught` result to `pending_menu` (also on read-only replay); `test_throw_response_on_pending_catch_is_the_menu` (room and full, no Home reopen); the real throw response is asserted again in M6.8u (room) and M6.8v (confirmed throw and Master Ball at full) |
| 2 | MUST: `identity = storage.identify(...)` ignores the `(identity, sprite)` pair (storage.py:4-12) | Fixed: `identity, _ = storage.identify(...)` in M6.8r `send_pending` and M6.8x `auto_send` |
| 3 | MUST: M6.8s's both-buttons test needs M6.8t's pending Send (research.py:89) | Fixed: M6.8s keeps rendering, Done and Upgrade tests; `test_fresh_walker_opens_pending_menu_and_both_buttons_resolve_it` moved to M6.8t |
| 4 | MUST: activation fallout list wrong (test_capacity.py:282, test_star_piece.py:337, test_walker_ack.py:99) and legacy fixtures erased | Fixed: M6.8u's list rebuilt from a probe (unit suite on a 3e56b30 export with catching.py:116-120 deleted: 61 application failures/errors; the other 19 are deploy/backup failures an unmodified export shows too on this host) plus two reasoned M6.8s/y effects (test_raids.py:241-258, test_walker_ack.py:93-109); adds test_catching.py :114, :205, :276, :299, the eight M6.8f/g return tests, test_raids.py :1073, :1141, :1623, test_share.py `caught()`, test_star_piece.py :279, :329, test_powerup.py:248; new `store_legacy` stored-result fixture kept separate from `pending_result()`; `caught_result()` uses it so the M6.8j owned-result tests incl. :782 stay on owned rows |
| 5 | MUST: `_pick(conn, session, selection)` cannot resolve batch picks | Fixed: `_pick(conn, session, uid)`; `review` passes the loop uid, `single` the selected uid; revision checks (:101, :128) stay; batch tests test_research.py:218, :235, :327 named as the regression guard |
| 6 | MUST: the room menu adds five disabled catch controls (screens_catch.py:74) | Fixed: `pending_menu` sets `state["recovery"] = True`; test_walker_ack.py:56, :180 assertions kept; `test_pending_menu_with_room_shows_done_and_send_only` asserts no disabled controls |
| 7 | SHOULD: no failure-after-payment Upgrade test | Fixed: `test_pending_upgrade_store_failure_rolls_back_then_retries_once` in M6.8s |
| 8 | SHOULD: no Mythical exemption case | Fixed: M6.8x `test_auto_send_exempts_shiny_legendary_and_mythical_forever` adds non-shiny Mew (151; `is_mythical` true, `is_legendary` false); M6.8r guards add a locked non-shiny Mythical |
| 9 | SHOULD: reviewed pending replay not tested past expiry | Fixed: M6.8r `test_send_pending_reviewed_replays_after_expiry_and_restart`; replay ordered before expiry and the pending check |
| 10 | NIT: false claim that SQLite cannot drop `overflow_uid` | Fixed: base note says dropping works (test_receipt_owner.py:48; reproduced) and the column stays only to avoid an unnecessary migration |
| — | Review's remaining risk: Share-after-Done owner hold | Resolved: owner decision 2026-11-06 recorded as decision I and in Q22 (2); the hold is removed from row 54 |

Also fixed at revision: stale anchors (catching.py `compute` :96-144, rewards :125-139; research
`send` Candy :71-74 and ledger :75-76, unlock :62-64; `catch_upgrade` pointer clear :256-257;
bot/research.py `confirm` :151-163, registrations :182-186; C3 `0017` :251-255, legacy `resume`
redaction :469; Q21 :467-481); the C5 sweep sentence now belongs to the sweep row (M6.8x).

**UNVERIFIED (paper):** line estimates (r ≈ +55, x ≈ +30, s ≈ +55/−45, z ≈ −3, t ≈ +30,
y ≈ +40, u −5, v ≈ +20/−20, w ≈ −40; the 300-line bound holds with margin). M6.8z's claim that
the share handler tests (test_share.py:107-300) pass unchanged is reasoned (they call `share`
directly; share.py:77 then renders a result without Share), not run. M6.8u's fallout list comes from one
probe run (`python -m unittest discover -s tests -p "test_*.py"` with the project venv on a
`git archive 3e56b30` scratch copy with catching.py:116-120 deleted; nothing in the repo changed);
the M6.8r–t/x–z code was not applied in that probe, so the † entries and "pass" claims in M6.8u
are reasoned from that code, not run. The 19 deploy/backup failures fail identically on an
unmodified export on this host (host tooling, not this change). C5 line numbers past :340 are
3e56b30 lines (cite by `rg` at dispatch). A failing auto-send blocks that tick's gym settlement
and raid expiry until it succeeds (accepted under the one-job pin; not probed).

### Amendment 3 review round 2 — 2026-11-06 (MUST 3, SHOULD 0, NIT 0; amend3-review-2.md)

All ten round-1 fixes confirmed by the reviewer.

| # | Finding | Disposition |
|---|---|---|
| 1 | MUST: M6.8y's `/raid` pending check reads `profile["profile_id"]` when `get_profile()` returns None (unenrolled member, other guild) | Fixed: M6.8y runs exclusion and `pending_catch` only when a profile exists; no profile or no pending catch → `raids.join` as today; test_raids.py:1532 (other guild → "No World Legendary is active here.") and :1734 (unenrolled, excluded, opted out) named in Accept as unchanged and passing |
| 2 | MUST: a stored catch replayed from an older screen still shows Share (walker.py:481 → screens_catch.py:80) | Fixed: new row **M6.8z** (step 55; screens_catch.py + walker.py, M6.8s's file scope — split off because M6.8s was at 4,076 bytes) deletes Share from `render_terminal` (:80-81) and the unread `share_allowed` key (walker.py:380); the result-screen Share assertions (test_share.py:75-76, :95; test_catching.py:315) move there from M6.8u; adds `test_stored_catch_replayed_from_older_screen_has_no_share`; Storage-details Share (bot/storage.py:66-67, :198; test_storage.py:351-355) unchanged; C5 :43-45 reworded (M6.8z) |
| 3 | MUST: C3 still requires the Pokémon row in the throw commit (:212-214), the receipt UID (:227) and `ack`-only acknowledgment (:223-224) | Fixed: explicit C3 edits through :195-228, each on its implementing row — M6.8u: M1.8 `CatchResult.pokemon` None, no row in the throw commit, the row written later manually (Done/Upgrade owned, Send `sent`) or automatically (M6.8x sweep), pre-M6.8u receipts/stored results valid and never pending, :227 receipt UID only on pre-M6.8u receipts; M6.8x: `acknowledged_at` set once by `ack` or `auto_send` in the sweep transaction; M6.8s: recovery reads the row or the pending encounter, Done/Upgrade store + acknowledge + session in one transaction; M6.8t: Send's one-transaction write and its Done acknowledgment; §4.2 C3 row updated |

Also at round 2: the C5 "owned" → "owned or pending" edit (:326-328, :431-432) moved from M6.8s
to M6.8t, where pending Send starts working; steps renumbered 55–63.

### Amendment 3 review round 3 — 2026-11-06 (MUST 0, SHOULD 0, NIT 1)

| # | Finding | Disposition |
|---|---|---|
| 1 (NIT) | Activation leaves `uuid4` unused (catching.py:6) | Fixed: M6.8u also deletes that import. |

Verdict "Ship the plan amendment". Full records: amend3-review-1.md … amend3-review-3.md.

### Amendment review round 1 — 2026-11-05 (MUST 5, SHOULD 1)

| # | Finding | Disposition |
|---|---|---|
| 1 | `pokemon.get` crashes on `sqlite3.Row` | Fixed: M6.8b `identify` reads `dict(pokemon).get("form_id")` (rows with or without the column, dicts); test with a real `pokemon` row, a real `encounters` row and dicts. |
| 2 | Gym receipts drop the form | Fixed: M7.6b landed (7b4a7ff), so new row **M6.8i** (`services/gyms.py` only) adds `form_id` to `_battle_snapshot` (:204-205); tests: cream Alcremie as attacker and defender, result sprites, receipt replay, legacy snapshot. C3 row added. |
| 3 | Catch shortcuts lose raid encounters | Fixed: M6.8f keeps the encounter selection and returns via new `catch_return` (sets flag `catch_return`); M6.8g carries it as `resume` (ball kept — the reset limit is gone); tests return to the same encounter with ordinary encounters queued after it and with none. M8.1c fallout below. |
| 4 | Migration fallout misses test_gyms.py | Fixed: M6.8b updates test_gyms.py:362-388 (compare `before`'s columns, assert new columns NULL) and makes it and test_capacity.py:79 expect `user_version` = migration-file count, so M8.1a's `0016` needs no edit there; suites added to Verify. |
| 5 | Cream select accepts another sweet's recipe | Fixed: M6.8d binds `evolve_pick` to the saved current `evolve_item` group for grouped sources; cross-group and no-group refusal tests; Milcery screen tests use the real two-step path. |
| 6 | Obsolete verification blockers | Fixed: the 124 × HTTP 200 check and the terminal diagnosis are recorded (§3); M6.8a's network step, miss list and stops removed; M6.8a/d require exact normal and shiny form URLs, `869.png` for the default. |

**Fallout for pending v2 rows** (coordinator applies to their tickets):
- **M8.1c** — landed first (1f21148); this clause and its tests now live in M6.8f/M6.8g: `open_encounter` also reopens the selected raid
  encounter when the selection carries `catch_return` (set only by M6.8f/g), with the same
  owner, `queued`/`revealed` and unexpired-spawn checks as `run_confirm`/`master_confirm`, and
  pops `catch_return`; add tests `test_storage_full_raid_expand_confirm_and_back_return_to_raid`
  and `test_storage_full_raid_research_send_and_cancel_return_to_raid`, each with an ordinary
  encounter queued and with none, plus `test_catch_return_after_raid_expiry_falls_through`.
- **M8.1a:** void — landed as `0015_raids.sql`; M6.8b makes the pinned tests count migration files.
- **Any later v2 row** that copies Pokémon fields into a receipt or table copies `form_id` too.

### Amendment review round 2 — 2026-11-05 (MUST 1, SHOULD 1)

| # | Finding | Disposition |
|---|---|---|
| 1 | M6.8d omits test_content_evolutions.py | Fixed: M6.8d now updates test_content_evolutions.py:231 (3 branch forms + 62 Alcremie forms), :241-242 (default-form targets keep `/<pokemon_id>.png`; Alcremie forms `/869-<form_identifier>.png` and `/shiny/869-…`), :294 (65), keeping the stats, family, exclusion and branch checks; no production file added (ticket 4,069 B after trimming). |
| 2 | Q1 still says 7 Alcremie recipes and ≤ 25 per source | Fixed: §3 above gives exact replacements for PLAN.md:173-174 (targets include the 62 Alcremie forms) and :180-181 (63 recipes; per-item limits; item-first selection, Q15); review records unchanged. |

Also re-checked at 036d339: M7.7a (7871aab) landed, so the block moves to steps 30–38 and
M6.8g records the +3-line shift in bot/research.py.

### Amendment re-anchor and rounds 3–5 — 2026-11-05 (amendment 1 only; supersedes amendment 1's step and migration numbers above — amendment 2 rows are steps 50–57, migration `0017`)

Round 3: MUST 0, SHOULD 0, NIT 0. The drive then landed M7.7b–M8.2a, so the supervisor re-anchored the amendment: block after step 36 (M8.2a) as steps 37–45; form migration `0016_pokemon_form.sql` (`0015_raids.sql` landed with M8.1a); M8.1c's raid-return clause and tests moved into M6.8f/g; M7.7b guard notes turned into instructions (M6.8c, M6.8e). In the records above, "§3 above" means the insert's §3, now §4.1 Q1.

| Round | # | Finding | Disposition |
|---|---|---|---|
| 4 | 1 (MUST) | M6.8b misses test_raids.py:376 (`user_version` 15) | Fixed: M6.8b counts migration files there too; test_raids.py in Files and Verify. |
| 4 | 2 (SHOULD) | M6.8f Verify omits existing raid regression tests | Fixed: `-p "test_raids.py"` added to M6.8f Verify. |
| 5 | — | MUST 0, SHOULD 0, NIT 0 — "Ship" | — |

**UNVERIFIED:** paper reviews only; raid return behaviour is proven by the M6.8f/g raid tests. Full records: amend-review-1.md … amend-review-5.md.

## 8. Build-time supervisor rulings (recorded at drive end, 2026-11-06)

Rulings the supervisor made at drive stops under owner-delegated authority. Owner decisions are in §4.1 (Q1–Q22) and §7.

1. `refs/wip/*` belongs to the supervisor's backup loop; Codex is the only writer of the feature branch.
2. Fixture/test-data additions a ticket's Accept or a prior row's loader requires are in scope (M6.1b mini `types`/`type_efficacy`).
3. Existing tests broken by a row's required behaviour may be updated deliberately, keeping their assertions (M6.4b `test_conversion` helper).
4. v1 bugfix during the drive: guild command sync registers only that guild's commands (81d869e); root README sync docs updated (owner-only README untouched).
5. Missing configured content/tables may be passed as an argument following v1 patterns (M7.4a/M7.5a deploy content).
6. A foreign-server gym is indistinguishable from a missing one: `stale`, no cross-guild lookup (M7.4a; overrides the ticket's `invalid`).
7. M8.2a: no shared HTTP transport change; the 5-second send deadline (not in the ticket) removed. **Accepted risk:** a discord.py internal retry later than Discord's nonce de-duplication window could duplicate a raid announcement.
8. M6.8b: `test_route_unlocks.py` backfill tests were already failing (broken by 0014/0015); fixed as a separate test-only commit under ruling 3. A full `test_cmd` run then surfaced four more stale tests (`test_finds` session fixture, `test_evolution_items` rare set incl. the non-convertible World Legendary Ticket, `test_gyms` `user_version` pin, `test_lure` `raid_spawn_id` column), fixed as tests only under ruling 3.
9. "King's Rock" U+FFFD sighting was a cp1252 terminal artifact, not data (Q17); only the guard test was added.
10. M6.8y: the pending-catch router intercept is read-only only when the session already holds that catch's **saved pending menu** (selection names the pending encounter **and** carries its quoted `storage_limit`) — a true replay writes nothing. An older throw selection naming the same encounter is not a replay: it saves the menu (with the Upgrade quote) and advances the revision (refined after review, 2dd4a93; C5).
11. M6.8u: the zero-match `test_overflow_` check applies to `tests/test_capacity.py` only; `test_economy_model.py`'s economy test is unrelated.
12. M6.8w: the ticket's "no contract change" corrected — C5's sentence keeping the M6.8g `resume` flow updated as superseded and removed.
13. Supervisor process notes: the drive overran one pause instruction (M6.8k landed before Q22; a half-built M6.8l is kept only in a local git stash); Codex once wrote status cells as `? done ?` (repaired 3e56b30).
