# Items and catching

Scope: A8–A9 and B5–B6. Research checked **2026-11-04**. Start with [README](README.md).

## Facts — Pokémon GO

Each source label below links to a source checked **2026-11-04**. **Official** means publisher/support documentation; **community** means published observation or analysis, not a guaranteed server specification. Durations are ordinary defaults; an announced event can override them.

### Item catalog

| Item | Effect | Duration / consumption | Evidence |
|---|---|---|---|
| Poké Ball / Great Ball / Ultra Ball | Catch attempt; community catch-model multipliers **1 / 1.5 / 2** | One throw | [I2], [I7] |
| Master Ball | Guaranteed capture in supported encounters | One use; no catch-probability roll | Official [I3] |
| Razz Berry | Easier capture; community multiplier **1.5** | Berried catch attempt, not a timed buff | [I2], [I7] |
| Golden Razz Berry | Stronger capture aid; community multiplier **2.5**; can restore a gym defender's motivation | Berried catch attempt / one feeding | [I8] |
| Nanab Berry | Calms movement/attacks, making a throw easier; no ordinary catch-model multiplier | Encounter berry effect | Official [I2]; model [I7] |
| Pinap Berry | **2×** catch Candy | If the berried catch attempt succeeds | Official [I2] |
| Silver Pinap Berry | Capture aid plus extra Candy; community values **1.8×** catch modifier and approximately **2.33×** Candy | Berried catch attempt | [I8]; precision caveat below |
| Potion / Super Potion / Hyper Potion / Max Potion | Restore **20 / 50 / 200 / all HP**, respectively; cannot revive a fainted Pokémon | Immediate, one use | Community item observations [I9]; healing rules official [I6] |
| Revive / Max Revive | Revive with **half / all HP** | Immediate, one use | Official [I1], [I6] |
| Standard Lure Module | Attracts Pokémon to a PokéStop for nearby players | **30 minutes** | Official [I5] |
| Glacial / Mossy / Magnetic / Rainy Lure | Attract selected cold-loving / leafy-habitat / magnetic / rain-loving species; also enable certain evolutions | Normally **30 minutes** | Official [I5] |
| Golden Lure | Makes a Golden PokéStop, with coin-related rewards and occasional Gimmighoul encounters; **one held at a time** | Normally **30 minutes**; one module | Official [I5] |
| Incense | Attracts Pokémon personally; works better while moving | Normally **60 minutes**; repeated uses extend duration, up to **24 hours** | Official [I4] |
| Daily Adventure Incense | Personal encounters while moving; a daily grant, only **one** held | **15 minutes** | Official [I4] |
| Lucky Egg | **2× XP** | Normally **30 minutes**; duration can stack | Official [I1] |
| Star Piece | **1.5× Stardust** | Normally **30 minutes**; duration can stack | Official [I1] |
| Rare Candy / Rare Candy XL | Convert into a chosen Pokémon family's Candy / Candy XL | Immediate, one resource per item | Official [I1]; see [economy](candy-transfer-evolution.md) |
| Sun Stone, King's Rock, Metal Coat, Dragon Scale, Upgrade, Sinnoh Stone, Unova Stone | Required by particular evolution recipes in addition to Candy | Consumed by the evolution; no timed effect | Official item categories [I1]; recipes in [evolution](candy-transfer-evolution.md) |
| Gimmighoul Coins | Special evolution resource, distinct from ordinary evolution stones | Spent on the applicable evolution | Official [I1]; see [evolution](candy-transfer-evolution.md) |

This covers the requested progression items, not every raid, Max Battle, event or cosmetic item. There is no documented Golden Nanab counterpart in the checked catalog; do not invent one. The bot's **Shiny Lure** is defined in [shinies-and-lures](shinies-and-lures.md), not inferred from the GO Lure Module name. [I1]

**Silver Pinap caveat:** official catch help still describes double Candy, while the community reference describes approximately 2.33× using extracted configuration. Current numerical behavior, internal precision and event/bonus rounding combinations are independently **UNVERIFIED** here; do not silently pick 2.333 versus 2.334 as an authoritative constant. The bot can define its own exact rule. No extracted configuration is reproduced here. [I2], [I8]

