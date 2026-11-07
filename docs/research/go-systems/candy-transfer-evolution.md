# Candy, research transfers, and evolution

Scope: A5–A6 and B2–B3. Checked **2026-11-04**. **Official** means a Pokémon GO support article or announcement; **community reference** means documented game behavior, not a published server specification; **empirical** means an identified original experiment. **UNVERIFIED** identifies a gap. Bot numbers below are recommendations, not GO facts.

## Facts: Pokémon GO

### Candy families and ordinary rewards

Candy is shared by an evolutionary family: Bulbasaur, Ivysaur, and Venusaur use Bulbasaur Candy. Stardust is usable across families. Candy XL is a separate, family-specific resource for higher power-ups. **Official:** [powering up · checked 2026-11-04][power].

Ordinary rewards, before event and item bonuses:

| Action | Ordinary family Candy | Candy XL, if eligible | Evidence |
|---|---:|---|---|
| Catch a base reward-tier Pokémon | 3 | Chance; not guaranteed | [Community reference · checked 2026-11-04][candy] |
| Catch an evolved reward-tier Pokémon | 5 | Evolved catches can provide more XL | [Community reference · checked 2026-11-04][candy] |
| Catch a fully evolved reward-tier Pokémon in a three-stage line | 10 | Evolved catches can provide more XL | [Community reference · checked 2026-11-04][candy] |
| Transfer to the Professor | 1 | Chance of 1; see study below | [Community reference · checked 2026-11-04][candy] |
| Evolve | 1 returned after paying the displayed cost | Chance | [Community reference · checked 2026-11-04][candy] |

These reward tiers are not a license to derive payouts from arbitrary main-series evolution-tree depth. **UNVERIFIED:** a complete current mapping of babies, forms, exceptional species, and catch reward tiers was not established here. Store verified rewards explicitly.

Baby additions can affect candy naming: the Hitmonlee/Hitmonchan currencies became Tyrogue Candy. Nidoran♀ and Nidoran♂ retain separate families. **Community reference:** [Candy (GO) · checked 2026-11-04][candy]. An English species name, National Dex ordering, or a shared type is therefore not a safe family identifier.

### Candy XL and transfer probability

The current help article says Candy XL becomes collectible at **Trainer level 31**. A 2026 official season announcement still explicitly uses level 31+ for its trade XL bonus; the announcement's guaranteed trade reward is a season bonus, not proof of a universal trade rule. **Official:** [powering up · checked 2026-11-04][power]; [Memories in Motion · checked 2026-11-04][season].

The Silph Research Group's **2021 original transfer study** examined over 20,000 transfers. It observed at most one XL per transfer and estimated these level-dependent chances:

| Pokémon level band studied | Estimated chance of 1 Candy XL |
|---|---:|
| 1–14 | 2.5% |
| 15–19 | 12.5% |
| 20–22 | 25% |
| 23–25 | 37.5% |
| 26–30 | 50% |
| 31–35 | 75% |

**Empirical, historical:** [original study, archived · checked 2026-11-04][xl-study]. These are inferred probabilities, not officially published constants. The study transferred Pokémon individually without first evolving, trading, or powering them up. **UNVERIFIED:** exact 2026 transfer probabilities, behavior above level 35, and equivalence of bulk transfer. Do not extrapolate the table into an exact current server implementation.

### Where resources come from

| Resource | Documented sources | Evidence |
|---|---|---|
| Family Candy | Catches, hatches, Professor transfers; buddy walking also earns Candy | [Official · checked 2026-11-04][power]; [official buddy documentation · checked 2026-11-04][buddy] |
| Stardust | Catches, hatches, research, battling | [Official · checked 2026-11-04][power] |
| Family Candy XL | Chance from catches, transfers, hatches, evolution, trades, gym berry feeding, and buddy walking; regular Candy can be converted | [Official · checked 2026-11-04][power] |

The documented conversion is **100 ordinary Candy → 1 Candy XL**. **Community reference:** [Candy (GO) · checked 2026-11-04][candy]. Power-up costs and their limits are in [cp-ivs-leveling.md](cp-ivs-leveling.md); catch modifiers and Rare Candy are in [items-and-catching.md](items-and-catching.md).

### Evolution costs and conditions

Evolution spends a species-specific amount of family Candy, sometimes with items or another condition. Evolution transforms the selected Pokémon rather than adding a storage entry. **Official:** [evolving your Pokémon · checked 2026-11-04][evolve]. Representative costs illustrate why a single price per stage is insufficient:

