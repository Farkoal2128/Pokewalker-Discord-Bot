# Pokémon GO gym mechanics

Scope: A1–A5. **All sources checked 2026-11-04**; each source entry repeats that date. “Official” describes published game rules; “community” describes independently maintained references or experiments. A historical experiment does not establish unchanged server behavior today. Reuse [task 2's CP inputs](../go-systems/cp-ivs-leveling.md); this file does not redefine progression.

## Facts

### 1. Control, slots and defender eligibility

| Rule | Evidence |
|---|---|
| Teams are **Instinct / yellow, Mystic / blue, Valor / red**. | Official help [^G1]. |
| A gym holds **6 defenders**, at most **1 per Trainer** and **1 of each species**. An empty gym can be claimed by any team; teammates fill remaining slots. Attackers bring up to **6 Pokémon**. | Official help [^G2]. |
| Defenders fight in placement order, oldest first. Removing every defender opens the gym for a new claim. | Official gym-system announcement [^G3]. |
| Legendary Pokémon cannot defend gyms; they can attack. A currently Mega-Evolved Pokémon cannot defend. | Official restrictions [^G4][^G5]. |
| Meltan and Melmetal are documented Mythical exceptions that can defend. | Current community species reference [^G6]; not a publisher-maintained complete eligibility list. |

**UNVERIFIED:** a complete current eligibility catalog covering every special form, Ultra Beast, buddy/health state and global simultaneous-deployment limit. Do not infer eligibility solely from PokéAPI's `is_legendary` / `is_mythical` flags. The confirmed restrictions above are not an exhaustive validation specification.

### 2. Motivation, berries and removal

**Official behavior:** motivation falls with elapsed time and lost battles, temporarily reducing displayed CP. Reaching the minimum does not itself send a defender home: a further defeat removes it. Friendly-team members can feed defenders; Golden Razz restores full motivation. [^G3] Remote ordinary feeding is less effective. [^G2]

**Historical community decay model:** DrThod's measurements model the time from full displayed CP to its floor using the Pokémon's **full CP**, not repeatedly recalculating from its shrinking CP. With `C = full CP`, the fitted duration `T` is: [^G7]

| Full CP | Approximate `T` |
|---|---:|
| **10–300** | **72 hours** |
| **301–2,322** | **250.35 − 72 × log10(C) hours** |
| **2,323+** | **8 hours** |

The observed displayed-CP floor was **20% of full CP**, so the corresponding loss is approximately `0.8 / T` of full CP per hour: **1.11%–10%** across the table, derived. These fractions describe displayed CP, not a claim that the motivation heart stops at 20%. Exact fit/rounding and continued applicability in 2026 are **UNVERIFIED**. [^G7]

**Historical feeding/removal observations:** community guides report about **3 defeats** to remove a fully motivated defender without intervening feeding, diminishing returns from repeated ordinary berries, and a feeding allowance of **10 berries per Pokémon**, covering up to **10 Pokémon per 30 minutes**. Treat these as published observations, not verified current server constants. [^G8]

**Source conflict:** official help describes ordinary berries as restoring equal motivation, while original berry experiments measured different Nanab restoration. Exact current berry curves/quotas are **UNVERIFIED**; both agree Golden Razz restores full motivation. Avoid implementing the old experimental percentages as authoritative current rules. [^G2][^G9]

### 3. PvE battles: actions, damage, energy and automation

#### Actions and energy

Fast attacks build energy; charged attacks spend it. Swiping dodges; zero HP causes a faint. [^G2] The same charged move can have different energy requirements in Gym/Raid battles and Trainer Battles. [^G10]

Published community PvE models use an energy cap of **100**, with familiar charged costs of **33 / 50 / 100**; fast gains and move durations depend on the move. Taking damage can also provide energy. Treat move-specific values as versioned PvE data, not a permanent three-cost whitelist. Exact current damage-to-energy rounding and source-specific exceptions are **UNVERIFIED** here. [^G11]

#### Ordinary damage model

Original gym experiments and a currently maintained community calculator support this ordinary pre-dodge model: [^G12][^G13]

`damage = floor(0.5 × move_power × attacker_Attack / defender_Defense × modifiers) + 1`

`modifiers = STAB × type_effectiveness × weather × other_applicable_bonuses`

Attack and Defense are the actual combat stats from the [progression model](../go-systems/cp-ivs-leveling.md), **not a CP ratio**. This is a community model, not a publisher-supplied specification of the entire current engine. The final `+1` occurs after flooring. [^G12][^G13]

| Modifier | Published value / rule | Evidence |
|---|---|---|
| Same-type attack bonus (STAB) | **1.2** when the move matches an attacker type; otherwise **1** | Community mechanics explanation [^G14]. |
| Type matchups | **1.6** super effective; **0.625** resisted; **0.390625** for a main-series immunity; neutral **1** | Original community analysis of the effectiveness change [^G15]. |
| Dual defender types | Multiply the two factors; a double weakness gives **2.56**, derived | Same type-system analysis [^G15]. |
| Weather | Matching attack types receive a reported **20%** boost, conventionally **1.2** in the model | Original community weather analysis; exact placement/rounding was explicitly uncertain [^G16]. |

Weather can affect both sides. Special bonuses and mechanics—including Mega/Primal, Shadow, friendship and raid-specific effects—need their own eligibility and stacking rules. The current calculator explicitly omits some special mechanics; the compact equation above is therefore not a claim of complete parity. [^G5][^G13][^G17]

#### Dodge, defender AI and changed timing

Historical controlled gym tests found a successful dodge reduced damage by about **75%**, with integer rounding and a minimum hit of **1**. A community simulator documents a defender approximation of a **2-second pause** and a **50% charged-move choice** when energy permits. These are historical/model parameters, **UNVERIFIED as exact current Gym AI rules**. The defender's owner does not choose live attacks during another player's challenge. [^G12][^G18]

The official battle-system update confirms changes to **damage, energy generation and attack durations** in Gyms/Raids. Original reporting on the **December 2024 raid dodge change** describes a changed input window and removal of stacked dodges. Raid observations do not establish identical Gym behavior. A legacy dodge-window constant or raid timing quantum must not be presented as a verified 2026 Gym rule. [^G19][^G20]

### 4. Defender rewards, badges and Photo Discs

| System | Current published rule / limitation | Evidence |
|---|---|---|
| Defender coins | Community reference: **1 PokéCoin per 10 minutes** defended. Official daily maximum: **50 per Trainer**, combined across gyms. | [^G21][^G22]. |
| Payment timing | Coins arrive only when the Pokémon returns. Multiple days held do not accumulate multiple daily caps; the return day's cap applies. **8 h 20 min** yields 50 at the stated rate, derived, provided that day's allowance remains. | Official payout/cap rule [^G22]; rate [^G21]. |
| Gym badges | **Basic, Bronze, Silver, Gold**; gym activity such as battling, defending and feeding advances the badge. Higher tiers improve Photo Disc rewards. | Official badge help [^G23]. |
| Photo Disc items | Gym spins provide items such as Poké Balls and Potions. Exact current distributions and badge thresholds are **UNVERIFIED** in this research. | Official gym help [^G2]; badge effects [^G23]. |

These are GO's rewards for physical-location defense. They do not establish suitable chat-activity rewards or a bot currency exchange rate.

### 5. Raids: feature boundary

**Official overview:** a temporary boss occupies a gym. Players use raid passes and cooperate with attacking parties; ordinary raids allow groups of up to **20 Trainers**, each with up to **6 Pokémon**. Listed ordinary difficulty tiers are **1, 3 and 5 stars**. Victory gives rewards and a separate boss-catching opportunity, normally using the awarded Premier Balls. It does not capture the gym for the winning players; the previous defenders resume defending that gym after the raid ends. [^G24]

Special formats include Mega/Mega Legendary, **Super Mega**, Primal, Shadow and Ultra Beast encounters. Their rewards, catch-ball rules and additional mechanics can differ; for example Mega/Primal raids award their respective energy, while some Ultra Beast events use Beast Balls. These are separate systems, not additional ordinary defender slots. This is an overview, not a current boss schedule, access-rule matrix or exhaustive tier list. [^G25]

## Recommendations — adaptation implications

- Preserve canonical CP/IVs/level and track deployment condition separately; do not lower stored CP to model fatigue.
- Select a small, explicit battle ruleset from the community damage model. Version the move data and bot timing rules; exact replication of undocumented current server behavior is unnecessary for this project.
- Keep raids outside v1. [Battle design](battle-system.md) and [server gym design](discord-gym-design.md) define proposed bot rules, rewards and limits independently of GO's observed constants.

## Sources

Each source below was checked **2026-11-04**. Community publications are evidence of their stated observations/models, not official guarantees.

[^G1]: **Official, checked 2026-11-04:** [Changing teams](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1243-how-do-i-change-my-team/).
[^G2]: **Official, checked 2026-11-04:** [Battling at Gyms](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1171-battling-at-gyms/).
[^G3]: **Official historical announcement, checked 2026-11-04:** [2017 gym redesign](https://pokemongo.com/news/raids).
[^G4]: **Official restriction, checked 2026-11-04:** [Legendary Pokémon announcement](https://pokemongo.com/news/legendarypokemon).
[^G5]: **Official, checked 2026-11-04:** [Using Mega-Evolved Pokémon](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1203-using-a-mega-evolved-pokemon/).
[^G6]: **Community reference, checked 2026-11-04:** [GO Hub: Meltan](https://db.pokemongohub.net/pokemon/808).
[^G7]: **Original historical experiment, checked 2026-11-04:** [DrThod's motivation-decay analysis](https://www.reddit.com/r/TheSilphRoad/comments/at26qv/the_motivation_decay_algorithm_used_in_gyms_has/).
[^G8]: **Community model/guide, checked 2026-11-04:** [Pokebattler gym handbook](https://articles.pokebattler.com/professor-willows-handbook-gyms/).
[^G9]: **Original historical experiment, checked 2026-11-04:** [Berries and gym motivation](https://articles.pokebattler.com/2017/07/20/berries-and-gym-motivation/).
[^G10]: **Official, checked 2026-11-04:** [Fast and charged attacks](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1160-fast-attacks-charged-attacks/).
[^G11]: **Original community analysis, checked 2026-11-04:** [Teban54: raid energy and charged-move discussion](https://articles.pokebattler.com/2023/01/02/analysis-fusion-flare-reshiram-and-fusion-bolt-zekrom-as-raid-attackers-which-one-to-raid/).
[^G12]: **Original historical experiment, checked 2026-11-04:** [Testing gym combat misconceptions](https://www.reddit.com/r/TheSilphRoad/comments/52b453/testing_gym_combat_misconceptions_2/).
[^G13]: **Community calculator methodology, checked 2026-11-04:** [GO Hub breakpoint calculator](https://db.pokemongohub.net/tools/breakpoints).
[^G14]: **Community explanation, checked 2026-11-04:** [Damage mechanics](https://pokemongohub.net/post/wiki/damage-mechanics/). Use its STAB/core-formula discussion; its old type-factor examples are superseded by G15.
[^G15]: **Original community analysis, checked 2026-11-04:** [2018 effectiveness changes](https://pokemongohub.net/post/meta/pokemon-go-type-effectiveness-change-december-2018/). Only the summarized mechanics are used; no extracted configuration is reproduced.
[^G16]: **Original community analysis, checked 2026-11-04:** [Pokebattler weather effects](https://articles.pokebattler.com/professor-willows-handbook-weather-effects/).
[^G17]: **Community reference, checked 2026-11-04:** [GO Hub weather guide](https://db.pokemongohub.net/weather).
[^G18]: **Simulator's own methodology, checked 2026-11-04:** [GameInfo calculation FAQ](https://pokemon.gameinfo.io/en/faq).
[^G19]: **Official update, checked 2026-11-04:** [Raid and battle systems update](https://pokemongo.com/news/battle-systems-update).
[^G20]: **Original community reporting, checked 2026-11-04:** [December 2024 raid dodge changes](https://pokemongohub.net/post/news/dodging-in-raids-finally-fixed-heres-how-to-dodge-with-the-new-mechanic/).
[^G21]: **Community reference, checked 2026-11-04:** [Serebii gym guide](https://www.serebii.net/pokemongo/gyms.shtml). Use its current opening section for the coin rate; the page also retains obsolete pre-redesign material.
[^G22]: **Official, checked 2026-11-04:** [Defender bonus](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1172-earning-the-defender-bonus/).
[^G23]: **Official, checked 2026-11-04:** [Gym badges](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1174-collecting-gym-badges/).
[^G24]: **Official, checked 2026-11-04:** [Raid battles](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1175-what-are-raid-battles/).
[^G25]: **Official, checked 2026-11-04:** [Raid types](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/29-what-are-the-different-types-of-raid-battles-1771551891/).
