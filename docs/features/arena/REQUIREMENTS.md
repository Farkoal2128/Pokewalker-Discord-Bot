# Arena — pre-plan requirements (approved)

Status: **approved by the owner 2026-11-13** after 8 review rounds (round 8: 0 Must, 1 Should, fixed). **Amended 2026-11-14** with the owner's monthly leaderboard (§6.3, AR-36..AR-41). Nothing here is planned or built yet. Next step:
`feature-pipeline:plan` turns this file into `PLAN.md`. No code changes before that plan is reviewed and approved.

Labels: **[O]** is the owner's spec. **[R]** is a recommendation that fills a gap; the owner can
override it.

## 1. Outcome

A solo, repeatable PvE mode. A player locks in a team of 3, then climbs endless floors. Each floor
has three 3-on-1 auto-battles. Clearing floors earns Arena Tickets, which the player redeems later
for encounters and gym-style rewards.

## 2. Ground truth from the code (checked 2026-11-13 at 2bab54b; rechecked against 9c8aec5, which only adds a favorites-first sort to the gym pickers)

| Fact | Where | Consequence for the Arena |
|---|---|---|
| IVs are the GO scale, 0-15 per stat (Attack, Defense, Stamina) | `pokewalker/domain/cp.py:_validate_ivs` | The 0-5/5-10/10-15 tiers fit inside the scale. |
| Levels run 1-40 (`level_x2` 2-80, `cpm.json` keys 2-80). Power-ups stop at level 40 (`cap_level_x2: 80` in `powerup_prices.json`) | `cp.py:cpm`, `content/balance/powerup_prices.json` | An enemy at level 40 matches a maxed player Pokémon. Enemies cannot go above level 40, so scaling past floor 40 must use HP and IVs, as the owner's spec already does. |
| The battle engine already fights 1-3 attackers against 1 defender. Gyms limit this to 1 through `party_max` | `pokewalker/domain/battle.py:simulate`, `contracts/gym-battle.md` (C7) | 3-on-1 fights need no change. But `Result` reports only outcome, ticks, surviving slots and events (at most 39 narrative lines plus one final line). It does **not** report each member's remaining HP, and C7 defines `Combatant.hp` as canonical (full) HP. Carrying HP between fights (AR-11) needs a small contract change (AR-11b). |
| The engine returns `win`, `loss` or `draw`. If the defender faints while any party member (even a benched one) still has HP, it is a `win`, even if the active attacker faints on the same tick. It is a `draw` only when the defender and the last party member faint together, or at the 120-tick limit | `battle.py:simulate`, C7 | The Arena counts a draw as a loss (AR-14). |
| Defender HP is a multiplier ×10 with ceiling rounding (gym defenders start at 2.0×) | `battle.py:defender_hp`, `battle.json` | Arena HP scaling reuses the same ×10 integer form. Arena enemies start at 1.0×. |
| Both moves use the first type; STAB 1.2; fixed fast/charged powers | `services/gyms.py:_battle_snapshot`, `battle.json` | The Arena reuses `_battle_snapshot` and the gym rules unchanged. |
| The catalog `bst` field is the main-series base stat total (Bulbasaur 318). It ranges from 175 (Solo Wishiwashi) to 720. The highest identity that is neither Legendary nor Mythical is Slaking at 670 (Normal Arceus, 720, is flagged Mythical, not Legendary) | `content/artifact/content.json` identities | The BST formula uses `bst`. The full limit is 720. |
| `is_legendary`/`is_mythical` flag 97 identities. Ultra Beasts (e.g. Xurkitree 570) and Paradox Pokémon (e.g. Iron Valiant 590) are **not** flagged | catalog | "Legendary, Mythical and similar" needs an authored list (AR-20). |
| The encounter queue holds 3 (`encounter_queue: 3`). `spawn_encounter` adds one route encounter, and its caller checks for room | `capacities.json`, `services/stepping.py:spawn_encounter`, `profiles.queue_size` | The ticket encounter grant reuses `spawn_encounter`, guarded by `queue_size`. |
| Gym income is one weighted roll of `gym_income_table` per held hour, delivered to `inbox_items`. The survivor reward is one roll of `survivor_table` plus 500 Stardust | `services/gyms.py:pay_hours`, `end_deployment` | Ticket incomes and survivor rewards reuse these rolls and deliver to the inbox with an `arena:` key. |
| Reward writes are protected against repeats either by `with_receipt` (battles, hourly income, deploys, feeding) or by a duplicate guard in the same transaction (the survivor reward uses `gym_deployments.survivor_rolled`). `with_receipt` takes an optional `profile_id`, and a receipt written without one is not removed by profile deletion | `pokewalker/db.with_receipt`, `services/gyms.py` | Every Arena write uses `with_receipt` **with `profile_id`** (AR-4b, §10 deletion row). |

### Economy reference values (stardust-equivalent, from `conversion_rates.json`)

| Unit | Value | Notes |
|---|---|---|
| 1 gym income roll | ≈ 26 | Mostly balls. 8% Razz, 8% Pinap. |
| 1 survivor reward | ≈ 754 + 1% World Legendary Ticket (unpriced) | Master Ball 6%, Shiny Lure 8%, Bottlecap 4%. |
| Full 8-hour gym hold | 8 incomes + 1 survivor ≈ 959 | The most one profile can earn from gyms is 3 holds per day. |
| Encounters | Walking: the step rules allow at most ~675 steps an hour (300 words at the full rate, later words at 25%, 30 accepted words a minute, 15-second cooldown), so at most ~6 encounters an hour if the queue is cleared between spawns. The casual and regular profiles in `simulation.json` get ~1-3 a day. **Hourly `/checkin`: +1 encounter per check-in when the queue has room** (`items.checkin` → `spawn_encounter`) | A player who checks in often already gets ~10-20 encounters a day, so Arena tickets are a top-up for them. For a casual player who rarely checks in, they are a big boost. |
| Berry supply (Razz + Pinap) | Finds: 16% of a find, at most 3 per hour. Check-in: 45% per check-in, hourly (≈0.45 berries per hour). Gym income: 16% per hour | A rare checker gets ~2-5 berries a day. Checking in every waking hour (~16 a day) gives ~7 from check-in alone, ~10-12 a day in total. |
| Stardust | Catches pay 100 / 300 / 500 each (`catch_stardust`). Check-in pays none directly (only overflow conversion). About 600 a day for one active hour a day (`economy-report.md`: ≈17,800 a month). A player who checks in hourly and catches ~15 a day gets roughly 3,000-4,500 a day | Level 40 costs ≈35,000 Stardust per Pokémon. |

