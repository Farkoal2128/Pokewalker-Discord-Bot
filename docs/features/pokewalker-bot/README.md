# Pokewalker Discord bot: requirements draft

Source: owner chat "Discord Pokewalker bot design" (claude.ai, 2026-11-04).
Status: Planned. This file contains requirements only. It is not a plan. The plan
loop writes the canonical `PLAN.md` here after [research](../../research/README.md) is done.

## Outcome

A Discord bot inspired by the HG/SS Pokéwalker. It counts a user's chat activity
as "steps" instead of physical steps. Steps can trigger encounters, and the user
reviews those encounters privately.

## Decided

| ID | Decision | Why |
|---|---|---|
| D1 | Steps come from the user's own messages in channels where counting is enabled. | This is the core idea. |
| D2 | The bot never announces an encounter publicly. It queues the encounter, and `/walker` shows it in an ephemeral reply with Catch/Run buttons. Each button press edits that same private message. The only public output is the opt-in share in D19. | Discord allows ephemeral messages only as replies to interactions, so the bot can't push a private notice when an encounter happens. |
| D3 | A passive ❗ reaction goes on every message that queues one or more encounters. A full queue produces no encounter or reaction. Opening `/walker` removes all of the profile's pending reactions. | Tells the user which messages queued encounters. |
| D4 | No DMs or public pings for encounters. | Many users block DMs, and pings add chat noise. |
| D5 | At most ~3 queued encounters per user. Steps still count when the queue is full, but no new encounters are created. | Matches the device's small storage and stops hoarding. |
| D6 | A per-server setting picks which channels count steps or get reactions. | Some servers won't want bot reactions everywhere. |
| D7 | Anti-farming rules are required (for example per-minute caps, ignoring repeated or very short messages, diminishing returns). | Both word counts and character counts can be spammed. |
| D8 | Mechanics are rewritten in our own words. No ROM dumps, extracted sprites/audio or copied code are committed. | Pokémon IP and reverse-engineering sources (see [PIPELINE.md](../../../PIPELINE.md)). |

### Owner decisions after the research review (2026-11-04)