### Catch-probability model

**Community model, not a published official algorithm:** the Grand Unified Catch Theory was tested against observed catches; a university study reports its formula and modifiers. Let `BCR` be the species/encounter's base capture probability and `c = CPM(Pokémon level)`:

$$
q = \frac{BCR}{2c},\qquad
p = 1-(1-q)^{B\,R\,T\,C\,M}.
$$

Here `B` is ball, `R` berry, `T` target-ring throw bonus, `C` curveball, and `M` type-medal bonus. This expression applies with `q` in `[0,1]`; a probability cannot exceed 1. Master Ball is a guaranteed-catch exception. Sources: original catch study [I7], official guarantee [I3]; checked **2026-11-04**.

| Input | Published ordinary model | Evidence / qualification |
|---|---|---|
| Ball `B` | Poké **1**, Great **1.5**, Ultra **2** | [I10]; encounter-specific balls are outside this ordinary inventory model |
| Berry `R` | None/Pinap/Nanab **1**; Razz **1.5**; Silver Pinap **1.8**; Golden Razz **2.5** | [I7], [I8] |
| Curve `C` | Straight **1**, curveball **1.7** | Community model [I10] |
| Ring `T` | Outside ring **1**; successful inside-ring hit uses **2 − r**, with `r` the ring radius divided by its maximum radius | Community explanation [I10] |
| Named throw bands | Nice roughly **1–1.3**, Great **1.3–1.7**, Excellent **1.7–2**; the bonus is continuous, not a fixed value for the word shown | [I13]; exact endpoint inclusivity **UNVERIFIED** |
| Medal `M` | None **1**, Bronze **1.1**, Silver **1.2**, Gold **1.3**, Platinum **1.4**; dual-type target uses the arithmetic mean of both relevant type bonuses | Current community calculator documentation [I13] |

Algebraic clarification: these are exponent modifiers, **not multipliers of final catch probability**. For a dual-type target use `(M1 + M2) / 2`; misplaced parentheses change the result.

**Scope limits:** encounter-specific overrides, critical captures, raid catch assistance, special balls and exceptional species can modify the ordinary model. The exact present server algorithm and complete current species BCR/flee table are **UNVERIFIED**. GO Hub's own database team states that newly hidden catch/flee inputs forced it to publish approximations; its example fallback values are not official species facts. [I11]

### Flee behavior and data boundaries

- Wild encounters can end after a failed catch; official help does not publish an all-species flee formula or probability. Published research treats flee as a separate outcome following breakout. There is **no verified universal GO flee percentage**. [I2], [I7]
- Do not generalize raid/research or shiny-specific guarantees to all wild Pokémon. Their exception tables are **UNVERIFIED** in this scope. A normal failed catch and choosing to leave an encounter are different actions. [I2], [I3]
- PokéAPI's `pokemon-species.capture_rate` is a main-series integer up to **255**, not GO `BCR`. Its documented species/stat/evolution resources do not supply GO catch multipliers or a complete current GO flee table. [I12]

## Recommendations — bot design, not GO facts

**All numbers below are proposed tuning defaults.** They need playtesting against the encounter pace established by the separate step-loop research.

### v1 item scope and walking drops

Include balls, Razz/Pinap/Golden Razz/Silver Pinap, Rare Candy, Star Pieces, supported evolution items, Master Ball and Shiny Lure. Defer Nanab (there is no moving target), healing items (until gyms define persistent damage), Incense/ordinary Lures (until encounter pacing is measured), and Lucky Eggs (no Trainer XP in v1). Do not add unusable items to the drop pool.

