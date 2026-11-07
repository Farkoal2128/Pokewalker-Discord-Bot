# Shinies and Shiny Lures

Scope: A7 and B4. Checked **2026-11-04**. GO changes over time; encounter eligibility and event bonuses must be versioned. Numbers under Recommendations are bot design settings or explicitly derived illustrations, not GO rules. Owner-selected settings are labeled; other defaults remain proposals.

## Facts

### Pokémon GO: eligibility and evidence quality

- Shiny availability is released selectively. Wild encounters, raids and research can award shinies, but an unreleased shiny is unavailable. The official help page identifies Smeargle, Unown and Meltan as examples requiring particular events for shiny availability. Check the actual species/form and event announcement rather than assuming every asset is obtainable. [Official shiny help](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/2678-what-are-shiny-pokemon/) — checked 2026-11-04.
- **A current-source warning:** the official *Memories in Motion* announcement introduced changes starting March 3, 2026: already-debuted shiny evolved species can appear wild; raids and Eggs have increased shiny chances compared with wild encounters; eligible Rocket encounters expanded, with leaders/Giovanni boosted relative to Grunts. It does **not** publish numeric probabilities. Historical advice that a species always has the same shiny rate across every encounter source is therefore unsafe. [Official announcement](https://pokemongo.com/en/seasons/memories-in-motion) — checked 2026-11-04.
- Exact current server probabilities and the complete species/form/source exception list are **UNVERIFIED**. Community measurements and summaries are useful estimates, not an official universal guarantee. In particular, do not copy a pre-2026 list of permanently boosted wild species into a current GO model. [Community GO shiny reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Pok%C3%A9mon_(GO)) — checked 2026-11-04.

### GO rates: useful estimates, not guaranteed constants

All rows describe **shiny-eligible** Pokémon. Historical samples establish observed rates in their original study periods; they cannot establish every current event's implementation.

| Context | Common estimate | What is actually supported | Source; checked |
|---|---:|---|---|
| Ordinary eligible wild encounter | ~1/512 (~0.195%) | Current community baseline; exact official value **UNVERIFIED**. | [Community reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Pok%C3%A9mon_(GO)); 2026-11-04 |
| Many eligible non-five-star raids and Eggs after the 2026 changes | ~1/64 (~1.56%) | Community estimate; precise current coverage and numeric rate independently **UNVERIFIED**. Official source confirms a boost only. | [Community reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Pok%C3%A9mon_(GO)), [official changes](https://pokemongo.com/en/seasons/memories-in-motion); 2026-11-04 |
| Eligible legendary raid encounter | ~1/20 (5%) | Historical Silph sample: 2,118 shinies / 41,027 encounters, ~1/19.4; exceptions remain possible. | [Silph study II, archived](https://web.archive.org/web/20221001091602/https://thesilphroad.com/science/reflecting-pokemon-go-shiny-rates-ii-raids-eggs-quests/); 2026-11-04 |
| Featured Community Day species | ~1/25 (4%) | Historical Silph aggregate: ~1/24.8. Applies to the specified species and bonus window. | [Silph study I, archived](https://web.archive.org/web/20221205203515/https://thesilphroad.com/science/reflecting-pokemon-go-shiny-rates-boosted-wild-rates/); 2026-11-04 |
| Some boosted wild events | ~1/128 (~0.78%) | Historical “medium event” sample measured ~1/133; no rule that every event boosts odds. | [Silph study I, archived](https://web.archive.org/web/20221205203515/https://thesilphroad.com/science/reflecting-pokemon-go-shiny-rates-boosted-wild-rates/); 2026-11-04 |
| Many special Raid Day events | ~1/10 (10%) | Historical special-raid sample measured ~1/10.5, with an explicitly excluded early exception. | [Silph study II, archived](https://web.archive.org/web/20221001091602/https://thesilphroad.com/science/reflecting-pokemon-go-shiny-rates-ii-raids-eggs-quests/); 2026-11-04 |

### Lures, charms and events are different mechanisms

- GO Lure Modules attract Pokémon to a PokéStop, normally for **30 minutes**, benefiting nearby trainers. Their standard official description provides no shiny-probability multiplier. More encounters can increase the chance of seeing a shiny even when the per-encounter probability is unchanged. A universal GO lure shiny boost is **UNVERIFIED**; read each event's stated bonuses separately. [Official Lure Modules help](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/1789-lure-modules/) — checked 2026-11-04.
- A GO equivalent of the main-series **Shiny Charm**, or a universal shiny bonus for a daily catch streak, was **not confirmed** in the checked official material: treat both as **UNVERIFIED**, not dependencies for this bot. The checked season announcement describes catch-streak XP/Stardust rewards and separately describes shiny-source changes. The proposed **Shiny Lure is a custom bot item**. [Official season announcement](https://pokemongo.com/en/seasons/memories-in-motion), [official shiny help](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/2678-what-are-shiny-pokemon/) — checked 2026-11-04.

### Main-series comparison

| Games | Ordinary base probability | Qualification | Source; checked |
|---|---:|---|---|
| Generations II–V | 1/8,192 (~0.0122%) | Standard baseline, excluding special methods, guaranteed encounters and restrictions. | [Shiny mechanics reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Pok%C3%A9mon); 2026-11-04 |
| Generation VI onward | 1/4,096 (~0.0244%) | Standard baseline; game-specific methods and some encounter categories differ. | [Shiny mechanics reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Pok%C3%A9mon); 2026-11-04 |

- In Gold/Silver/Crystal, shininess depends on DVs: Defense, Speed and Special must each be **10**, and Attack one of **2, 3, 6, 7, 10, 11, 14, 15**. Breeding inheritance changes the odds. Do not copy that correlation into GO-style IVs. HGSS uses the later shiny system. [Shiny mechanics reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Pok%C3%A9mon) — checked 2026-11-04.
- Shiny Charm debuted in **Black 2/White 2**. Its usual effect is **two additional shiny attempts**, approximately tripling eligible odds: about **1/2,731** in B2W2 and **1/1,366** with the later baseline. This is method-dependent: for example, BDSP's Charm affects breeding only, and Legends: Arceus uses a different roll bonus. Ordinary NPC gifts/trades are generally unaffected. [Shiny Charm reference](https://bulbapedia.bulbagarden.net/wiki/Shiny_Charm) — checked 2026-11-04.
- In **Let's Go Pikachu/Eevee**, Lure/Super Lure/Max Lure add **one shiny attempt**: approximately **1/2,048** with a lure alone or **1/1,024** with Charm plus lure and no combo bonus. Catch combos add another game-specific boost; gifts/Alolan trades are unaffected. These are not GO Lure Module mechanics. [Serebii Let's Go shiny guide](https://www.serebii.net/letsgopikachueevee/shinypokemon.shtml) — checked 2026-11-04.

## Recommendations

### Baseline and pacing

**Owner-selected pacing, 2026-11-04: 3 eligible generated encounters per active hour.** Use this hourly target for balance calculations. Encounters remain step-triggered and subject to anti-spam rules, queue capacity and species/form eligibility; the target is not an observed rate or a guarantee of encounters while idle. The exact definition of active time and the supporting step cadence still need implementation design.

Keep the proposed shiny probability at **1/256 per eligible generated encounter** (**0.390625%**). [Task 1's older step-budget proposal](../pokewalker/adaptation.md) needs reconciliation with the hourly target; see Open decisions below. Calendar-day estimates must state how many hours the player is active.

Shininess gives no CP, IV, catch-candy or research-reward bonus; the [catch flow](items-and-catching.md) provides shiny-specific flee protection. Keep shiny RNG independent of IVs and the catch-success roll. Evolution preserves shiny status. Explicitly maintain `shiny_enabled` per supported form; an available sprite alone must not enable an encounter.

For independent encounters with constant probability `p`:

- Chance of at least one shiny in `n` encounters: `1 - (1 - p)^n`.
- Expected encounters to first shiny: `1 / p`; an expectation is not a guarantee or pity threshold.
- At `p = 1/256`, the median is **178 encounters** and reaching **95%** cumulative probability takes **766 encounters**. These are **derived**, assuming every encounter is eligible.

At **3 eligible encounters per active hour**, the derived mean is **85.3 active hours**, the median encounter count corresponds to **59.3 active hours**, and the 95% threshold to **255.3 active hours**. These convert encounter counts into time at the selected rate; encounter timing and successful captures can change the experienced wait.

**Derived calendar illustrations**, without lures and before catch failures, assuming the target is sustained for the stated daily activity:

| Active hours/day | Eligible generated encounters/day | Mean days to a shiny encounter | Chance of at least one in 30 days |
|---:|---:|---:|---:|
| 1 | 3 | 85.3 | 29.7% |
| 2 | 6 | 42.7 | 50.6% |
| 4 | 12 | 21.3 | 75.6% |

Measure eligible generated encounters per active hour, queue saturation and successful shiny catches. If the selected wait is too long, evaluate **1/128**; at 3/hour its derived mean is **42.7 active hours**. For a target mean wait of `T` active hours at `r` eligible encounters/hour, the balancing relation is `p = 1/(r*T)`. Tune reward pacing through explicit balance settings while retaining anti-spam protections. Do not add streak pity or permanent Charm progression in v1.

### Shiny Lure contract

| Property | Proposed v1 behavior |
|---|---|
| Stored item | Rare item; maximum **1 held** per player. No expiry or countdown while unused. |
| Activation | Explicit `/walker` inventory button; atomic consume-and-activate transaction. |
| Duration | **1 real hour** from successful activation, saved as absolute UTC timestamps. Offline time counts. |
| Effect | Multiply the probability by **4**: baseline `1/256` becomes `1/64` (**1.5625%**). This is a probability multiplier, not four independent rerolls. |
| Eligibility | Only encounters generated in `[starts_at, expires_at)`; not existing queued encounters. |
| Stacking | At most one active effect. Reject another activation while active without consuming the held item. No extension, paused timer or additive duration. |
| Active plus stored | Activation consumes the item; a later find may fill the empty inventory slot while the effect is active. **One held plus one active** is permitted. |
| Duplicates | Apply the shared rare-item conversion policy in [items-and-catching.md](items-and-catching.md); no hidden second inventory unit. |
| Scope | Player-wide if progression is global. Multiple guilds must not multiply activations or reapply the effect. |

Do not add an encounter-frequency boost to this item. Its chance of producing any shiny remains dependent on eligible encounters generated during the hour:

| Eligible encounters generated during the hour | Baseline chance of at least one | With Shiny Lure |
|---:|---:|---:|
| 1 | 0.39% | 1.56% |
| 2 | 0.78% | 3.10% |
| 3 — hourly target | 1.17% | 4.61% |

These percentages are **derived** from the formula above, not measured outcomes. At the selected pace, a full active hour corresponds to **3 eligible rolls** and a **4.61%** chance of at least one shiny with the lure. Fewer qualifying encounters reduce that chance; the one-hour effect still expires in real time, including idle/offline time. Avoid promising a shiny or encouraging spam to exploit the hour.

For future events, give each encounter one selected base rate, then apply at most one lure multiplier. Make event/lure compatibility explicit in configuration; no implicit multiplication of every active bonus. Proposed safety cap: `p <= 1/16`, unless an explicitly guaranteed reward is separately modeled. This cap is a design choice, not GO behavior.

### Queue, persistence and UX invariants

1. At encounter creation, atomically save species/form, shiny result, effective probability, generation time, rate/configuration version and applied effect ID. Use secure random draws and a unique triggering-event key. Retries return the saved result.
2. Resolve the saved encounter through `/walker`. Opening, timing out, reconnecting, switching guild or changing a ball never rerolls shininess. Catching after the lure expires retains the result; activating a lure before resolving an old queue gives no retroactive benefit.
3. Respect the bounded encounter queue. At capacity, do not pre-roll hidden candidates for later selection; apply the shared overflow policy and count suppressed generation separately from encounters.
4. Use authoritative server timestamps and atomic activation. The exact expiry instant is excluded. Restarts retain the original deadline; duplicate button interactions cannot consume twice or restart an effect.
5. Show the shiny icon, accessible text and alternate artwork when resolving an encounter. Inventory shows held quantity and active countdown/expiry independently. With both present, label the held item **“Stored — available after the current effect expires”** and disable activation. Activation text explains **“4× shiny odds for encounters generated during the next hour; existing queued encounters are unchanged.”**
6. Protect shinies from bulk research transfer by default; use the safeguards in [candy-transfer-evolution.md](candy-transfer-evolution.md). Retain the audited encounter result and transaction metadata described in [storage-and-data-model.md](storage-and-data-model.md).

### Open decisions

- Reconcile the step cadence and earning budgets with the owner-selected **3 eligible encounters per active hour**. The older **1,000 awarded steps/day ÷ 100 steps/encounter = 10 encounters/day** supports only **3 hours 20 minutes/day** at that rate, before queue suppression or ineligible forms. Treat those older encounter-pacing defaults as pending revision, not as a second daily encounter limit. Item-find budgets are separate and require their own supply check.
- Define active-time measurement and validate the observed hourly pace. Choose an acceptable median shiny wait before finalizing `1/256`; evaluate `1/128` against that target.
- Resolve global versus server-local progression across research tasks before implementation. Keep rare-item caps, active effects, queues and earning limits consistent with that ownership decision; this file's proposed pacing assumes one shared player budget.
- Confirm the proposed [catch policy](items-and-catching.md): 0% shiny flee, 10% ordinary flee after failure, and repeat attempts after nonterminal failures. These choices affect acquisition pace and are bot recommendations, not GO facts.

