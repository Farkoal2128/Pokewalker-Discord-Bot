# Pokémon GO progression research

**Checked: 2026-11-04.** Task 2 research and proposed v1 settings; implementation and feature approval remain separate. Gym coverage is limited to required inputs.

## Facts — key findings and numbers

- **CP:** GO base stats + **0–15 IVs** + level multiplier; minimum **10 CP**. Main-series stats need conversion. [Community CP reference](https://db.pokemongohub.net/tools/cp-calculator), checked 2026-11-04.
- **Levels:** Trainer cap became **80** on October 15, 2025; Pokémon caps did not rise. Current Trainer-to-Pokémon mapping is **UNVERIFIED**. [Official update](https://pokemongo.com/news/pgo-leveling-update-details-2025), checked 2026-11-04.
- **Resources:** ordinary catch Candy **3/5/10**, transfer **1**; Candy XL unlock **31**. [Community yields](https://bulbapedia.bulbagarden.net/wiki/Candy_(GO)), [official XL rule](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1121-powering-up-pokemon/), checked 2026-11-04.
- **Shinies:** March 2026 changes distinguish raid/Egg odds from wild odds; no official universal numeric rate is confirmed. [Official changes](https://pokemongo.com/en/seasons/memories-in-motion), checked 2026-11-04.
- **PokéAPI:** supplies main-series data; its `capture_rate` is not GO BCR. [API documentation](https://pokeapi.co/docs/v2), checked 2026-11-04.
- **Storage:** level rewards can exceed shop caps; current universal maxima are **UNVERIFIED**. [Official storage update](https://pokemongo.com/news/pgo-leveling-update-details-2025), checked 2026-11-04.

## Recommendations — proposed v1 scope

The encounter-pacing target is **owner-selected (2026-11-04)**; the other numbers are **design defaults**, subject to playtesting.

| System | Starting recommendation |
|---|---|
| CP / levels | GO-style CP; catch level uniformly **1–20**; power up by **0.5** to **40**; no Trainer XP or XL |
| Resources | Family Candy + universal Stardust; catches **3/5/10 Candy + 100/300/500 dust** |
| Research-send | **1 Candy, no dust**; exact-selection preview/confirm; mandatory bulk shiny exclusion; favorite/lock/assignment protections |
| Encounter pace | **3 eligible generated encounters per active hour**, selected by the owner; calibrate step cadence/budgets to support it |
| Shiny | **1/256** per eligible generated encounter; tune to observed pace |
| Shiny Lure | **4×** probability → **1/64**, **1 real hour** from activation; unused item does not expire; no stacking |
| Rare inventory | Master Ball and Shiny Lure: **max 1 held each**; duplicates become **500 dust** |
| Walking finds | **1 per 100 awarded steps**, at most **10/day globally**; each also gives **20 dust**; detailed weights total **10,000** |
| Catching | Ball/berry buttons; ordinary GO-model exponent formula; no timing skill; proposed flee **10% after failure, 0% for shinies** |
| Storage | **100 Pokémon / 250 ordinary item units**; separate rare pockets; dust-funded **+50** expansions |
| Scope / persistence | Global player collection, server-specific gyms; freeze encounter rolls at generation; atomic spending/rewards; durable state behind ephemeral UI |

Defer trading, Trainer XP, buddy Candy, weather/Shadow/Lucky modifiers, Hyper Training, healing and encounter-frequency boosters. Enable only verified species/forms and achievable evolution recipes. No assets or game-data dumps are included.

## Read only the file needed

| File | Coverage |
|---|---|
| [cp-ivs-leveling.md](cp-ivs-leveling.md) | A1–A4, B1: CP/stat formulas, CPM reference, IV sources, levels, full standard power-up cost bands |
| [candy-transfer-evolution.md](candy-transfer-evolution.md) | A5–A6, B2–B3: resources, research-send UX, evolution recipes and conditions |
| [shinies-and-lures.md](shinies-and-lures.md) | A7, B4: GO/main-series comparison, evidence quality, encounter-pace math, lure lifecycle |
| [items-and-catching.md](items-and-catching.md) | A8–A9, B5–B6: item catalog, catch formula, drop weights, rare duplicates, catch transactions |
| [storage-and-data-model.md](storage-and-data-model.md) | A10, B7–B8: dated storage facts, capacities, entities and invariants |

## Open decisions before implementation

At the owner-selected **3 eligible encounters/hour** and proposed **1/256** shiny odds, the mean wait is **85.3 active hours**, with a **59.3-active-hour** equivalent median (derived). Calendar waits depend on daily active time; see [pacing calculations](shinies-and-lures.md). Reconcile [task 1's older 1,000-step/day budget and 100-step encounter cadence](../pokewalker/adaptation.md), which allow only 10 encounters/day and cannot sustain the target beyond 3 hours 20 minutes/day. Check ball/resource supply separately; the proposed 10 daily item finds are not an encounter limit.

Resolve task 1's server-local profiles versus global ownership and later 300-step dowsing versus passive 100-step item finds; never run both item budgets. Confirm launch species/forms, stat/CPM provenance, approximation policy and resource prices before writing requirements/contracts. Gym combat and rewards remain separate research.