| Evolution | Required resource | Evidence |
|---|---|---|
| Caterpie → Metapod → Butterfree | 12, then 50 Candy | [Community reference · checked 2026-11-04][evo-table] |
| Grookey → Thwackey → Rillaboom | 25, then 100 Grookey Candy | [Official launch announcement · checked 2026-11-04][galar] |
| Magikarp → Gyarados | 400 Candy | [Community reference · checked 2026-11-04][evo-table] |
| Applin → Flapple / Appletun | 200 Applin Candy + 20 Tart / Sweet Apples respectively | [Official launch announcement · checked 2026-11-04][apples] |
| Roaming Form Gimmighoul → Gholdengo | 999 Gimmighoul Coins | [Official announcement · checked 2026-11-04][coins] |

Established evolution items include the following. This is a useful baseline catalog, not a claim that no later special item exists.

| Item | Example evolution(s) | Evidence |
|---|---|---|
| Sun Stone | Gloom → Bellossom; Sunkern → Sunflora | [Community reference · checked 2026-11-04][evo-table] |
| King's Rock | Poliwhirl → Politoed; Slowpoke → Slowking | [Community reference · checked 2026-11-04][evo-table] |
| Metal Coat | Onix → Steelix; Scyther → Scizor | [Community reference · checked 2026-11-04][evo-table] |
| Dragon Scale | Seadra → Kingdra | [Community reference · checked 2026-11-04][evo-table] |
| Up-Grade | Porygon → Porygon2 | [Community reference · checked 2026-11-04][evo-table] |
| Sinnoh Stone | Rhydon → Rhyperior; Porygon2 → Porygon-Z | [Community reference · checked 2026-11-04][evo-table] |
| Unova Stone | Lampent → Chandelure; Minccino → Cinccino | [Community reference · checked 2026-11-04][evo-modern] |
| Tart / Sweet Apple | Applin branches, as above | [Official · checked 2026-11-04][apples] |

Other condition patterns worth preserving in a rules model:

| Pattern | Verified example / limitation | Evidence |
|---|---|---|
| Trade discount | Eligible traded Pokémon, including Kadabra, Machoke, Graveler, and Haunter, can evolve without Candy. Receiving a trade does not automatically evolve them. | [Official · checked 2026-11-04][trade] |
| Buddy task | Feebas requires buddy walking; some species require tasks shown on their details screen. | [Official · checked 2026-11-04][evolve] |
| Hearts | Sylveon's ordinary requirement is 70 hearts; the cited 2021 event reduced it to 7 temporarily. | [Official historical announcement · checked 2026-11-04][sylveon] |
| Nearby lure | Certain species require proximity to a particular active Lure Module. | [Official · checked 2026-11-04][evolve] |
| Time, sex, branch, or battle condition | GO includes day/night and sex restrictions and species-specific conditions; use individual verified rules. | [Community evolution catalog · checked 2026-11-04][evo-modern] |

**UNVERIFIED:** a complete, current species/form evolution catalog is outside this researched sample. Do not silently translate every PokéAPI evolution requirement into a GO rule.

### GO's transfer safeguards

Transfer is irreversible. GO blocks transfers of favorites, current buddies, and gym defenders. Its bulk flow excludes Shinies, Lucky Pokémon, and buddies at Good Buddy or higher; bulk Legendary/Mythical transfer needs a settings opt-in, and some special Pokémon cannot be transferred. **Official:** [transferring Pokémon · checked 2026-11-04][transfer].

## Recommendations: bot v1

### Resource economy — DESIGN DEFAULTS

**Keep family Candy and universal Stardust; omit Candy XL.** Family Candy rewards repeated encounters with a line. Stardust makes power-up and storage purchases compete for a shared budget. Retain the level-40 v1 ceiling and power-up bands in [cp-ivs-leveling.md](cp-ivs-leveling.md). Avoid a separate trainer XP economy in v1.

| Source / sink | Recommended v1 behavior |
|---|---|
| Successful catch | Explicit reward tier: **3 / 5 / 10 family Candy + 100 / 300 / 500 Stardust**. Store tier on species/form data. |
| Send for research | **1 family Candy per Pokémon; 0 Stardust**. Same reward regardless of level, IVs, evolution, or shiny status. |
| Eligible walking | Every item-find event also gives **20 Stardust**, independent of the item result. Initial cadence **1 find per 100 awarded steps, maximum 10 finds per player per UTC day**: at most **200 base walking Stardust/day before Star Piece bonuses**. Item-specific resource drops are additional; see item table. |
| Rare Candy item | Convert **1 item → 1 Candy** for a chosen, explicitly displayed family. |
| Evolution | Pay the configured Candy/item cost; **no Candy refund or XP** in this adaptation. |
| Power-up | Pay Candy plus Stardust using the specified v1 cost bands. |
| Storage expansion | Spend Stardust using [storage-and-data-model.md](storage-and-data-model.md). |
| Buddy walking | Defer passive family Candy until eligible-step pace is measured. |
| Gym reward interface | Reserve a resource-award hook with an idempotency key; award **0** until the separate gym design supplies a budget. |