Proposed walking rule: **one passive find per 100 awarded steps, at most 10 finds per UTC day per player across all servers**. Count post-filter/post-diminishing-return steps. Each find also grants **20 Stardust**, independently of its item outcome. This replaces [task 1's later 300-step dowsing proposal](../pokewalker/adaptation.md) for the v1 supply loop; do not enable both reward paths. Preserve a sub-threshold remainder across days; discard excess find credit at the daily cap.

**Encounter-pacing update, owner decision 2026-11-04:** use **3 eligible generated encounters per active hour**, as detailed in [shinies-and-lures.md](shinies-and-lures.md). The older 1,000-step/day budget with one encounter per 100 steps needs reconciliation with that target. The **10 item finds/day** above are a separate supply proposal, not an encounter limit. They no longer imply supplies scale with every encounter at the higher pace; validate balls/resources per active hour before implementation.

Exactly one weighted outcome per find; weights total **10,000**. Item packs occupy their individual unit count in the bag.

| Outcome | Quantity | Weight | Chance per find | Inventory class |
|---|---:|---:|---:|---|
| Poké Ball | 5 | 5,000 | 50% | Ordinary |
| Great Ball | 3 | 1,800 | 18% | Ordinary |
| Ultra Ball | 1 | 600 | 6% | Ordinary |
| Razz Berry | 1 | 800 | 8% | Ordinary |
| Pinap Berry | 1 | 800 | 8% | Ordinary |
| Golden Razz Berry | 1 | 150 | 1.5% | Ordinary |
| Silver Pinap Berry | 1 | 100 | 1% | Ordinary |
| Rare Candy | 1 | 200 | 2% | Ordinary, despite its name |
| Star Piece | 1 | 50 | 0.5% | Ordinary |
| Evolution item | 1 | 200 | 2% | Ordinary |
| Stardust bundle | 100 | 240 | 2.4% | Currency, no bag slots |
| Shiny Lure | 1 | 50 | 0.5% | **Rare: max 1 held** |
| Master Ball | 1 | 10 | 0.1% | **Rare: max 1 held** |

Evolution-item outcomes choose uniformly among the **distinct item kinds used by enabled evolution recipes**; if none exist, grant 100 Stardust. Candidate kinds are the seven stones/items listed above. Offer a deterministic **500-Stardust purchase per evolution item** so one missing random drop cannot block a supported evolution. Other drops are not sold in v1.

Give a new player **30 Poké Balls** once. At maximum finds the table yields an expected **31 balls/day** (`10 × (0.50×5 + 0.18×3 + 0.06)`), excluding Master Balls. This is a derived supply estimate, not a promise: measure balls spent per catch and finds per encounter. If players run out, adjust the existing supply budget; do not encourage extra message spam.

### Rare items, duplicates and full bags

- Only **Master Ball and Shiny Lure** are rare in v1. A future evolution voucher could be max-one, but defer it until special evolution conditions exist. Exclude IV-changing items from v1.
- Rare items use separate max-one pockets, outside the ordinary bag cap. A rare find still succeeds with a full normal bag. The cap applies to inventory; an active consumed Shiny Lure effect is not a held item.
- If the selected rare item is already held, grant **500 Stardust** instead. Do not reroll the drop or raise other rare odds. Report the conversion in the next private `/walker` summary, without a public message.
- If an ordinary item pack cannot fit in full, convert that entire find to **10 Stardust**; preserve existing inventory and do not reroll. Show this in the private summary. There is no unbounded overflow mailbox.
- Rare-cap checks, overflow checks, item credit, fallback credit and the find's unique receipt commit together. Concurrent finds cannot grant two rare items or grant both an item and its conversion.
- A Shiny Lure can be replenished while its previous effect is active, but cannot be activated until that effect expires. Duration, restart behavior and no-stacking rules are in [shinies-and-lures](shinies-and-lures.md).

At 10 finds/day, the expected wait is **20 days per Shiny Lure** and **100 days per Master Ball** before duplicate conversion; at 5 finds/day those means double. These are geometric means, not guaranteed drop schedules. Reassess after the private-server pilot.

### Bot item semantics

Use the ordinary ball/berry exponent modifiers above. Define Silver Pinap Candy explicitly as **`floor(7 × base_catch_candy / 3)`**, giving **7 / 11 / 23** for base rewards **3 / 5 / 10**. Pinap gives **2×**; berry types cannot combine. This is the bot's chosen rule, not a claim about GO's internal rounding.

Star Piece grants **1.5×** catch Stardust and walking Stardust for **30 real minutes** after activation; floor each final reward. Duplicate/overflow conversions, research-send rewards and refunds are excluded. Permit only one active Star Piece, reject reactivation without consumption, and do not stack duration. Its effect can coexist with a Shiny Lure because they affect different rewards.

### Button-based catch flow

1. `/walker` shows the oldest unresolved encounter privately: species/form, CP, shiny indicator, bag counts and selected ball/berry. Buttons open **Ball**, **Berry**, **Throw**, **Later**, **Run** actions; selection can use a small submenu.
2. Choosing a ball or berry only updates the selection. **Throw** atomically checks owner, encounter revision/state, inventory and available Pokémon storage before consuming **one ball and at most one berry**. A storage-full result spends nothing and links to Storage/Research Send.
3. Roll capture once and persist the attempt/result. Success creates one Pokémon instance and awards the catch resources in the same transaction. Failure consumes the selected items, then rolls flee; otherwise offer another throw. Clear the berry after the attempt.
4. **Master Ball requires a separate confirmation** naming the target. Revalidate capacity and ownership at confirmation; on success consume it and guarantee capture. Never draw a flee result on this path.
5. **Later** retains the encounter unchanged; reopening does not reroll species, level, IVs or shiny. **Run** discards it permanently; require a second confirmation for shiny encounters. Disable terminal controls and show the persisted result.

Use `p = 1 − (1 − clamp(BCR/(2×CPM), 0, 1))^(ball×berry)`; set throw, curve and medal modifiers to **1**. A timing minigame would reward connection/device speed and add interaction failure modes without improving this collection loop, so omit it in v1.

Set explicit per-species/form encounter classes in the bot balance data: **common BCR 0.50, uncommon BCR 0.30, rare BCR 0.15**. Do not infer rarity solely from main-series `capture_rate`; do not add a legendary class before its encounter rules exist. As a **derived example**, BCR 0.30 at level 20 (`CPM = 0.5974` in the selected reference) gives approximately **25.1%** with Poké Ball and no berry, or **58.0%** with Ultra Ball + Razz. Higher level affects catch difficulty through CPM; IVs and displayed CP do not independently enter this formula.

Choose **10% flee after a failed ordinary catch** and **0% for shiny encounters**. No automatic encounter expiry in v1; unresolved encounters still occupy the bounded queue. These are forgiving bot rules, not GO mechanics. A successful catch never also flees. Master Ball remains useful for guaranteed immediate capture and saving ordinary resources.

### Consistency requirements for implementation

- Persist encounter state outside ephemeral messages. Reopening `/walker` creates fresh controls for the same state after a restart or expired interaction.
- An attempt is unique by **encounter + attempt ordinal**, with a conditional encounter-version transition. A second click or a second open panel must return the existing result rather than spend again. A Discord interaction ID alone is insufficient because two clicks can have different IDs.
- Keep RNG outcomes, spend, ownership transition, storage insertion and reward ledger atomic; never publish a success before commit. A failed commit spends nothing. Retry rendering from the committed result after a response failure.
- Freeze shiny eligibility/effect at **encounter generation**, but evaluate Star Piece at **reward time**. Both choices are explicit; timestamps and balance versions are recorded for reproducibility.

## Sources

All checked **2026-11-04**. Older numerical research is labeled community evidence; it does not confirm every current exception.

[I1]: https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1094-types-of-items-and-their-effects/
[I2]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/102-finding-catching-wild-pokemon/
[I3]: https://pokemongo.com/news/masterball?hl=en
[I4]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/2480-what-are-incense/
[I5]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/1789-lure-modules/
[I6]: https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1167-reviving-fainted-pokemon-restoring-hp/
[I7]: https://www.csuohio.edu/sites/default/files/66%20B.pdf
[I8]: https://pokemongohub.net/post/guide/silver-pinap-berry/
[I9]: https://www.serebii.net/pokemongo/items.shtml
[I10]: https://pokemongohub.net/post/wiki/catch-mechanics/
[I11]: https://pokemongohub.net/post/news/niantic-hides-base-catch-and-base-flee-rates-from-the-game-master-file/
[I12]: https://pokeapi.co/docs/v2#pokemon-species
[I13]: https://pokemon.gameinfo.io/en/tools/catch-chance-calculator/