## 3. Entry, team and run lifecycle

- **AR-1 [O]** A profile can **start** a run at most once every 18 hours.
- **AR-2 [R]** The 18-hour cooldown starts **when the run starts**. *Why:* it is one timestamp, needs no "run finished" bookkeeping, and stops anyone delaying the end of a run to gain time.
- **AR-3 [O, owner ruling 2026-11-13]** A run ends only in one of two ways: a fight is lost (AR-14), or **18 hours pass since the start**. Reaching hour 18 counts as a **defeat on the current floor**: that floor pays nothing, and tickets already earned stay (AR-31). There is no timer: every run action (fight, heal, opening the Arena screen) first checks the 18-hour limit inside the same database transaction, and an over-time run is ended as a defeat before anything else happens, so no fight or heal is accepted after hour 18.
- **AR-3a [O, owner ruling 2026-11-13]** The player can **back out** of the Arena at any time, during any break, and come back later to the exact same spot (same floor, fight, enemy and team HP) as long as the run hasn't ended. Backing out does not end the run, pause the 18-hour clock or cost anything. There is no "give up" button. *Why none is needed:* tickets are credited floor by floor, and the cooldown runs from the start whatever happens, so ending early would gain the player nothing.
- **AR-4 [R]** Run state (team snapshot, team HP, floor, fight slot, pre-rolled next enemy) lives in SQLite. A bot restart resumes the run exactly where it was.
- **AR-4a [R] Stale screens.** Several `/walker` screens can be open for the same profile. Every run action (fight, heal, Heal all & fight, Fight until hurt) carries the run ID and the run's expected revision; the revision goes up on every change to the run. The action checks both inside its transaction. If they don't match, it spends nothing, fights nothing and redraws the current state. Fight receipts are keyed by run ID and fight number (floor, slot), so the same fight can never resolve twice.
- **AR-4b [R] Receipts belong to the profile.** Every Arena `with_receipt` call passes `profile_id`, so profile deletion removes the receipts (and the team snapshots and results inside them) along with the new tables (§10).
- **AR-5 [O]** The team is exactly 3 Pokémon, chosen at run start. The **members** cannot change during the run; their **order** can (AR-10c).
- **AR-6 [O, owner ruling 2026-11-13]** **No restrictions on team members.** Legendary, Mythical, Ultra Beast, Paradox and any other Pokémon may join the team. There is no BST, CP or species cap.
  - **[O, owner ruling 2026-11-13]** The **companion** is allowed. A Pokémon **currently defending a gym is not**. Otherwise the player must own the Pokémon, and the 3 must be 3 different owned Pokémon (two of the same species is fine).
  - **AR-6a [O, owner ruling 2026-11-13]** While a Pokémon is on the deploying profile's **own** live Arena team, that profile cannot deploy it to a gym (`gyms.deploy` refuses with a new status). "Live" means the run has not ended **and** less than 18 hours have passed since it started, so the block lifts at hour 18 even if the player never opens the Arena again. The check matches profile + Pokémon. The same rule covers **claiming a gym after a gym battle** ("Claim with attacker", `gyms.battle` with a nominee): the claim picker marks Arena team members as unable to defend, and `gyms.battle` rejects such a nominee **before** the battle runs, in the same place it already rejects a blocked Legendary nominee, so a claim that can't succeed never clears the defender or uses the battle cooldown. The refusal names the real reason (on an Arena team). Arena team members also can't attack at all (AR-6b), so the player can only attack, with or without claiming, using Pokémon outside their live Arena team. Gym screens show why a team member can't be deployed or claim. *Why:* without this, a player could start a run and then deploy the same Pokémon, getting around the owner's rule.
  - **AR-6b [O, owner ruling 2026-11-13]** A Pokémon on the player's own live Arena team (same "live" rule as AR-6a) also **cannot attack a gym**. `gyms.battle` refuses a party containing one, before the battle runs and before any cooldown or payout, with the real reason; the gym attacker picker marks such Pokémon as busy in the Arena. Together with AR-6a, a Pokémon is in either the Arena or gyms during a run, never both.
- **AR-7 [R]** At run start, each team member's stats are snapshotted (species, level, IVs, types, full HP) through the same `_battle_snapshot` the gyms use. Powering up or evolving a member mid-run does not affect the run. *Why:* no mid-run revalidation, and it matches "cannot be changed".
- **AR-7a [O, owner ruling 2026-11-13] No trading away.** A Pokémon on the player's own live Arena team (the same "live" rule as AR-6a) **cannot be traded**: the trade picker leaves it out, offering it is refused, and accepting a trade that includes it is refused (trade acceptance already rechecks eligibility, `services/trading.py`), so an offer made before the run started cannot complete during the run. Gym defenders already cannot be traded (`deployed` in `trading.REFUSED`); that stays as is. **[R]** The same block covers sending the Pokémon to research, the only other way a Pokémon leaves the player. *Why:* otherwise a team member could leave mid-run and its run snapshot would keep fighting and earning Candy for a Pokémon the player no longer has.
- **AR-8 [R]** Players excluded from the bot cannot start or continue a run. Paused players cannot start one. This uses the existing `profiles.restrictions`: exclusion is checked the way gyms check it, and the paused-start refusal matches check-in (gyms themselves do not refuse paused players).

## 4. Fights