These values are tuning proposals. Count only steps admitted by anti-spam rules; process message edits, duplicate deliveries, and cross-server activity under the selected progression scope. Do not reward raw uncapped characters. Apply the same scope to resource balances and their daily limits.

No power-up refund on research transfer; otherwise spending and reclaiming can undermine the resource sink. Shiny and high-IV Pokémon should not provide a research premium that pressures players to destroy collectibles. Pinap modifies catch Candy only, according to the item rules. Effects and event configuration must not accidentally multiply transfer rewards.

### Family and evolution policy

Use an immutable `candy_family_id` independent of display names, species IDs, and regional forms. A curated family map should include baby and branched species; map regional forms explicitly. Do not create a new currency just because a display name changes. Validate every supported evolution edge with source provenance and a ruleset version.

For v1, ship verified Candy-only edges and supported edges using the seven standard evolution items, from Sun Stone through Unova Stone in the table above. The proposed **500 Stardust per item** shop provides a deterministic alternative to walking drops; see [items-and-catching.md](items-and-catching.md). Defer unavailable buddy, lure, time, trade, apple, or special-resource conditions with a visible “not available yet” explanation. Never advertise an evolution whose requirement players cannot satisfy. Offer explicit branch selection rather than nickname tricks or a hidden random branch.

Show the destination form, Candy/item price, current balance, and resulting CP before confirmation. Atomically spend resources and update the existing instance. Preserve IVs, level, shiny status, original catch provenance, favorite/lock state, and stable instance ID; recompute CP for the destination. Do not charge Stardust merely for evolution. Reject the entire action if ownership, instance version, conditions, balance, or assignments changed since preview.

### “Send for research” flow — DESIGN DEFAULTS

1. Open **Storage → Send for research** privately. Show **5 candidates per page** with toggle buttons, Previous/Next, Review, and Cancel. Keep selection across pages using stable instance IDs. Cap one batch at **20**.
2. Default suggestions contain ordinary duplicates only. Exclude favorites, explicit locks, Shinies, catalog-marked special/rare Pokémon, active buddies, and any Pokémon assigned to a gym or other exclusive activity. Display why excluded Pokémon are protected.
3. Review the exact selected Pokémon with species/form, CP, IV appraisal, and identifiers. Summarize **Candy totals by family**, count, and the irreversible removal. Require a distinct **Send N Pokémon** button; selecting candidates never sends them.
4. Expire the review after **120 seconds**. Cancel or expiry changes nothing. A stale review refreshes the selection and requires a new confirmation.
5. Shiny/special Pokémon remain excluded from bulk sending even after manual unlocking. A single send requires opening that Pokémon, explicitly removing its research lock, then confirming a second warning showing the shiny/special status. Favorites must be unmarked separately. Assignment protections cannot be overridden by the transfer button.

Never auto-send a Pokémon to make room. A full-storage catch should use the recovery flow in [storage-and-data-model.md](storage-and-data-model.md).

### Transaction requirements

- Button payloads reference a server-side review token, owner, scope, expiry, instance IDs/versions, and reward quote. Recheck actor ownership; do not trust amounts supplied by the client.
- On confirmation, lock or version-check the selected instances and balances. Revalidate every protection and assignment. **All-or-nothing:** if one candidate changed, remove none and issue a new review.
- Mark instances sent and credit the exact family totals in one transaction. Persist a research receipt and reward-ledger entries; uniquely constrain the operation ID and each instance's completed research disposition.
- Repeated clicks, Discord retries, concurrent sessions, and a restart after commit return the existing receipt. They must never grant rewards twice. The receipt is evidence of the committed result; it is not an undo mechanism.

### Open decisions

- Confirm global versus per-server progression scope before creating balances or daily caps.
- Measure eligible steps, catches, and family concentrations before enabling buddy Candy or increasing rewards.
- Choose the first supported evolution roster and which evolution items can actually drop.
- Decide whether special/rare protection is mandatory or configurable; keep shiny exclusion from bulk sending mandatory.

[power]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/2372-powering-up-pokemon/
[buddy]: https://pokemongo.com/news/buddy?hl=en
[evolve]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/100-evolving-your-pokemon/
[transfer]: https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1124-transferring-pokemon/
[candy]: https://bulbapedia.bulbagarden.net/wiki/Candy_(GO)
[xl-study]: https://web.archive.org/web/20220714174430/https://thesilphroad.com/science/guide-candy-xl-part-3-transferring
[season]: https://pokemongo.com/seasons/memories-in-motion
[evo-table]: https://www.serebii.net/pokemongo/evolution.shtml
[evo-modern]: https://pokemondb.net/go/evolution
[galar]: https://pokemongo.com/news/go-out-galar-region
[apples]: https://pokemongo.com/news/sweet-discoveries-2025
[coins]: https://pokemongo.com/news/gocoin
[trade]: https://pokemongo.com/news/trade-evolution
[sylveon]: https://pokemongo.com/news/communityday-aug21
