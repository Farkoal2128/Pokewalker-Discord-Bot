# CP, IVs and leveling

Scope: A1–A4 and B1. Checked **2026-11-04**. See [README](README.md) for the project-wide decisions and [resource economy](candy-transfer-evolution.md) for rewards.

## Facts

**Evidence labels:** **Official** means the Pokémon GO publisher/help center documents the rule. **Community** means a published mechanics explanation, study or calculator supports it; it is not an official server specification. **UNVERIFIED** marks an unresolved detail. Dates below are access/check dates, not claims that the game was tested directly.

### 1. Combat Power

**Community — standard CP formula:** for GO base stats `A, D, S`, individual values `a, d, s`, and level multiplier `m = CPM(L)`:

$$
CP=\max\left(10,\left\lfloor\frac{(A+a)\sqrt{D+d}\sqrt{S+s}\,m^2}{10}\right\rfloor\right).
$$

The minimum displayed CP is **10**. Calculate with the unrounded inputs, then floor the final result. Combat Attack and Defense are `(A+a)×m` and `(D+d)×m`; ordinary maximum HP is `max(10, floor((S+s)×m))`. Do **not** substitute already-rounded HP into the CP equation. Shedinja has a special HP rule. CP alone does not encode moves or type matchups. Source: [GO Hub CP/stat calculator documentation](https://db.pokemongohub.net/tools/cp-calculator), checked **2026-11-04**.

### 2. Converting main-series base stats

**Community — ordinary, unadjusted forms:** let `AH/AL` be the higher/lower of main-series Attack and Special Attack; `DH/DL` the higher/lower of Defense and Special Defense; `V` Speed; and `H` HP. The commonly documented conversion is:

$$
q=1+\frac{V-75}{500}
$$
$$
A=\operatorname{round}\left(\operatorname{round}\left(2\frac{7AH+AL}{8}\right)q\right)
$$
$$
D=\operatorname{round}\left(\operatorname{round}\left(2\frac{5DH+3DL}{8}\right)q\right),\qquad
S=\left\lfloor1.75H+50\right\rfloor.
$$

Thus physical/special stats are blended and Speed scales Attack/Defense. Rounding the inner Attack/Defense expression before applying Speed matters. Sources: [Cave of Dragonflies](https://www.dragonflycave.com/pokemon-go/stats/) and [GO Hub stat-conversion research](https://pokemongohub.net/post/featured/pokemon-go-calculates-stats-max-cp/), checked **2026-11-04**.

**Community exceptions / UNVERIFIED universal conversion:** high-CP species have historically received a **9%** base-stat reduction; selected exceptional forms use other adjustments. Community references disagree over `>4000` versus `≥4000` for the unadjusted level-40 threshold, the placement of rounding, and floor versus round for Stamina. Bulbapedia also documents separate Mega/Primal exceptions. Consequently, these equations are **not a confirmed exact generator for every current species/form**. Exact tie rounding, adjustment order and the complete current exception set remain **UNVERIFIED** here. Sources: [GO Hub conversion](https://pokemongohub.net/post/featured/pokemon-go-calculates-stats-max-cp/) and [Bulbapedia: Stat (GO)](https://bulbapedia.bulbagarden.net/wiki/Stat_(GO)), checked **2026-11-04**.

**Official API boundary:** PokéAPI supplies main-series base stats and species/form/evolution information. Its documented resources do not supply GO's base-stat overrides, CPM table or power-up pricing. Main-series stat values cannot be passed directly into the GO CP formula. Source: [PokéAPI v2 documentation](https://pokeapi.co/docs/v2), checked **2026-11-04**.

### 3. CP multipliers and half levels

**Community:** each Pokémon level has a multiplier; a power-up advances **0.5 level**. The [complete published CPM reference](https://pokemongohub.net/post/article/pokemon-go-cpm-list/) lists whole and half levels through 51. Selected checkpoints below are transcribed from that reference, checked **2026-11-04**; this document intentionally links the full table rather than republishing a game-data dump.

| Pokémon level | Published CPM |
|---:|---:|
| 1 | 0.094 |
| 1.5 | 0.1351374318 |
| 2 | 0.16639787 |
| 10 | 0.4225 |
| 15 | 0.51739395 |
| 20 | 0.5974 |
| 20.5 | 0.6048236651 |
| 30 | 0.7317 |
| 30.5 | 0.7347410093 |
| 40 | 0.7903 |
| 40.5 | 0.792803968 |
| 50 | 0.84029999 |
| 51 | 0.84529999 |

**UNVERIFIED — exact live precision:** community tables differ slightly at some half levels and in retained decimal precision. The values above are published reference values, not a publisher-guaranteed binary representation. Do not assume linear interpolation, or one interpolation formula across every band, reproduces GO exactly. The older [Cave of Dragonflies table](https://www.dragonflycave.com/pokemon-go/stats/) and [GO Hub table](https://pokemongohub.net/post/article/pokemon-go-cpm-list/) show why a versioned choice is necessary; checked **2026-11-04**.

### 4. IVs and appraisal

**Community:** GO has three IVs, Attack/Defense/Stamina, each an integer **0–15**. A large wild-catch study supports independently uniform rolls for ordinary wild Pokémon; the live random-number implementation is unpublished. A floor restricts each stat's range. These are default source rules, with event/special-encounter exceptions. Sources: [wild IV distribution study](https://pokemongohub.net/post/featured/researching-iv-mechanics-distribution-pokemon-go/) and [current IV guide](https://pokemongohub.net/post/featured/pokemon-go-iv-guide-explained/), checked **2026-11-04**.

| Source | Default IV range for each stat | Perfect-IV probability under uniform rolls |
|---|---:|---:|
| Ordinary wild | 0–15 | 1/4096 |
| Weather-boosted wild | 4–15 | 1/1728 |
| Eggs, ordinary raids, most research | 10–15 | 1/216 |
| Lucky trade | 12–15 | 1/64 |

Other **community defaults**: ordinary GO Battle League rewards use a **10** floor; Shadow Raids use **6** (giving a derived perfect-IV chance of **1/1000**). Normal trades reroll IVs with floors **1/2/3/5** at Good/Great/Ultra/Best friendship. Special events can override floors; the newer Forever Friends tier's floor is **UNVERIFIED** here. Sources: [GO Hub IV-floor calculator](https://db.pokemongohub.net/tools/hundo-odds), [original Shadow Raid coverage](https://leekduck.com/events/rising-shadows-shadow-raid-debut/) and [trade reroll reference](https://bulbapedia.bulbagarden.net/wiki/Trade_(GO)#IV_reroll), checked **2026-11-04**.

**Community appraisal mapping:** sum the three IVs: `0–22 → 0★`, `23–29 → 1★`, `30–36 → 2★`, `37–44 → 3★`, `45 → perfect/4* search category`. The perfect appraisal uses a red seal rather than four drawn stars. Bars show individual stat quality. Source: [IV/appraisal guide](https://pokemongohub.net/post/featured/pokemon-go-iv-guide-explained/), checked **2026-11-04**.

**Official:** evolution and power-ups do not improve appraisal; purification can. IV quality is therefore distinct from Pokémon level. **Do not describe IVs as permanently immutable:** Hyper Training now provides a way to increase these stats, using Bottle Caps and tasks; trading can also change IVs. Sources: [official appraisal help](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1120-appraising-your-pokemon/), [official Hyper Training help](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1113-what-is-hyper-training/) and [community trade-IV guide](https://pokemongohub.net/post/featured/pokemon-go-iv-guide-explained/), checked **2026-11-04**.

### 5. Pokémon level versus Trainer level

**Official:** the Trainer cap changed from **50 to 80 on October 15, 2025**; the publisher explicitly says that change affects Trainer level, not Pokémon. Power-up eligibility is still limited by Trainer progression. Sources: [level-update details](https://pokemongo.com/news/pgo-leveling-update-details-2025) and [official power-up help](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1121-powering-up-pokemon/), checked **2026-11-04**.

**Community:** the ordinary paid Pokémon-level range remains **1–50**, in half-level increments after power-ups. An active Best Buddy normally adds **one effective level**, making a paid level-50 Pokémon effectively 51 while boosted. Special forms/events require separate handling. Source: [Bulbapedia: Power Up](https://bulbapedia.bulbagarden.net/wiki/Power_Up), checked **2026-11-04**.

**Community default acquisition levels:** the source below documents these encounter defaults; they are not exhaustive of unusual research, event or trade encounters. Sources: [Power Up: initial level](https://bulbapedia.bulbagarden.net/wiki/Power_Up#Initial_level) and [GameInfo weather guide](https://pokemon.gameinfo.io/en/guides/weather-boost), checked **2026-11-04**.

| Source | Published ordinary level rule |
|---|---|
| Wild | Whole levels from 1; ordinary upper ceiling 30, with a lower-Trainer limitation |
| Weather-boosted wild | Weather adds 5 levels to the eligible wild range; ordinary ceiling 35 |
| Egg | Normally 20 at sufficiently high Trainer progression; lower-Trainer limitation |
| Standard research reward | 15 |
| Ordinary raid reward | 20, or 25 with matching weather |
| Ordinary Rocket rescue | 8, or 13 with matching weather |

**UNVERIFIED after Trainer reindexing:** older/community rules express the wild ceiling as `min(TrainerLevel,30)`, hatch level as `min(TrainerLevel,20)`, and power-up cap as `min(TrainerLevel+10,50)`. The official 2025 update does not publish the exact replacement mapping, and current guides repeat or contradict older numeric unlocks. This research does **not** confirm that those expressions still use today's displayed Trainer level. Preserve them as historical/community context, not a current implementation contract. Sources: [official reindexing announcement](https://pokemongo.com/news/pgo-leveling-update-details-2025), [community level rules](https://bulbapedia.bulbagarden.net/wiki/Power_Up), checked **2026-11-04**.

### 6. Power-up costs

**Community — standard, non-discounted Pokémon:** each row gives the cost of **one +0.5 power-up from the current level**, including both listed endpoints. Candy XL replaces ordinary Candy from the **40 → 40.5** step. Do not shift these bands by one level. Sources: [GO Hub normal-cost guide](https://pokemongohub.net/post/guide/guide-to-power-up-costs-in-pokemon-go/) and [PokeTools explicit starting-level table](https://www.poketools.com/pokemon-go-power-up-calculator), checked **2026-11-04**.

| Current level before power-up | Stardust | Candy | Candy XL |
|---|---:|---:|---:|
| 1–2.5 | 200 | 1 | — |
| 3–4.5 | 400 | 1 | — |
| 5–6.5 | 600 | 1 | — |
| 7–8.5 | 800 | 1 | — |
| 9–10.5 | 1,000 | 1 | — |
| 11–12.5 | 1,300 | 2 | — |
| 13–14.5 | 1,600 | 2 | — |
| 15–16.5 | 1,900 | 2 | — |
| 17–18.5 | 2,200 | 2 | — |
| 19–20.5 | 2,500 | 2 | — |
| 21–22.5 | 3,000 | 3 | — |
| 23–24.5 | 3,500 | 3 | — |
| 25–25.5 | 4,000 | 3 | — |
| 26–26.5 | 4,000 | 4 | — |
| 27–28.5 | 4,500 | 4 | — |
| 29–30.5 | 5,000 | 4 | — |
| 31–32.5 | 6,000 | 6 | — |
| 33–34.5 | 7,000 | 8 | — |
| 35–36.5 | 8,000 | 10 | — |
| 37–38.5 | 9,000 | 12 | — |
| 39–39.5 | 10,000 | 15 | — |
| 40–40.5 | 10,000 | — | 10 |
| 41–41.5 | 11,000 | — | 10 |
| 42–42.5 | 11,000 | — | 12 |
| 43–43.5 | 12,000 | — | 12 |
| 44–44.5 | 12,000 | — | 15 |
| 45–45.5 | 13,000 | — | 15 |
| 46–46.5 | 13,000 | — | 17 |
| 47–47.5 | 14,000 | — | 17 |
| 48–48.5 | 14,000 | — | 20 |
| 49–49.5 | 15,000 | — | 20 |

**Community:** standard **40 → 50 costs 250,000 Stardust + 296 Candy XL**. Lucky Pokémon halve Dust, not Candy; Shadow Pokémon cost more and purified Pokémon less. These and species-specific exceptions such as Eternatus require separate pricing, so the table is not universal. Sources: [GO Hub power-up calculator](https://db.pokemongohub.net/tools/power-up-calculator) and [Bulbapedia exceptions](https://bulbapedia.bulbagarden.net/wiki/Power_Up), checked **2026-11-04**.

**Official:** Candy XL collection begins at **Trainer level 31**. See [resource sources and yields](candy-transfer-evolution.md) for Candy, Stardust and XL acquisition. Source: [official power-up help](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1121-powering-up-pokemon/), checked **2026-11-04**.

## Recommendations — proposed bot rules, not GO facts

### V1 CP contract

- **Use the standard CP equation**, keep the three IVs, retain a hidden power-up level, and show players CP plus an optional `/walker` details view with IVs and level. CP remains the main progression display.
- **Skip a Trainer-level/XP system for v1.** Independently sample catch level uniformly from the integers **1–20**, and each IV uniformly from **0–15**. These are bot defaults. Freeze all rolls when the encounter is queued, so reopening it, switching servers or later gaining resources cannot reroll it.
- Power up in **+0.5** steps to **40**. Represent level as integer `level_x2` **2–80**; display half its value. Calculate CP from canonical inputs; never increment a cached CP by an estimated amount.
- Keep **family Candy + universal Stardust**, omit XL. Candy makes repeated species useful; Dust lets activity with other species support a favorite. Do not add weather, Shadow/purified/Lucky modifiers, trading, Hyper Training or Buddy level boosts in v1.
- Version the CP formula, CPM table and species/form base-stat records. Select one published multiplier reference, including every half level, and freeze the chosen values rather than interpolating at runtime. Confirm reference CP examples before implementation is accepted.
- Start with a supported species/form set. Use the documented conversion for ordinary forms, with independently checked GO-stat overrides where needed. Record the source and date per override. If a form has unresolved stats, disable it or explicitly label its stats as the bot's approximation; never silently call them exact GO values.

### Proposed bot power-up prices

These **starting values require economy testing**; they deliberately differ from GO. Charge once per half-level, using the level **before** the upgrade. Bounds below are lower-inclusive, upper-exclusive.

| Current bot level | Family Candy | Stardust |
|---|---:|---:|
| `[1,10)` | 1 | 100 |
| `[10,20)` | 2 | 250 |
| `[20,30)` | 3 | 500 |
| `[30,40)` | 4 | 1,000 |

Quote the next level, resulting CP and both costs before confirmation; debit currencies and update the instance atomically. For multiple upgrades, sum the price of every crossed half-step. Reject cap violations and duplicate submissions. Evaluate affordability against the encounter/drop pacing in the other research files before treating these values as balanced.

### Inputs to reserve for future gyms

Expose stable species/form identity, GO-style base stats, IVs, level, calculated Attack/Defense/HP, types and a mechanics-version identifier. CP is a useful displayed summary, but later gym combat should consume the underlying stats and an independently designed move/type system. Do not infer combat damage or win probability from CP alone.

If a later Trainer/research rank is desired, award progress for **capped eligible activity**, distinct-species discoveries and research milestones. Decide its catch-level and power-up unlock schedule separately; do not import GO's unresolved post-2025 Trainer mapping or reward uncapped message counts.

### Open decisions / implementation blockers

- Choose the permitted GO-stat/CPM reference and document its licensing/provenance before importing a maintained dataset.
- Confirm or deliberately approximate conversion exceptions and decimal precision; these are **UNVERIFIED** above, not instructions to guess.
- Validate the proposed price schedule against expected encounters per active day and the desired time to improve a favorite.
- Decide whether low-level catches should have compensating utility; the uniform **1–20** distribution is a simple starting proposal, not a GO rule or a proven balance result.