- **AR-9 [O]** Each floor has 3 fights in order: **entry**, **middle**, **boss**. Each is the player's team (its living members) against one enemy.
- **AR-10 [R]** Each fight is resolved instantly by `battle.simulate` with the gym `battle.json` rules: the same moves, energy, STAB, type chart and tick limit. Gyms keep `party_max: 1`; the Arena allows 3. Team members fight in the run's current party order (AR-10c): the first member leads, and the next steps in when one faints, as in gyms.
- **AR-10a [O, owner ruling 2026-11-13]** The break screen shows the next enemy (AR-15), each member's HP and full HP, a **berry choice** (Razz or Pinap, defaulting to whichever the player has more of), a **Heal** button per member, **Fight** (one fight), **Heal all & fight**, **Fight until hurt**, a **party order** control (AR-10c) and **Back out** (AR-3a). Heal and Heal all & fight use the selected berry type; the player switches the choice between Heal presses to mix types. **Heal all & fight** is all-or-nothing: it needs one selected berry per member below full HP. If the player has too few, it spends nothing, starts no fight and says how many are missing. Members at full HP cost nothing.
- **AR-10b [O, owner ruling 2026-11-13] Fight until hurt.** One click resolves fights back to back, never spending berries. **Auto-order (per-profile toggle, off by default):** when on, before each fight in the chain the party is reordered by current HP as a percentage of full HP, highest first (ties keep their current order), so the member furthest from the stop threshold leads and the chain stops less often. When off, the chain keeps the run's current order. The toggle sits next to Fight until hurt, is saved on the profile like the stop threshold (AR-10d), and can be changed in any break. *(Owner rulings 2026-11-13: percentage, not raw HP; a toggle, default off, because §8 shows automatic ordering can make berry-rich runs end sooner.)* The order left after the chain stops is the run's current order, and the result screen shows it. It stops at the first of: a break where any member is below the player's **stop threshold** (AR-10d) or was revived at 1 HP (AR-11a); a lost fight (run over, AR-14); right after the boss of a floor that pays a ticket (AR-32); the 18-hour limit (AR-3); or a restriction change (AR-8). Each fight in the chain is its **own committed write**: a coordinator outside the normal one-transaction handler (`bot/walker.py` dispatch, `writer.run`) submits one writer job per fight, and each job rechecks the run revision (AR-4a), restrictions and the 18-hour limit before fighting. A crash mid-chain keeps every finished fight and never repeats one; the chain just stops. The result screen lists each fight in order. *Why:* the player still makes every berry decision, while easy stretches cost one click instead of one per fight.
- **AR-10c [O, owner ruling 2026-11-13] Party order.** In any break, the player can set the order of the 3 members (who leads, who is second, who is third). Changing the order is free, costs no berry, and counts as a change to the run (its revision goes up, AR-4a). The order is saved with the run and survives backing out and restarts (AR-4). **Fight** and **Heal all & fight** use the order as the player left it; only **Fight until hurt** with auto-order turned on reorders automatically (AR-10b). A fainted member revived at 1 HP (AR-11a) keeps its place unless the player or the chain moves it. *Why:* the engine already sends members out in list order, so order is just the list the Arena passes to `simulate`; no engine change is needed.
- **AR-10d [O, owner ruling 2026-11-13] Stop threshold.** The player sets the HP percentage at which Fight until hurt stops: **10% to 90% in steps of 10, default 50%**. It is a per-profile setting shown on the break screen next to Fight until hurt, saved on the profile, so it carries over to later runs and survives restarts. Changing it is free and allowed in any break. Changing the threshold or the auto-order toggle (AR-10b) while a run is live also bumps that run's revision in the same transaction (AR-4a), so any other open screen must redraw before it can start a fight, and a running chain stops at its next check and redraws. *[R] for the range and step:* below 10% the chain would keep fighting with members one hit from fainting, and 10-point steps fit a single Discord select menu.
- **AR-11 [R]** Team HP **carries over** between fights and floors.
- **AR-11b [R]** Contract C7 (`contracts/gym-battle.md`) changes in two compatible ways. (1) An attacker's `Combatant.hp` means its **starting HP** for this fight (any positive integer), not necessarily its full HP; gyms keep passing full HP, so gym behavior doesn't change. (2) `Result` gains `party_hp`: each party member's HP when the fight ends, in party order. (3) `Result` gains `finisher`: the party position that landed the knockout hit on the defender, or none if the defender didn't faint (needed for AR-14a). The Arena keeps each member's full HP separately in the run snapshot (AR-7), applies the 1 HP revive (AR-11a) and any heals, then builds the next fight's `Combatant`s from the current HP. Every existing `Result` constructor and consumer is checked for compatibility. *Why:* rebuilding HP from the event log is unreliable, because the log stops after 39 lines.
- **AR-11a [O, owner ruling 2026-11-13]** In every break between fights, any team member that fainted is **revived automatically at 1 HP**, for free. All 3 members therefore start every fight alive. A run still ends only by losing a fight (AR-14) or by reaching hour 18 (AR-3).
- **AR-12 [O]** Between fights, the player may heal with **Razz Berries** or **Pinap Berries** only, never Golden Razz or Silver Pinap.
- **AR-13 [O, owner ruling 2026-11-13]** One berry (Razz or Pinap, the player's choice) restores **one** team member to **full HP**, including one just revived at 1 HP (AR-11a). In any break the player may heal **any or all three** members (3 berries heal all 3). There is **no cap** per break or per run; the player's berry stock is the only limit.
- **AR-14 [R]** Only a `win` clears a fight. A `loss`, or a `draw` (double knockout or tick limit), ends the run. Rewards already earned are kept (AR-31).
- **AR-14a [O, owner ruling 2026-11-13] Candy for knockouts.** Each Arena fight the player wins gives **1 Candy** of the family of the team member that landed the knockout hit, added to the profile's existing `candy` for that family (the family comes from the run snapshot, AR-7; a member that evolved mid-run stays in the same family). It is credited in the same write as the fight result, with a ledger line (`arena_candy`). Lost fights pay nothing. Skipped floors (AR-34) pay no Candy, because no fight happened. Fights inside Fight until hurt count normally. **Special finishers (owner ruling 2026-11-13):** if the finishing member is a special Pokémon (Legendary, Mythical, Ultra Beast or Paradox, the AR-20 list), it earns Candy **only for knocking out a floor's boss**, so at most 1 Candy per floor. Regular Pokémon earn Candy for every knockout. **Team picker warning:** when the player adds a special Pokémon to the team at run start, the picker warns that it only earns Candy from boss knockouts; the warning informs and does not block (AR-6). *Why:* Legendary Candy is scarce (10 per catch, 1% encounters), and full-rate knockout Candy would let one Legendary power up in about 3 days. Regular families keep the full rate because evolving needs family Candy, and Rare Candy can't replace it; the Arena then joins companion walking as a way to grind evolution Candy.
- **AR-15 [R]** Before a **single** fight (Fight, Heal all & fight), the player sees the enemy's **species, types and CP**. Level and IVs stay hidden. Starting **Fight until hurt** (AR-10b) accepts the fights in the chain without separate previews until it stops; the result screen then shows each enemy fought. The enemy is rolled once and stored (AR-4), so reopening the screen or restarting the bot cannot re-roll it.

## 5. Enemy generation

### 5.1 Level, IVs, HP

- **AR-16 [O]** Hidden enemy level = floor number on floors 1-40 (floor 1 = level 1, floor 40 = level 40). From floor 41 on, it stays at level 40.
- **AR-17 [O, confirmed 2026-11-13]** Enemy IVs are rolled uniformly per stat within the fight's tier: **entry 0-5, middle 5-10, boss 10-15**. *Why these, not 1-5/6-10/11-15:* each range then has room for exactly 5 minimum-IV steps per stat, 15 steps across three stats. At one step every 5 floors, that is 75 floors, which matches the owner's "after 75 floors every enemy has maximum IVs". With the 1-5/6-10/11-15 ranges, middle and boss enemies would reach their maximum at floor 100 and entry enemies would never roll 0.
- **AR-18 [O, slowed by owner ruling 2026-11-13]** After floor 40, the enemy HP multiplier rises by **+0.1× every 5 floors, capped at 2.0×**: floors 41-44 = 1.0×, 45 = 1.1×, 50 = 1.2×, 60 = 1.4×, 90 = 2.0×. As a formula: `factor_x10 = 10 + min(10, floor((floor − 40) / 5))` for floors 41-115. Enemy HP = ceil(canonical HP × factor_x10 / 10), the same as `defender_hp`. *(The owner's original spec was +0.1× per floor, reaching 2.0× at floor 50. The owner slowed it after the simulation showed that floors 41-50 were a wall where HP doubled at the same time as IVs started rising, so most runs ended at floor 50-57 regardless of team.)*
- **AR-19 [O]** After floor 40, every 5 floors the minimum IV rises by +1 in one stat. **[R]** The stats take turns: **Attack → Defense → Stamina**, deterministically. Step *n* = floor(( floor − 40 ) / 5), at most 15. The minimum never exceeds the tier maximum.

| Floor | HP × | IV steps | Entry min (A/D/S) | Middle min | Boss min |
|---|---|---|---|---|---|
| 1-40 | 1.0 | 0 | 0/0/0 | 5/5/5 | 10/10/10 |
| 45 | 1.1 | 1 | 1/0/0 | 6/5/5 | 11/10/10 |
| 50 | 1.2 | 2 | 1/1/0 | 6/6/5 | 11/11/10 |
| 55 | 1.3 | 3 | 1/1/1 | 6/6/6 | 11/11/11 |
| 60 | 1.4 | 4 | 2/1/1 | 7/6/6 | 12/11/11 |
| 90 | 2.0 | 10 | 4/3/3 | 9/8/8 | 14/13/13 |
| 100 | 2.0 | 12 | 4/4/4 | 9/9/9 | 14/14/14 |
| 115 | 2.0 | 15 | **5/5/5 (max)** | **10/10/10 (max)** | **15/15/15 (max)** |
| 125 | 3.0 | 15 | max | max | max |

- **AR-19a [R]** **Past floor 115**, the HP multiplier rises again by **+0.1× per floor with no cap** (floor 116 = 2.1×, floor 125 = 3.0×). *Why:* level and IVs are already at their maximum, so without this, a strong team with enough berries could climb forever and earn tickets without limit. Uncapped HP eventually hits the 120-tick limit, so every run ends. In simulation, no run cleared more than about 150 floors, even maxed teams with unlimited berries; most runs end far earlier (§8).

### 5.2 Species: BST window

- **AR-20 [O+R]** **Special Pokémon** = `is_legendary` **or** `is_mythical` **or** an Ultra Beast (species 793-799, 803-806) **or** a Paradox Pokémon (984-995, 1005-1006, 1009-1010, 1020-1023). The Ultra Beast and Paradox IDs go in an authored balance table (`content/balance/arena.json`), with source and check date as ADR 0001 requires, because PokéAPI has no such flag. Count: 128 special identities and 966 regular ones. *(Owner confirmed all four groups, 2026-11-13.)*
- **AR-21 [O]** Special Pokémon never appear as entry or middle enemies. They can appear as bosses.
- **AR-22 [R] BST cap formula.** Every enemy is drawn from identities with `bst ≤ cap`. There is no lower bound.
  - Base cap: `cap(f) = round(300 + 420 × (f − 1) / 31)` for floors 1-31, and **720 from floor 32 on** (720 is the catalog maximum, so any Pokémon can appear).
  - Boss cap: `floor(cap(f) × 1.15)`, or `floor(cap(f) × 1.50)` when f is a multiple of 10. Never above 720. **[R]** The +50% applies to the **boss of floors 10, 20, 30…** only and replaces the +15%. Entry and middle use the base cap. *(Owner confirmed 2026-11-13.)*
  - *Why linear from 300:* at floor 1, the cap of 300 already allows 177 regular species, so floor 1 has variety without strong Pokémon. The cap climbs about 13.5 BST per floor, first allows pseudo-legendaries (600) at floor 24 and Slaking (670) at floor 29, and hits the full limit exactly at floor 32 as the owner asked.

| Floor | Base cap | Regular species allowed (entry/middle) | Boss cap | Regular boss pool | Special boss pool |
|---|---|---|---|---|---|
| 1 | 300 | 177 | 345 | 328 | 2 (Cosmog, Meltan) |
| 5 | 354 | 344 | 407 | 438 | 4 |
| 10 | 422 | 484 | 633 (×1.5) | 965 | 105 |
| 20 | 557 | 952 | 720 (×1.5, capped) | 966 | 128 |
| 30 | 693 | 966 | 720 | 966 | 128 |
| 32 | 720 | 966 | 720 | 966 | 128 |
| 40 | 720 | 966 | 720 | 966 | 128 |

- **AR-23 [R] How a species is picked.** Entry and middle: uniform over eligible regular identities. Boss: first a reserved draw for a special Pokémon, **5%** on normal floors and **25%** on multiples of 10. On success, pick uniformly from eligible special identities; on failure, or if none is eligible, pick uniformly from eligible regular identities. *Why:* this uses the same reserved-draw pattern as `encounters.roll_tier`. A per-species weight would swing as the number of eligible specials grows from 2 to 128. *(Percentages confirmed by the owner 2026-11-13.)*
- **AR-24 [R]** Enemies are never shiny and use the default (non-gendered) variety. They are display-only and cannot be caught.

## 6. Arena Tickets

- **AR-25 [O]** Rewards are Arena Tickets in five tiers. They are stored per profile in an **Arena submenu**, separate from the inbox, and redeemed from there.
- **AR-26 [O]** What each ticket gives when redeemed:

| Ticket | Encounters | Stardust → inbox | Gym income rolls → inbox | Survivor rewards → inbox | ≈ stardust-eq (excl. encounters) |
|---|---|---|---|---|---|
| Bronze | +1 | 100 | 0 | 0 | 100 |
| Silver | up to +2 (fills up to 2 free slots) | 200 | 2 | 0 | 251 |
| Gold | fill queue to 3/3 | 400 | 4 | 0 | 502 |
| Platinum | fill queue to 3/3 | 1,000 | 8 | 1 | 1,959 (one full 8-hour gym hold + 1,000) |
| Diamond | fill queue to 3/3 | 3,000 | 24 | 3 | 5,877 (a perfect day of gym holding + 3,000) |

*Silver buffed 2026-11-13 by owner decision. The owner's original Silver was +1 encounter and 1 income roll. Now encounters go 1 → 2 → 3 and income rolls 0 → 2 → 4 → 8 → 24 across the tiers. Flat Stardust added to every ticket 2026-11-13 by owner decision, then doubled by the owner the same day to 100 / 200 / 400 / 1,000 / 3,000. It is on top of the 500 Stardust inside each survivor reward.*

- **AR-27 [R]** Encounters come from `spawn_encounter` on the profile's current route. An active Lure, Companion Mirror or Shiny Charm applies, and a Lure or Mirror charge is used up, exactly as with walking encounters.
- **AR-28 [R]** A ticket can be redeemed only when the queue has **at least one free slot**. Otherwise the button explains why and nothing is spent. *Why:* one rule covers all tiers, and tickets keep indefinitely, so waiting costs nothing. For Silver and above, the confirm screen quotes how many encounters the redemption adds right now (for example "2 of 3 slots free: +2 encounters"). The quote is saved with the confirm button and rechecked inside the redemption transaction. If walking or a check-in has changed the free slots since, nothing is spent (no ticket, no Lure or Mirror charge) and the screen shows the new quote.
- **AR-29a [R]** Inbox rewards from tickets use the existing lossless inbox. An item that doesn't fit the bag or a rare pocket (Master Ball, Shiny Lure, World Legendary Ticket: 1 each) stays in the inbox until there is room, exactly as gym survivor rewards do today (`milestones.claim`).
- **AR-29 [R]** Income and survivor rolls use the live `gym_income_table` and `survivor_table` (so balance changes carry over) and go to `inbox_items` with keys like `arena:<redeem_id>:income:<n>` and `arena:<redeem_id>:survivor:<n>`; the flat Stardust goes in as one `arena:<redeem_id>:stardust` row. Each redemption is atomic and idempotent (`with_receipt`).
- **AR-30 [R]** There is no storage cap on tickets. *Why:* the deep floors limit themselves, because berries are scarce (§8).

### 6.1 Recommended distribution

- **AR-31 [R]** A ticket is credited **when its floor is cleared** (boss beaten). The player keeps it when the run later ends by a lost fight or the 18-hour limit. *Why:* there is no "bank or risk it" state to store or explain, and a crash or restart cannot lose rewards. Berries already cost the player something.
- **AR-32 [O, owner ruling 2026-11-13] Repeat schedule, earned on every run.** Tickets come on floors that are multiples of 5, on two tracks:

| Floors | Ticket |
|---|---|
| 5, 15 | Bronze |
| 10, 20, 30, 40 | Silver |
| 25, 35, 45, 55… (every 10 floors from 25) | Gold |
| 50, 60, 70 | Platinum |
| 80, 90, 100… (every 10 floors from 80) | Diamond |
| all other floors | none |

  Floors ending in 0 go Silver → Platinum (from 50) → Diamond (from 80). Floors ending in 5 go Bronze → Gold (from 25). Each tier starts at its floor and then repeats every 10 floors until a higher tier takes over that track. *(Owner ruling 2026-11-13; it replaces the earlier "every 25th / 50th / 100th" schedule. Gold stays at 25 so that it lands on the 5-track and never collides with Silver, Platinum or Diamond.)*

- **AR-33 [R] First-clear bonus.** The first time a profile ever clears a floor that pays **Silver or better** (every ticket floor from 10 on, except Bronze floors 5 and 15), it gets **one extra copy** of that floor's ticket. This needs one stored value, `best_floor`.

- **AR-34 [O, owner ruling 2026-11-13] Floor skip.** When starting a run, the player may skip floors they have already proven:
  - Maximum skip `S = min(floor(best_floor / 2), 40)`, where `best_floor` is the highest floor the profile has ever cleared (AR-33). Examples: best 30 → skip up to 15; best 79 → 39; best 80 or more → 40.
  - The player picks any skip `k` from 0 to `S`, and the run starts at floor `k + 1`, entry fight, with the team at full HP.
  - The skipped floors 1..k pay **their AR-32 tickets as if cleared**. The first-clear bonus (AR-33) never applies to skipped floors, because every skipped floor was already cleared before.
  - `best_floor` only rises from floors actually fought, so skipping never raises the skip limit by itself.
  - *Why:* a deep run otherwise starts with 120 easy fights (floors 1-40). Skipping 40 floors cuts a typical veteran run from about 125-230 fights to about 50-150 (simulation below).
  - **[O, owner ruling 2026-11-13]** Skipped-floor tickets are credited **at run start**, in the same transaction that creates the run. The owner accepted on purpose that a veteran can start a run, back out (AR-3a) and still keep the skipped floors' tickets (at the full 40-floor skip: 2 Bronze, 4 Silver and 2 Gold, about 1,800 Stardust, 16 income rolls and up to ~16 encounters every 18 hours).

Simulation of runs after a 40-floor skip (slowed HP ramp, exact HP, 100 runs per row, healing below 40% HP, **fixed party order** as chosen at the start; "reach N" = floor N cleared). §8 has the same runs with automatic ordering:

| Team | Berries | Median floor (p10-p90) | Reach 50 (Platinum) | Reach 80 (Diamond) | Reach 90 | Reach 100 |
|---|---|---|---|---|---|---|
| Mid: Dragonite/Tyranitar/Metagross L30 12/12/12 | 30 | 57 (55-59) | 100% | 0% | 0% | 0% |
| same | 50 | 66 (63-68) | 99% | 0% | 0% | 0% |
| same | 100 | 83 (64-88) | 100% | 61% | 2% | 0% |
| Max: same, L40 15/15/15 | 30 | 60 (58-63) | 100% | 0% | 0% | 0% |
| same | 50 | 71 (69-73) | 100% | 0% | 0% | 0% |
| same | 100 | 93 (87-96) | 100% | 94% | 76% | 0% |
| Max legends: Mewtwo/Rayquaza/Groudon L40 15/15/15 | 30 | 62 (60-64) | 100% | 0% | 0% | 0% |
| same | 50 | 73 (71-76) | 100% | 0% | 0% | 0% |
| same | 100 | 97 (93-100) | 100% | 96% | 94% | 17% |

What the skip, this schedule and the slowed ramp mean together:
- **The skip saves berries as well as fights.** About 30 berries that went on floors 1-40 now go on floors 41+. A veteran (best ≥ 80) with 30 berries usually clears floor 57-62: 1-2 Platinum plus 2-3 Gold most runs.
- **Berries, not team strength, now decide Diamond.** With about 100 berries in one run, even a mid-level team clears floor 80 in 61% of runs, and maxed teams in 94-96%. With 50 berries or fewer, no simulated run reached 80. So Diamond takes roughly 1-2 weeks of saving berries (for an hourly checker) rather than a maxed team, and a maxed team with 100 berries often gets a second Diamond at floor 90.
- **Survivor rolls are the thing to watch.** A run that clears 80 pays 6 survivor rolls (3 Platinum + 1 Diamond); one that clears 90 pays 9; one that clears 100 pays 12. The gym maximum is 3 a day. Each survivor roll has a 6% Master Ball and 1% World Legendary Ticket chance; rare pockets hold 1 each and the rest waits in the inbox (AR-29a). The slowed ramp makes these deep runs more common. If Master Balls feel too common after launch, the levers are the survivor table, the Platinum/Diamond contents, or the ramp in `arena.json`, not the schedule.

What a run pays under this schedule (repeat tickets only; first-clear bonus copies excluded; a "fill" adds up to 3 encounters):

| Run clears floor | Tickets | Encounters (max) | Flat Stardust | Income rolls | Survivor rolls |
|---|---|---|---|---|---|
| 10 (no berries, typical) | 1B, 1S | 3 | 300 | 2 | 0 |
| 20 | 2B, 2S | 6 | 600 | 4 | 0 |
| 30 | 2B, 3S, 1G | 8 + 1 fill | 1,200 | 10 | 0 |
| 40 | 2B, 4S, 2G | 10 + 2 fills | 1,800 | 16 | 0 |
| 50 | 2B, 4S, 3G, 1P | 10 + 4 fills | 3,200 | 28 | 1 |
| 60 | 2B, 4S, 4G, 2P | 10 + 6 fills | 4,600 | 40 | 2 |
| 80 | 2B, 4S, 6G, 3P, 1D | 10 + 10 fills | 9,400 | 80 | 6 |
| 100 | 2B, 4S, 8G, 3P, 3D | 10 + 14 fills | 16,200 | 136 | 12 |

*Reasoning:*
- A typical engaged player without a skip has 10-30 berries per run and clears floor 15-40 (§8). That earns 3-8 tickets, about 4-16 encounters per 18-hour window. For someone who checks in hourly (~10-20 encounters a day already) that is a modest top-up. For a casual player it is the larger share, which the owner accepted (free baseline, below).
- Flat Stardust adds about 400-1,800 per typical run (roughly 530-2,400 a day at one run per 18 hours). For a player active about an hour a day (~600 a day) their total Stardust becomes about 1.9-5 times as much. For an hourly checker (~3,000-4,500 a day) it is about +12-80%. Level 40 (≈35,000 per Pokémon) drops from about 2 months of walking alone to about 2-4 weeks for a casual player who also runs the Arena. The owner chose this generosity on purpose (2026-11-13).
- **Candy (AR-14a):** a run pays one Candy per fight won when a regular Pokémon lands the knockout, but only one per floor (the boss) when a special Pokémon does. For a team of regular Pokémon that is about 3 per floor: ~45 for a floor-15 run, ~120 for a floor-40 run, and ~120 more for floors 41-80 after a skip. For an all-special team it is 1 per floor: ~15, ~40 and ~40. Mixed teams fall in between, depending on who lands each knockout. Skipped floors pay no Candy. Powering one Pokémon from level 1 to 40 costs about 200 Candy (`powerup_prices.json`), and evolving needs family Candy that Rare Candy can't replace, so the Arena becomes a main source of evolution Candy for regular families, next to companion walking. If Candy floods, the lever is Candy per knockout, not the schedule.
- *(The owner kept the free baseline on purpose: a run with no berries usually clears floor 10-18 and earns about 3-4 encounters every 18 hours, which makes the Arena a real second way to progress alongside walking.)*

## 6.2 Server setting

- **AR-35 [O, owner ruling 2026-11-13] Admin on/off.** `/walker-admin arena on|off reason` turns the Arena on or off for the server. It is **on by default**. It follows the existing `/walker-admin gyms legendary` command exactly: Manage Server permission, server only, a reason is required, it writes a new `guilds.arena_enabled INTEGER NOT NULL DEFAULT 1` (0 or 1) and a `mod_audit` row (`arena_on` / `arena_off`), and replies with the new state.
- **AR-35a [R] What "off" does.** While off, nobody in the server can **start** a run; the start screen says the Arena is turned off here. Runs already live when it was turned off **can still be played to the end** (they last at most 18 hours, AR-3), and **tickets can always be redeemed**. Turning it back on changes nothing else: cooldowns, `best_floor` and tickets are untouched. *Why:* turning the Arena off should never take away rewards a player already earned or let a live run die at hour 18 because of a moderator's action, and the longest a live run can continue is 18 hours.

## 6.3 Monthly leaderboard (owner request 2026-11-14)

- **AR-36 [O, owner ruling 2026-11-14] What it ranks.** Each server has one Arena leaderboard per calendar month. A player's score is the **highest floor they fully cleared (boss beaten) in a fight during that month**. *[R]* Months follow **UTC**, because the bot keeps every time in UTC and has no server time zone. A floor counts in the month its boss fight was won, so a run that crosses midnight on the 1st scores its later floors in the new month. Skipped floors (AR-34) don't score by themselves, because no fight happened. Only the floors fought after the skip count, so after a 40-floor skip the first score is 41. Fights inside Fight until hurt (AR-10b) count normally. The score is written in the same transaction as the boss win that sets it, and only when it beats the player's score so far that month.
- **AR-37 [R] Ties.** Equal floors rank by who reached that floor first in the month (the time of the boss win). An exact tie on time falls back to the older profile (`profiles.created_at`), then to `profile_id`, so the order is always fixed. *Why:* reaching a floor first is a fair, visible rule, and the result can't change after the fact.
- **AR-38 [O, owner ruling 2026-11-14] Rewards and reset.** The leaderboard resets at the start of the 1st of each month (00:00 UTC). The finished month's top 3 get these rewards in their **inbox**:
  - **1st place:** 1 Master Ball, 1 Shiny Lure and 1 World Legendary Ticket.
  - **2nd place:** 1 Master Ball and 1 Shiny Lure.
  - **3rd place:** 1 Master Ball.

  *(The owner first wrote "Shiny Charm" and corrected it to the consumable Shiny Lure on 2026-11-14.)* To win a reward, a player must have cleared **floor 10 or higher** that month (owner ruling 2026-11-14). *Why:* each server has its own profiles, so without a minimum a player alone on a private server would win 1st place every month by clearing floor 1. If fewer than 3 players reach floor 10, the empty places pay nothing and nobody moves up from below floor 10. The rewards use the existing inbox rows (`resource='item'`). The existing claim already caps each rare item at one held (`capacities.json` `rare_pockets`), so a winner who already holds a Master Ball keeps the new one waiting in the inbox until there is room. That is how every inbox reward works today.
- **AR-39 [R] Paying out without a timer.** There is no scheduler, so a month is paid out (settled) **the first time anyone in that server opens the walker home, the Arena, the leaderboard or their inbox after the month ends**. Settlement runs once per server and month, in one writer transaction: it ranks the month, writes the inbox rows and records the month as settled, so paying twice is impossible. The inbox milestone id is `arena_month:<YYYY-MM>:<place>`. A winner who opens `/walker` triggers the settlement themselves, so nobody's reward depends on someone else playing. The home is included because its Inbox button is disabled when the inbox is empty (`bot/screens.py:36-38`). Settlement also **records the paid places** (guild, month, place, profile, floor) in rows that cascade with the profile, so "last month's top 3" shows who was actually paid. A winner who later deletes their data disappears from that list and nobody moves up into their place, because deleted players leave no data behind. If several months went by unpaid, each unsettled month is paid in turn. A profile deleted before settlement drops out of the ranking, and the players below it move up. *Why:* this is the same lazy, check-on-use pattern the 18-hour limit uses (AR-3). It needs no background job.
- **AR-40 [R] The screen.** The Arena home gets a **Leaderboard** button. It shows only to the viewer, like every other walker screen, with:
  - this month's top 10 in this server (a Discord mention with pings off, `<@user_id>`, as the gym and trade screens do, because the bot stores no names; floor), plus the viewer's own place and floor if they are outside the top 10;
  - the time until the reset;
  - the three reward lines and the floor-10 minimum;
  - last month's paid places (AR-39), which can be fewer than 3.

  It lists only players with a profile in this server. A player who deleted their data, or whom a moderator reset, is gone from it (both delete the profile, and the monthly score rows cascade). The leaderboard stays visible and settlement still runs while the Arena is turned off (AR-35a), because finished months are already earned. The settled-month rows belong to the server, not to a profile, so they stay. They are the one exception to §10's rule that new tables reference profiles, and they are removed only when the server's data is removed (`guilds` cascade).
- **AR-41 [R] Not included.** No public announcement post. No all-time or cross-server board. No rewards below 3rd place. Players can't hide from the board: it shows only profiles in that server. A player who left the server keeps their profile (there is no leave handler), so they stay ranked and can still win. Their reward waits in their inbox. These stay out unless the owner asks.

## 7. Out of scope (not asked; name them so they don't creep in)

- Server announcements, all-time or cross-server leaderboards, or showing someone else's best floor outside the monthly leaderboard (AR-36..AR-41).
- Catching Arena enemies, or fight rewards other than Arena Tickets and knockout Candy (AR-14a). The monthly leaderboard's inbox rewards (AR-38) are the one exception.
- New moves or battle mechanics. The Arena reuses the gym engine and rules as they are.
- Spending tickets on anything other than their fixed contents, or trading tickets.

## 8. Simulation evidence (scratch only, not committed)

A scratch script ran the real `battle.simulate`, `combat_stats`, `cpm.json`, `battle.json` and catalog with the rules above (slowed HP ramp, AR-18; free 1 HP revive, AR-11a), 100 runs per cell. HP carry-over is exact: the script used a copy of `simulate` that returns each member's remaining HP (what AR-11b adds) and does not cap the log. Healing policy: before each fight, use a berry on any member below 40% HP. Party order: **fixed** in the order chosen at the start (no reordering), which matches playing with single Fight presses. Each cell shows the median floor cleared, the p10-p90 range, and the median number of berries spent where the budget was not the limit.

| Team | 0 berries | ≤10 | ≤30 | ≤100 | unlimited |
|---|---|---|---|---|---|
| Casual: 3 random Evolved, L20, 7/7/7 | 10 (9-11) | 16 (14-18) | 23 (19-27) | 27 (20-35), 41 used | 26 (19-34), 39 used |
| Mid: Dragonite/Tyranitar/Metagross L30 12/12/12 | 15 (14-17) | 24 (23-25) | 37 (35-40) | 70 (59-73) | 84 (61-108), 134 used |
| Max: same, L40 15/15/15 | 17 (15-18) | 27 (25-28) | 42 (40-44) | 80 (76-83) | 109 (79-128), 165 used |
| Max legends: Mewtwo/Rayquaza/Groudon L40 15/15/15 | 18 (17-19) | 28 (27-29) | 44 (41-46) | 84 (81-87) | 126 (99-138), 198 used |

**Party order matters (AR-10b, AR-10c).** The skip runs from §6.1 again, with the party re-sorted by HP percentage before every fight (Fight until hurt's auto-order) instead of a fixed order. Median floor, then the chance to clear floor 80:

| Team, after a 40-floor skip | 30 berries | 50 berries | 100 berries |
|---|---|---|---|
| Mid L30 12/12/12 | fixed 57 / sorted 56 | fixed 66 / sorted 64 | fixed 83 (61%) / sorted 67 (15%) |
| Max L40 15/15/15 | fixed 60 / sorted 59 | fixed 71 / sorted 69 | fixed 93 (94%) / sorted 79 (49%) |
| Legends L40 15/15/15 | fixed 62 / sorted 63 | fixed 73 / sorted 74 | fixed 97 (96%) / sorted 95 (76%) |

With few berries the order hardly matters. With many berries, sorting by HP percentage spreads damage over all three members, so nobody drops below the heal line and the bench never stays fresh; the team then loses a hard fight while everyone is half-worn. A fixed order lets the lead take the damage and get healed while the bench stays at full HP. **Auto-order means fewer stops, but up to ~15 fewer floors in berry-rich runs and a lower chance of Diamond**, which is why it is a toggle, off by default (AR-10b). The payout and Diamond estimates in §6.1 assume fixed order.

Takeaways ("floor" = highest floor fully cleared; 100 runs per cell, fixed seeds; the script is scratch-only and not committed, so treat these as estimates):
- Berries matter more than team strength. From floor 1, the first 30 berries are worth about 0.8 extra floors each for a strong team (max team: 17 → 42); with a skip, the same berries go further because they are spent on floors 41+.
- The free 1 HP revive adds only about one floor over a no-revive rule, because a member at 1 HP gets in roughly one hit before fainting again. Full healing still has to come from berries.
- Even with unlimited berries no simulated run cleared more than ~150 floors: the uncapped HP growth after floor 115 (AR-19a) stops them. Medians are lower (84-126 for the strong teams), because a bad boss type matchup can end a run regardless of berries.
- With a limited berry budget and no skip, a Legendary team clears about 1-4 more floors than the maxed Dragonite/Tyranitar/Metagross team; after a skip with 100 berries the gap is about 4 (97 vs 93); with unlimited berries it is larger (126 vs 109), but unlimited berries isn't a realistic case. The owner's no-restrictions ruling (AR-6) stands.

## 9. Open questions for the owner

Answered 2026-11-13: IV ranges 0-5/5-10/10-15 (AR-17); companion allowed, gym defenders excluded (AR-6, AR-6a); no berry cap, all 3 may be healed in one break (AR-13); boss-only = Legendary + Mythical + Ultra Beasts + Paradox (AR-20).

Answered 2026-11-13: the +50% applies to the boss only on floors 10, 20, 30… (AR-22); special-boss chance is 5% / 25% (AR-23); the first-clear bonus stays (AR-33). The ticket schedule was later replaced by the owner's two-track schedule (AR-32), with Diamond from floor 80.

Added later (floor skip and Fight until hurt):

8. *Answered 2026-11-13:* skipped-floor tickets are paid at run start (AR-34).
9. *Answered 2026-11-13:* add **Fight until hurt** (AR-10b).

## 10. Existing code each requirement touches

| Requirement | Code / data | Change type (for the plan, not now) |
|---|---|---|
| AR-1-4, AR-31-34 | new `pokewalker/services/arena.py`; new migration in `pokewalker/db/migrations/` (arena runs, ticket balances, `best_floor`, last start time) | new tables; uses `with_receipt` |
| Deletion and reset | every new table references `profiles(profile_id) ON DELETE CASCADE`; every Arena receipt passes `profile_id` (AR-4b); `services/deletion.py` (profile delete, deletion-marker replay after restore) and admin reset rely on the cascade | extend the existing deletion/reset and receipt-owner regression tests to cover Arena tables, Arena receipts, ledger lines and `arena:` inbox rows |
| AR-5-7, AR-6a-b | `services/gyms.py:_battle_snapshot`, `gyms.deploy`, `gyms.battle` (nominee check before the battle), `services/storage.detail` | reuse `_battle_snapshot`; `deploy`, the `battle` nominee check and the `battle` attacker-party check gain one refusal (`in_arena`) |
| AR-7a | `services/trading.py` (`_TRADABLE` picker query, `tradable_reason` at offer and at acceptance), `services/research.py` (send to research); `bot/trade.py`, `bot/storage.py`, `bot/research.py` refusal text (single send: a hard, non-unlockable "on an Arena team" refusal, never the Legendary/Mythical unlock prompt; bulk select: readable protection text); extend `tests/test_research.py` protection tests | one shared "on a live Arena team" check, plus a refusal reason (`in_arena`) |
| AR-8 | `services/profiles.restrictions` | reuse |
| AR-10b, AR-10d | `profiles` gains a stop-threshold column (default 50) and an auto-order flag (default off); arena break screen | two columns, one select, one toggle |
| AR-35-35a | `bot/admin_channels.py` (new `arena` subcommand, copied from `gyms legendary`); new migration adding `guilds.arena_enabled`; arena service start check | small: one column, one command, one check |
| AR-36-41 | new migration 0027 (monthly score rows with profile cascade; settled-month rows, guild cascade; paid-place rows, profile cascade); `services/arena.py` boss-win write and `settle`; `content/balance/arena.json` leaderboard numbers; `bot/walker.py` home, `bot/arena.py` screen, `bot/milestones.py` inbox open; inbox key `arena_month:<YYYY-MM>:<place>` | medium: one table pair, one write, one lazy payout, one screen |
| AR-9-11b, AR-14 | `domain/battle.py:simulate`, `Combatant`, `Result`, `combat_stats`; `content/balance/battle.json` | compatible C7 change: `Combatant.hp` = starting HP, `Result.party_hp` and `Result.finisher` added (AR-11b) |
| AR-12-13 | `inventory` table (`razz_berry`, `pinap_berry`) | new spend path in the arena service |
| AR-14a | `candy` table (same upsert as companion candy in `services/stepping.py`), `resource_ledger` reason `arena_candy`; special list from `arena.json` (AR-20) decides boss-only Candy; team picker warning in `bot/arena.py` | reuse the existing candy write |
| AR-16-19a, AR-22-23 | new pure `pokewalker/domain/arena.py`; `cp.py:cpm`; new `content/balance/arena.json` (caps, IV ranges, HP steps, special lists, chances, ticket schedule) + `content/manifest.json` balance hash | new pure module + balance table |
| AR-20-21 | catalog `is_legendary`/`is_mythical`; Ultra Beast/Paradox IDs in `arena.json` | new data |
| AR-25-29 | `services/stepping.py:spawn_encounter`, `profiles.queue_size`, `capacities.json` `encounter_queue`; `gyms.py` income/survivor roll code (`pay_hours`, `end_deployment`) → extract a shared roll helper; `inbox_items` | refactor roll into a helper + reuse |
| UI | new `pokewalker/bot/arena.py` (the team picker reuses `storage.page(favorites_first=…)` and its Favorites first / Newest first toggle, as the gym pickers do since 9c8aec5); `bot/screens.py` (home button); `bot/walker.py` (`handlers` registration, and the Fight-until-hurt coordinator that commits one writer job per fight, AR-10b); `bot/milestones.py` (readable labels for `arena:` inbox rows instead of raw keys); `bot/gyms.py` (explain the `in_arena` refusal in the deploy, claim and attacker pickers; the battle result must not say "you already hold a gym" for it); `content/help.md` | new screens + small changes to existing ones |
| Checks | `tests/test_balance_tables.py` (its exact table list must include `arena.json`); deletion/reset tests (row above) | update existing tests deliberately |
| Economy | `scripts/economy/model.py`, `docs/features/pokewalker-bot/economy-report.md` | add arena ticket income to the report |
| Contracts | `contracts/gym-battle.md` (C7: `Combatant.hp` as starting HP, `Result.party_hp`, `Result.finisher`); `contracts/persisted-state.md` (new tables, `arena:` inbox keys, cascade, the `in_arena` refusal for deploy, gym battles, trades and research); `contracts/balance-tables.md` (`arena.json`); `contracts/discord-commands.md` (Arena screens and buttons, `/walker-admin arena on|off reason`); `contracts/persisted-state.md` also gains `guilds.arena_enabled` | deliberate contract updates, contract tests first |