These settle the conflicts in [the research synthesis](../../research/synthesis.md#2-conflicts-that-must-be-resolved).

| ID | Decision |
|---|---|
| D9 | **No daily limits anywhere. Only hourly limits.** Every cap, budget and diminishing-returns curve uses a rolling hour or a per-minute window. No UTC-day budgets or daily resets. |
| D10 | **Everything is isolated per server.** A player is `(guild_id, user_id)`. Steps, encounter queue, collection, storage, inventory, rare-item caps, currencies, Candy, active effects, companion, Pokédex, gyms and all limits belong to one server. Nothing carries over or is shared between servers. |
| D11 | **Passive item finds** are the walking item source. Dowsing is not a separate supply budget. |
| D12 | **`/checkin`**: once per hour (see D22), grants 1 Poké Ball plus one random common item, and queues one wild encounter unless the encounter queue is full. |
| D13 | **Gym control income**: while a player controls a gym, it grants one random item per hour held. The chance of a rare item (Master Ball, Shiny Lure) is double the passive-find chance of the full v1.1 table (exact values in D23). |
| D14 | **Walking companion**: the player picks one Pokémon from their collection. It earns Candy for its own Candy family as the player earns steps. |
| D15 | **Pokédex tracker**: species seen and caught, per player per server. Tracking is per species: regional and other forms count toward their species. A species becomes **seen** when an encounter is revealed (not when it is queued, so hidden encounters leak nothing). It becomes **seen and caught** on a successful catch, the starter grant, evolving into it, or receiving it in a trade (owner decision 2026-11-12). Running, fleeing, or sending a Pokémon for research never removes an entry. |
| D16 | **Onboarding**: a player's first `/walker` in a server explains the loop and grants starter items. |
| D17 | **Moderation tools** for server moderators. |
| D18 | Step unit: **words**, defined in D33 (originally characters; changed by the owner). Queued encounters do not expire. |
| D19 | **Opt-in sharing**: after a catch, a "Share this catch" button posts a public embed of the catch in the channel where `/walker` was used. Viewing a Pokémon in storage offers the same "Share this Pokémon" option. |

### Approved settings (owner, 2026-11-04)

These are playtest values. Changing one later is a deliberate requirements change.

| ID | Setting |
|---|---|
| D20 | **Steps and encounters (D9):** the first **300 accepted words (base steps) per rolling hour** each award a full step, and every later word in that hour awards **0.25** of a step. The per-message cap, 15-second cooldown and 30-per-minute cap stay; the minute cap counts accepted words (base steps) before the 0.25 reduction. One encounter per **100 awarded steps**. **There is no hourly encounter cap.** Encounters are limited only by the step curve and the 3-encounter queue (D5). **Counting:** steps are stored in hundredths. For each accepted word, look at the base steps (words) credited to the player in this server during the previous 60 minutes, by message time. If fewer than 300, the word awards 1.00 step; otherwise 0.25. The threshold counts accepted words, never awarded steps. A message that crosses 300 is split word by word. Fractions are never rounded away: the encounter, find and companion meters (D20, D21, D25) all accumulate hundredths and keep the remainder after each trigger. |
| D21 | **Passive finds (D11):** one find per 100 awarded steps, at most **3 per rolling hour**. While 3 finds have been granted in the last 60 minutes, the find meter is **frozen**: new steps add nothing to it, and no backlog builds up (as with the full queue, D5). The freeze starts **immediately** when the third find is granted. Steps from the rest of that same message are discarded for the find meter; for example, with 99 on the meter and a message awarding 20, the find triggers and the other 19 are dropped. Whatever remains on the meter at that moment is kept. Use the weight table in [items-and-catching](../../research/go-systems/items-and-catching.md#v1-item-scope-and-walking-drops). **In v1** the Star Piece (50) and Evolution item (200) rows are removed, because those items arrive in v1.1. The remaining weights total 9,750 and are used as they are; for example, the Master Ball is 10/9,750 ≈ 0.10%. **From v1.1** the full 10,000-weight table applies. |
| D22 | **Check-in (D12):** available again **60 minutes after the last successful check-in**, not on the clock hour. |
| D23 | **Gym income (D13):** one item for each full hour held. Each completed hour gets exactly one reward receipt. `/gym rewards` pays the completed hours that have no receipt yet, and ending the deployment pays any remaining ones, so no hour is paid twice. **Exception:** when a moderator excludes the holder (D31), unpaid hours are forfeited. Uses the full passive table (D21, v1.1 form) with the Master Ball raised to **20** and the Shiny Lure to **100**, and the Poké Ball row lowered from 5,000 to **4,940**, so the total stays 10,000: exactly **0.2%** and **1%**. At most one held gym per player per server. |
| D24 | **Gym tenure:** a defender goes home **8 real hours** after deployment. This replaces the researched activity-day fatigue and 7-day backstop, so one deployment earns at most 8 gym items. |
| D25 | **Companion (D14):** 1 Candy for the companion's **own evolution family** per **150 awarded steps**. The companion can be changed at any time, and progress toward the next Candy is kept. The meter belongs to the player's server profile, not to a Pokémon. Each Candy goes to the family of whichever Pokémon is the companion at the moment the meter reaches 150. Restrictions are in D30. |
| D26 | **Onboarding (D16):** the player picks a starter (D34), then gets 30 Poké Balls, 5 Razz Berries, and the first encounter queued immediately. |
| D27 | **Sharing (D19):** the server can turn sharing off. At most one share per player per minute. The bot needs `EMBED_LINKS` plus `SEND_MESSAGES` in a normal channel, or `SEND_MESSAGES_IN_THREADS` in a thread; if they are missing, the button explains why rather than failing silently. |
| D48 | **Shares show a picture (D19).** Share embeds include the Pokémon's sprite as the embed image, hotlinked from the PokéAPI sprites repository at a **pinned commit**. Discord fetches it; the bot hosts and renders nothing. Use the exact form, gender and shiny state: the front sprite (shiny or not) of that form, and the female sprite where the species has gender differences (D53). If no matching sprite exists, send the share without an image and never substitute a non-shiny or base-form picture. The embed text (name, CP, shiny, catcher) stays complete without the image. |
| D49 | **Pictures everywhere a Pokémon appears.** Every screen showing **one** Pokémon includes its picture, using the same exact-form, exact-shiny sprite rule and no-substitute fallback as D48. **v1** hotlinks sprites: the encounter reveal and catch result show the wild Pokémon as the embed image; `/walker` shows the companion as the embed thumbnail; the storage details view and Pokédex entries show the selected Pokémon. **No version renders images (owner decision 2026-11-04):** every picture, in v1, v1.1 and v2, is the hotlinked sprite, which Discord fetches. **Lists of many Pokémon (storage pages, the Pokédex list) are text only**; opening one entry shows its picture. **v2** gym screens (matchup, battle result, defender) show the relevant sprites as embed images or thumbnails. Text always carries the full information. |
| D28 | **Data deletion:** `/walker-account delete-data` wipes the player's data in the **current server only**. Profile IDs are random UUIDs, never reused, even after a restore. **Deletion markers:** before deleting, the bot appends a minimal marker (the deleted **profile ID**, server ID, time) to a small marker log outside the game database, and syncs it to disk. Then it deletes the profile. On every startup, any marked profile that still exists is deleted again, which also finishes a deletion interrupted by a crash. The marker log is copied off-machine with every hourly backup, and a restore always uses the **newest** marker log available, deleting only those exact profile IDs, so a player who re-enrolled later (and so has a new profile ID) is untouched. Accepted limit: if the whole host is lost, deletions made after the last **successful** off-machine copy of the marker log can be lost along with other data from that period. Normally that is under an hour, but longer if uploads have been failing, so the age of the last successful copy is monitored with the backups. Deleting a profile that holds a gym ends that deployment exactly as an exclusion does: the defender is removed, unpaid hours are forfeited (D23), and battles in progress against it are aborted. Nothing is ever credited to a later profile. **Retention exceptions:** moderation audit entries about the player and any **active** restriction (pause, exclusion, share ban) are kept, keyed by `(guild_id, user_id)` rather than by profile, so they also apply to a re-enrolled profile. A **raid participation record** (server, user, spawn) is also kept, but only until that spawn expires (D60). The privacy text says so, and the delete-then-re-enroll case is a required test. Backups are pruned by **age alone**: anything older than 28 days is deleted locally and off-machine, whether or not newer uploads succeed. A failed prune raises an alert and is retried, so deleted data leaves all backups within 28 days, or as soon as the off-machine store is reachable again. The privacy text states this. |
| D29 | **Check-in common item (D12):** one roll, weights out of 100: **Great Ball ×1: 35**, **Razz Berry ×1: 30**, **Poké Ball ×2: 20**, **Pinap Berry ×1: 15**. It never grants rare items. Like passive finds, a pack that doesn't fit in a full bag becomes 10 Stardust. The guaranteed Poké Ball is granted **first**, then the random pack is checked against the space left. Each converts to 10 Stardust on its own if it doesn't fit. A check-in always succeeds and always restarts the 60-minute timer. |
| D30 | **Companion restrictions (D14):** the current companion cannot defend a gym, be sent for research, or be selected as a gym attacker. A Pokémon deployed to a gym cannot be made the companion. A player with no companion still earns steps; only companion Candy pauses. |
| D31 | **Moderation tools (D17):** see the list below. |
| D32 | **Gym defender weakening (D24):** the defender's battle HP is `ceil(canonical_HP × (2.0 − 0.1 × h))`, where `h` is the number of full hours since deployment (0–7). That is 2.0× when placed and 1.3× in its last hour; at 8 hours it goes home. The value is frozen when a battle starts. Stored CP, level, IVs and HP never change. |
| D33 | **One step per word (D18).** A word is a Unicode word segment ([UAX #29](https://www.unicode.org/reports/tr29/)) with at least 2 letters or digits, counted after removing URLs, mentions, emoji, code blocks and quoted lines. A message needs at least **4** eligible words, and at most **20** count. The same word, ignoring case, counts at most **3** times per message. **Order:** filter words, apply the repetition cap, check the 4-word minimum, then apply the 20-word message cap, cooldown and rate caps. Example: "hello hello hello hello" leaves 3 eligible words after the cap, so the message is rejected. The duplicate-message window, 15-second cooldown, 30-steps-per-minute cap and every D20 number stay the same: an average English word is about 5 characters, so one word replaces the old 5-character step. |
| D34 | **Starter choice (D16).** On their first `/walker` in a server, the player picks one starter from the base forms of every main-series generation's starter trio: Generations 1–9, 27 species. They get exactly one starter per server profile. The starter's species and evolution family count as part of the launch roster. |
| D35 | **Release split:** see the table below. |
| D36 | **CP only, no visible levels.** Players see Combat Power, never a Pokémon level. Level stays an internal value (`level_x2`) because CP, power-up cost and catch difficulty are calculated from it. The power-up screen shows CP before → after and the cost. The details view shows CP, HP and the IV appraisal, but no level. |
| D37 | **Full roster.** Every main-series species in the pinned PokéAPI snapshot can be caught, including species Pokémon GO has not released. Each species' default form and its **regional forms** (Alolan, Galarian, Hisuian, Paldean) are separate encounters. **Legendary and Mythical** Pokémon can be caught as very rare walking encounters. **No special battle mechanics or transformations:** no Mega Evolution, Primal Reversion, Dynamax/Gigantamax, Z-Moves, Terastallization or other battle-only forms and moves. These forms are never encounters, items or gym options. Other cosmetic forms (Unown letters, Vivillon patterns and similar) use the default form for now. |

#### D35: Release split

Each release must be playable on its own in a single server. A row only depends on earlier rows.

| Release | Contents |
|---|---|
| **v1: walking loop** | Enrollment, onboarding with starter choice and starter kit; item-to-Stardust conversion (D61); `/walker-account privacy`, `opt-out`, `delete-data`; server channel config; word steps and anti-farming; 3-encounter queue and ❗; `/walker` reveal and catch (balls, berries, Master Ball confirmation, flee); CP and IV appraisal (level hidden, D36); paged storage view (250 slots, D44); send for research; Candy and Stardust; power-up; passive finds; `/checkin`; walking companion; Pokédex; type-themed routes, number set by the planner (D45); shiny and Shiny Lure; hotlinked sprites on encounter, catch, companion, storage-detail, Pokédex and share screens (D48–D49); moderation tools except `gym-recall` and `/walker-admin raids`; owner `/admin`; backups and the systemd service. |
| **v1.1: depth** | Evolution (Candy plus the D55 evolution items, with the Stardust purchase); Star Piece; storage and bag expansion; route unlocks. |
| **v2: gyms** | Per-server gyms and admin commands; the gym-only survivor roll, World Legendary Ticket, `/raid` and `/walker-admin raids` (D60); auto-simulated battles with text results and hotlinked sprites (D49); 8-hour tenure with hourly weakening; hourly gym income; `/walker-mod gym-recall`. |
| **Later** | Peer visits; a dowsing presentation for finds; interactive battle turns; raid *battles* (fighting a boss before catching; D60's catch-only `/raid` is v2); trading; Candy XL; events and featured routes. |

Why this split: v1 is the smallest version that has a reason to come back (catching, the
companion, the Pokédex) plus a place to spend resources (power-up). Its screens hotlink sprites,
so it needs no image rendering (no version renders images, D49). Gyms come later because they
need a stable roster, stats and moves, and the most transaction design.

#### D31: Moderation tools

All moderation commands are guild-only and reply ephemerally. They sit under `/walker-mod`
(default visibility Moderate Members), except the two Manage Server actions, which sit under
`/walker-admin` (default visibility Manage Server) so that Discord does not hide them from
anyone allowed to use them. `/walker` itself has no subcommands; account controls use
`/walker-account privacy`, `opt-out` and `delete-data`, because a Discord command with
subcommands cannot also be run bare. Every
command that **changes** something requires a reason and writes a moderation audit entry. The
read-only `status` and `log` need no reason and are not audited. The handler rechecks permissions on every use. Moderators never see message content.

| Command | Permission | Effect |
|---|---|---|
| `/walker-mod status member` | Moderate Members | Show a member's game summary in this server: enrolled/paused/excluded state, steps credited in the last hour and in total, steps discarded by anti-farming in the last hour, queue size, catches, and recent moderation actions. |
| `/walker-mod pause member duration? reason` | Moderate Members | Stop the member earning steps, finds, check-ins and companion Candy in this server, indefinitely or for 1 h / 24 h / 7 d. They can still open `/walker` and resolve queued encounters. `/walker` shows them that earning is paused and until when. |
| `/walker-mod resume member reason` | Moderate Members | Lift a pause early. |
| `/walker-mod exclude member reason` | Moderate Members | Block the member from every bot feature in this server. Their data is kept, and any gym defender is sent home; its unpaid hours are forfeited (D23). They can still use `/walker-account privacy` and `/walker-account delete-data`. |
| `/walker-mod include member reason` | Moderate Members | Reverse an exclusion. |
| `/walker-mod share-ban member reason` / `share-unban` | Moderate Members | Remove or restore the member's Share buttons in this server. |
| `/walker-mod gym-recall gym reason` | Moderate Members | Send a gym's defender home. Income for full hours already held is still paid. |
| `/walker-admin reset member reason` | **Manage Server** | Delete the member's profile in this server, after a confirmation that names the member and what is lost. It cannot be undone; it uses the same deletion markers as D28, so a restore cannot bring the profile back. |
| `/walker-admin raids on\|off reason` | **Manage Server** | Allow or block World Legendary spawns (D60) in this server, and pick the channel for the spawn announcement. Off by default until a channel is set. |
| `/walker-admin sharing on\|off reason` | **Manage Server** | Turn the Share feature on or off for the whole server. |
| `/walker-mod log member?` | Moderate Members | Show the last 25 moderation actions in this server, optionally for one member. |

Moderation cannot grant or edit items, Pokémon, Candy or Stardust. The audit records actor,
target, action, reason and time. It is deleted with the server's data, and a target's
`delete-data` does not remove moderation entries about them.

### Full-roster rules (D38–D41, approved by the owner 2026-11-04)

- **D38: Encounter model for the full roster (D37):** two routes with six slots each cannot hold
  over 1,000 species. Instead, each route has **type weights**; for example, a forest route
  favours Grass, Bug and Poison. The roll is over **encounter identities**: each species' default form, each regional form,
  and each D52 separate-encounter form, each with its **own** types, base stats and tier
  (Alolan Vulpix is Ice, ordinary Vulpix is Fire). An encounter first rolls a rarity tier,
  then picks an identity of that tier in proportion to its **route weight**: the higher of
  the route's weights for that identity's one or two types. Identities with weight 0 on that route are not eligible. The
  Legendary/Mythical tier ignores route types and picks uniformly among all of them. Proposed tiers, derived
  automatically from PokéAPI data. **Amended by D46 (wild final-stage restriction) and D50 (tier chances):**

  | Tier | Rule | Chance per encounter |
  |---|---|---|
  | Common | Base stage or single-stage species, base-stat total < 400 | 60% |
  | Uncommon | Middle stage with total < 500, or base/single-stage with total 400–499 | 30% |
  | Rare | Any non-final stage, or single-stage species, with total ≥ 500 | 3% |
  | Evolved | Final stage of a family with 2 or more members | 6% |
  | Legendary/Mythical | PokéAPI `is_legendary` or `is_mythical` | 1%, ignoring route types |

  A single-stage species is one that neither evolves nor evolves from anything; its total
  decides its tier. The tier sets the catch class: BCR 0.50, 0.30 and 0.15, 0.15 for Evolved,
  and **0.05** for Legendary/Mythical, which never flee after a failed throw (D47). Shiny odds
  stay 1/256 for every tier.
- **D39: GO-style stats for the full roster (D37):** calculate GO base stats for every species with
  the documented conversion, and label them as the bot's values. Every `round` in the
  conversion rounds halves **up** (`floor(x + 0.5)`), never to even. Fixture: Attack 5,
  Special Attack 35, Speed 50 gives `round(2×(7×35+5)/8) = round(62.5) = 63`, then
  `round(63 × 0.95) = round(59.85) = 60`. Apply no GO-specific
  exceptions: for species GO hasn't released there is nothing to match, and for released ones
  exact GO parity was never required.
- **D40: Candy and evolution for the full roster (v1.1):** Candy families come from PokéAPI
  evolution chains. Every evolution costs Candy by stage depth, not by member count. In a family whose
  longest chain has one evolution step, every evolution costs **50**; this includes Eevee's
  eight branches. In a two-step family, depth 0→1 costs **25** and depth 1→2 costs **100**;
  Applin→Flapple costs 25 and Dipplin→Hydrapple costs 100. *(Wording clarified 2026-11-04;
  the rule is unchanged.)* Evolution items follow D55. Every other condition (trade, friendship, time, location,
  move) becomes Candy-only, so every evolution is achievable. **Exception (D54): gender
  conditions are kept**, because a Pokémon keeps its gender (D53) when it evolves. For
  example, only female Combee become Vespiquen.
- **D40a: Catch rewards for the full roster.** Catch Candy and Stardust follow evolution
  depth in the species graph: depth 0 (including single-stage species) gives **3 Candy +
  100 Stardust**, depth 1 gives **5 + 300**, and depth 2 gives **10 + 500**.
  Legendary/Mythical species give **10 + 500**. The content import assigns this for every
  identity and checks that none is missing.
- **D40b: Gym start quota (v2).** The researched "5 battle starts per player per UTC day" is
  retired under D9. The 10-minute cooldown after each completed battle is the only start limit.
- **D41: Legendary/Mythical rules (D37):** they cannot defend gyms but can attack, following GO. They
  can be the companion, and they are protected from bulk research send like shinies.
### Starter and language (D42–D43, approved by the owner 2026-11-04)

- **D42: Starter stats (D34):** hidden level 10, each IV rolled 10–15, never shiny, gender rolled at creation
  from the species' `gender_rate` (as in D53), and favorited by default so it is protected from research send. It becomes the player's
  companion automatically and can be swapped at any time.
- **D43: English only.** Bot text, commands and step counting target English. Under the default
  UAX #29 rules each Chinese/Japanese ideograph is a one-character segment, which D33's
  two-character minimum rejects, and a run of Thai text is one word. That is accepted for now. Supporting other languages is a future
  requirements change.

### Storage, routes and scarcity (D44–D47, approved by the owner 2026-11-04)

- **D44: Storage size.** Pokémon storage starts at **250** (was 100). The 250-unit bag is
  unchanged. Expansion purchases stay in v1.1.
- **D45: More routes in v1.** v1 ships more than 2 type-themed routes. The planner sets the
  count and each route's type weights, based on the number of species, their types and
  their environments: PokéAPI `habitat` where present (it only covers early generations),
  otherwise types. Every non-legendary **encounter identity** (D38: default, regional and D52 forms) must be eligible on at least one v1 route; the content build checks this.
  Route unlocks stay in v1.1.
- **D46: Wild final-stage restriction.** Final evolutions of multi-member families appear
  only in the Evolved tier (D38; 6% after D50), so evolving stays the main way to get them.
- **D47: Scarcity is intended.** Legendaries and Mythicals are meant to drain balls: a 0.05
  catch class, no flee, and they hold a queue slot until caught or run from. Walking finds
  plus `/checkin` deliberately do **not** fully cover a top-pace player's ball use. Gym
  income (D13, D23) is the intended extra source. The economy simulation should confirm a
  shortfall that holding a gym closes; it should not remove the shortfall.

### Forms research decisions (D50–D58, approved by the owner 2026-11-04)

From the [forms research review](../../research/synthesis.md#7-review-of-the-pokéapi-forms-research-pr-6),
based on [pokeapi-forms.md](../../research/data-visuals/pokeapi-forms.md).

- **D50: Tier chances and empty tiers.** Common 60%, Uncommon 30%, Rare 3%, Evolved 6%,
  Legendary/Mythical 1% (see the D38 table). Across the whole roster each tier is then strictly rarer per **encounter identity**. A species with a regional form has two identities, so it is correspondingly more common. That is a baseline
  target; route filtering and redistribution may change the order on a single route, and that
  is acceptable.
  If a route has no eligible identity in the rolled tier, that tier's chance is spread
  proportionally over the route's other non-empty **non-legendary** tiers. Legendary/Mythical
  always stays at exactly 1%.
- **D51: Content source pin.** Content builds from PokéAPI commit
  `e5b79b2e15d7c50735a945936afd4cd1cfd94eae`, using the research's filter and
  named-exception list. Updating the pin is a reviewed content change. The roster baseline is
  1,082 identities before D52 additions.
- **D52: Non-regional forms with different stats.**
  - *Default form only:* Deoxys, Dialga/Palkia/Giratina Origin, Tornadus/Thundurus/Landorus/
    Enamorus Therian, Kyurem, Necrozma and Calyrex fusions, Hoopa, Shaymin, Zygarde 10%,
    Arceus and Silvally types, Ogerpon masks, Eternal Flower Floette, Partner Pikachu/Eevee,
    Rotom appliances, Roaming Gimmighoul, and Minior (Meteor only, no cores).
  - *Separate encounters:* Wormadam cloaks, Oricorio styles, Pumpkaboo and Gourgeist sizes,
    Bloodmoon Ursaluna.
  - *Evolution branches* chosen when evolving: Lycanroc forms, Urshifu styles.
  - There is no form-change mechanic.
- **D53: Gender.** Gender is rolled when an encounter is queued, from PokéAPI `gender_rate`,
  and frozen. It picks the female sprite where `has_gender_differences`, and the variety for
  Indeedee, Basculegion and Oinkologne. For those three, the encounter identity is the
  species: its tier and route weight come from the default (male) variety, and the
  gender rolled afterwards picks which variety is created. **Exception:** for these three,
  gender is rolled **50/50** whatever PokéAPI's `gender_rate` says. The pinned data gives
  Oinkologne `gender_rate = 0`, which would make its female variety unreachable. The content
  build checks that both varieties of all three are reachable. Genderless species have none.
- **D54: Evolution routing.** Evolution uses the form-aware routes; for example, only Galarian
  Linoone evolves to Obstagoon. Tiers use the species graph. Forms that matter only for
  evolution (White-striped Basculin, Own Tempo Rockruff, Burmy cloaks) use the default
  appearance; the player chooses the branch target when evolving, and a Burmy's gender
  decides Mothim or Wormadam. Gender conditions are the one kept exception to D40's
  condition stripping.
- **D55: Evolution items (amends D40 and the earlier 7-item list).** The item set is every
  main-series evolution item that a retained route uses in the pinned data: elemental stones,
  King's Rock, Metal Coat, Dragon Scale, Up-Grade and so on. There is no Sinnoh or Unova
  Stone. Item drops and the 500-Stardust purchase cover exactly this set.
- **D56: Shedinja** is catch-only, as a wild Evolved-tier encounter. Nincada evolves only to
  Ninjask.
- **D57: Ultra Beasts and Paradox Pokémon** follow PokéAPI's flags. Ultra Beasts and the
  ordinary Paradox Pokémon have neither flag, so they use the normal tiers and D41 does not
  apply to them. **Koraidon and Miraidon** are Paradox Pokémon but flagged Legendary in
  PokéAPI, so they are Legendary: 1% tier, BCR 0.05, D41, and the D59 Paradox duo group.
- **D58: Eternamax** is excluded as a battle-only transformation (D37), despite its PokéAPI
  flag. Arceus's legacy "unknown" type form is excluded.

### Pokédex milestones (D59, owner request 2026-11-04; reward contents set by the reviewer)

- **D59: One-time Pokédex milestone rewards (v1, with D15).** Each milestone pays once per
  server profile, as soon as its condition is met. Milestones count **caught** species (D15).
  Pokédex entries are never removed, so a milestone can never be lost. Rewards go to a
  **reward inbox** on `/walker`, and **Claim** moves whatever fits. Ordinary items wait for
  bag space and rare items for an empty rare pocket, so a milestone reward is never converted
  or lost. Percentages use the species count of the installed content (1,025 at the D51 pin);
  a milestone already earned stays earned if that count changes.

  Reward bundles, set by difficulty. All items exist in v1. The economy simulation checks
  their size before launch.

  | Bundle | Contents |
  |---|---|
  | Bronze | 10 Great Balls, 5 Razz Berries, 500 Stardust |
  | Silver | 10 Ultra Balls, 3 Golden Razz Berries, 2 Rare Candy, 2,000 Stardust |
  | Gold | 20 Ultra Balls, 5 Golden Razz Berries, 5 Silver Pinap Berries, 5 Rare Candy, 5,000 Stardust, 1 Shiny Lure |
  | Platinum | 30 Ultra Balls, 10 Golden Razz Berries, 10 Rare Candy, 15,000 Stardust, 1 Master Ball |
  | Diamond | 50 Ultra Balls, 20 Golden Razz Berries, 25 Rare Candy, 50,000 Stardust, 1 Master Ball, 1 Shiny Lure |

  | Milestone | Condition | Bundle | Why this tier |
  |---|---|---|---|
  | Pokédex 5% / 10% | 52 / 103 species caught | Bronze / Bronze | Common and Uncommon catches alone |
  | Pokédex 25% | 257 | Silver | Needs most route types |
  | Pokédex 50% | 513 | Gold | Needs Rare and Evolved species, or evolution (v1.1) |
  | Pokédex 75% / 90% | 769 / 923 | Platinum / Platinum | Nearly every non-legendary species |
  | Pokédex 100% | 1,025 | Diamond | Every Legendary and Mythical |
  | Starter trio, ×9 | The three base starters of one generation (Kanto 1/4/7, Johto 152/155/158, Hoenn 252/255/258, Sinnoh 387/390/393, Unova 495/498/501, Kalos 650/653/656, Alola 722/725/728, Galar 810/813/816, Paldea 906/909/912) | Bronze each | Common-tier species; the chosen starter already counts |
  | All 27 starters | Every trio above | Gold | Spread across many route types |
  | Region complete, ×9 | Every species of one generation, Legendaries and Mythicals included | Platinum each | Includes that region's Legendaries |
  | First Legendary / first Mythical | Any one caught | Silver / Silver | 1% tier, then the 0.05 catch class |
  | Legendary group, ×19 | Birds 144/145/146; Beasts 243/244/245; Tower duo 249/250; Regis 377/378/379/486/894/895; Eon duo 380/381; Weather trio 382/383/384; Lake trio 480/481/482; Creation trio 483/484/487; Swords of Justice 638/639/640; Forces of Nature 641/642/645/905; Tao trio 643/644/646; Aura trio 716/717/718; Guardian deities 785–788; Light trio 791/792/800; Hero duo 888/889; Calyrex and steeds 896/897/898; Treasures of Ruin 1001–1004; Paradox duo 1007/1008; Loyal Three 1014/1015/1016 | Platinum each | Several specific Legendaries |
  | Mythical set, ×5 | All Mythicals of one generation that has two or more: Gen 3 385/386; Gen 4 489–493; Gen 5 494/647/648/649; Gen 6 719/720/721; Gen 7 801/802/807/808/809 | Platinum each | Several specific Mythicals |
  | All Legendaries / all Mythicals | All 71 / all 23 | Diamond / Diamond | The full rare pool |
  | Ultra Beast first catch, ×11 | First catch of each: 793 Nihilego, 794 Buzzwole, 795 Pheromosa, 796 Xurkitree, 797 Celesteela, 798 Kartana, 799 Guzzlord, 803 Poipole, 804 Naganadel, 805 Stakataka, 806 Blacephalon | Silver each | Owner exception: Ultra Beasts aren't Legendary in PokéAPI (D57) |

  Regional forms count toward their species (D15), so Galarian birds complete the Birds group.

  **Evolution-line milestones (owner request 2026-11-04).** Catching every species of an
  evolution family pays a one-time **25 Candy of that family + 1 Ultra Ball + 250 Stardust per
  species in the line** (500 for a two-species line, 750 for three, 2,250 for Eevee's nine). A family
  qualifies when it has two or more species joined by at least one real evolution; in the
  D51 pin that is **340 families covering 824 species**. Single-species families do not
  qualify. Neither does Phione/Manaphy, which share a chain ID but have no evolution between
  them (D54). Species gained by evolving count, because evolving marks the result as caught
  (D15). Four lines contain Legendary or Mythical species and also pay a difficulty bundle:

  | Line | Species | Extra bundle | Why |
  |---|---|---|---|
  | Type: Null line | 772, 773 | Gold | One specific Legendary catch, then evolve |
  | Kubfu line | 891, 892 | Gold | Same |
  | Meltan line (Mythical) | 808, 809 | Gold | Same, for a Mythical |
  | Cosmog line | 789, 790, 791, 792 | Platinum | Both Solgaleo and Lunala branches: two Cosmog, or two lucky catches |
  | Poipole line (Ultra Beast) | 803, 804 | Silver | Owner exception: Ultra Beasts aren't Legendary in PokéAPI (D57), but their line still earns a bundle |

  The content build derives the list from the pinned families (D54) and fails if a
  qualifying family has no milestone.

  **Required acceptance case for awarding:** a catch completes a milestone, the process restarts
  after the award commits, and completion checking runs again. Exactly one award must exist,
  keyed by (profile, milestone), and its earned record and inbox contents commit together.

  **Required acceptance case for the inbox:** a Gold reward is claimed while the Shiny Lure
  pocket is full, so Stardust and items are credited and the Lure stays in the inbox. Then
  the player clicks Claim twice at once, and the process restarts after commit but before
  the reply. Credited plus remaining quantities must always equal the original reward, and
  no currency is ever paid twice.

### Gym survivor reward and World Legendaries (D60, owner request 2026-11-04; weights and catch details set by the reviewer)

- **D60: Survivor roll (v2).** A defender that completes its full 8-hour tenure (D24)
  **without being defeated** earns its owner one extra **survivor roll** when it goes home,
  in addition to the hourly items (D23). Every survivor roll also pays a flat **500 Stardust**,
  whatever the item outcome. Recall, moderator recall, exclusion or a lost battle
  forfeits it. The roll uses a **gym-only table** that never appears in passive finds or
  check-ins. Weights out of 10,000:

  | Outcome | Weight | Chance |
  |---|---:|---:|
  | 5 Ultra Balls (weight reduced by owner decision 2026-11-12) | 2,000 | 20% |
  | 3 Golden Razz Berries | 2,000 | 20% |
  | 3 Silver Pinap Berries | 1,500 | 15% |
  | 5 Rare Candy | 1,500 | 15% |
  | 2 Star Pieces | 1,000 | 10% |
  | Shiny Lure | 800 | 8% |
  | Master Ball | 600 | 6% |
  | Companion Mirror (owner decision 2026-11-12) | 500 | 5% |
  | **World Legendary Ticket** | 100 | 1% |

  Rewards land in the D59 reward inbox, so a full bag or rare pocket never converts or loses
  them.

- **World Legendary Ticket.** A rare item, at most 1 held; a second waits in the inbox. Using
  it from `/walker` (with a confirmation) spawns a **World Legendary** in that server.
  - The spawn is one random **Legendary** encounter identity (Mythicals excluded), chosen
    uniformly and ignoring routes.
  - It lasts **60 minutes** from the spawn, measured in UTC and kept across restarts.
  - Only one World Legendary can be active per server. The ticket is consumed only when the
    spawn is committed, and never comes back; if raids are off, no channel is set, the bot lacks permission to post
    there, or one is already active, it is refused and kept.
  - The bot posts **one public embed** with the Pokémon's picture (D48 sprite rules) in the
    admin-chosen raid channel, naming the species and the despawn time. This is a deliberate
    exception to D2: no pings and no DMs (D4). Delivery is **at most once**. Every send attempt for a spawn reuses one Discord
    `nonce` with `enforce_nonce`, and the bot retries only within Discord's short nonce
    window. Once any attempt might have reached Discord (a timeout or a crash), the bot never
    posts again for that spawn. A missing announcement is accepted over a duplicate. **A
    committed spawn is never refunded or cancelled.** The permission check before spending
    is the only guard. Members can still find the spawn
    with `/raid`. Required acceptance case: crash after Discord accepts the post but before its
    ID is saved, then restart. There must be no second post and no refund.
- **`/raid`** works only while a World Legendary is active in the server; otherwise it
  explains that none is active. Any enrolled, non-excluded member can join once per spawn. Running
    `/raid` again during the same spawn reopens that player's saved encounter; it never
    creates or rerolls another. Participation is keyed by (server, user, spawn), not by
    profile, and survives `delete-data` until the spawn expires (D28). Required acceptance
    case: join → delete data → re-enroll → `/raid` gives no new encounter.
  - Joining gives the player a **private encounter** of the spawn's exact identity, species
    and form; Galarian Articuno stays Galarian. It is outside the
    3-encounter queue (D5) and has its own level, IVs, gender and shiny roll (1/256; a Shiny
    Lure active at join time applies, as for any encounter generated while it is active).
  - It uses the normal catch flow with the Legendary catch class (BCR 0.05, never flees,
    D38/D47).
  - When the spawn expires, unfinished raid encounters disappear; balls already thrown stay
    spent. A catch counts for the Pokédex and every D59 milestone.
- **Required acceptance case (expiry):** with an injected clock, open a raid catch panel before
  expiry, advance past expiry while cleanup is still pending, then press Throw. The throw is
  rejected and spends nothing. A catch committed before expiry survives cleanup.
- **Required acceptance case:** interrupt a survivor return after the roll is saved but before
  it finishes, then retry. There must be one saved roll, one 500-Stardust award and one
  completed return; the return and its payout commit together.

### Converting items to Stardust (D61, owner request 2026-11-04; values set by the reviewer)

- **D61: Item conversion (v1).** From the `/walker` bag, a player picks an item and a
  quantity. The bot previews the total, and a confirmation converts the items to Stardust in
  one transaction. Conversion can't be undone. Rare items need a second confirmation that
  names them. The rates sit deliberately below what the items are worth, so conversion
  frees bag space and doesn't become an income source:

  | Item | Stardust per unit |
  |---|---:|
  | Poké Ball | 2 |
  | Great Ball | 5 |
  | Ultra Ball | 10 |
  | Razz Berry, Pinap Berry | 5 |
  | Golden Razz Berry, Silver Pinap Berry | 25 |
  | Rare Candy | 20 |
  | Star Piece (v1.1) | 50 |
  | Evolution item (v1.1; sells for 500) | 100 |
  | Master Ball, Shiny Lure | 500, the same as the duplicate rule |
  | World Legendary Ticket (v2) | Can't be converted |

  For scale: a bag of 30 Poké Balls converts to 60 Stardust, while an ordinary catch pays
  100–500. Items waiting in the reward inbox can't be converted until claimed. Required
  acceptance case: confirm the same conversion of 5 of 20 Poké Balls twice, including a
  restart after commit but before the reply. The result must be exactly 15 balls and +10
  Stardust, using the action-receipt rule.

## Open questions

- **Legendary pacing versus D59.** Under D38/D50 one *identity* in the Legendary/Mythical tier appears in about
  1 in 9,700 encounters (1% split over 97 identities). A species with two identities, such as
  each legendary bird with its Galarian form, appears about 1 in 4,850. Seeing all three birds
  takes about 8,900 encounters on average, and a single-identity trio about 17,800, before
  catch time. That is thousands of active hours. The group and "all" milestones are
  effectively out of reach unless the owner adds a way to target Legendaries, for example a
  per-server **featured Legendary group** that receives most of the 1% tier for a set
  period. Owner decision; the economy simulation should report the expected times.

- **Send to research from the catch screen** ([synthesis §5](../../research/synthesis.md#5-scope-additions-worth-considering)):
  the owner requested it, but it is not yet a decision, including whether an automatic
  duplicate-send setting exists. It is out of plan scope until decided.

The first `PLAN.md` rows are, in order: the content import and the chat-rate
measurement (independent of each other), then the economy simulation, which uses both the
imported tier sizes and the measured chat rates ([synthesis §4](../../research/synthesis.md#4-gaps-further-research-and-work-recommended),
items 1–3). Application work follows them.

## Platform constraints

- Reading message text needs the privileged Message Content intent. Discord reviews
  intent access once the app reaches **10,000 unique users** across its servers
  (changed June 2026). App verification to grow past 100 servers is a separate
  process. See [intents research](../../research/discord-intents-permissions.md).
- Removing the bot's **own** ❗ reaction does not need Manage Messages.
- The opt-in share (D19) and the World Legendary announcement (D60) are the only features that post messages: it needs `EMBED_LINKS` plus `SEND_MESSAGES` (normal channels) or `SEND_MESSAGES_IN_THREADS` (threads).
- Any Catch/Run handler has to stop double-click races, and only the encounter's
  owner may act on it.

## Delivery workflow (owner intent)

1. Codex Pro messages research the open topics into `docs/research/`. Claude then
   reviews that research summary.
2. Plan loop: Claude writes the first `PLAN.md` (`feature-pipeline:plan`). Codex
   runs the audit/review → revise rounds. Claude does a final check before drive.
3. `feature-pipeline:drive`: Codex implements.
4. Post-drive loop: Claude reviews the diff against the plan, and Codex fixes. The
   reviewer is never the model that wrote the code. Claude writes subtle concurrency
   fixes itself.

Stopping rule for each loop: stop when a round finds no high- or medium-severity
issues, with a cap of about 3 rounds. If issues persist after that, send the plan
back to Claude instead of running more rounds.
