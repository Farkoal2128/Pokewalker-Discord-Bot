# Routes and encounters

Checked: **2026-11-04**. Scope: historical encounter availability and a suggested data contract. These are reference tables, **not approved Discord balance settings**. See [mechanics.md](mechanics.md) for the complete route/unlock list and [adaptation.md](adaptation.md) for chat pacing.

## Facts: how to read a route

- A course has six Pokémon entries arranged as three pairs, groups A/B/C. A stroll selects one entry per pair; changing the selection requires returning and sending the walking Pokémon again. Thus a stroll exposes three candidates, not all six. The precise pair-selection distribution is **UNVERIFIED** here. [Serebii courses][SC], checked 2026-11-04.
- Eligibility uses today's steps; this counter resets at midnight. [Bulbapedia Pokéwalker][BW], checked 2026-11-04.
- Device route records hold three Pokémon and ten items, with ordered threshold/chance checks. [Grinberg, route structures][DG], checked 2026-11-04.
- An advantageous carried type reduces Pokémon thresholds by **25%**. Item threshold reduction is **UNVERIFIED: sources disagree**. Serebii says it applies; Bulbapedia and Altissimo say it does not. Examples retain published normal/advantageous Pokémon thresholds and normal item thresholds. Rounding for other values is **UNVERIFIED**. [Serebii][SC], [Bulbapedia][BW], [Altissimo][ALT]; checked 2026-11-04.
- Altissimo reports **one shared 0–99 roll**, checked A → B → C when eligible; items redraw. With eligible Doduo, its A/B/C outcomes are **70/5/25%**, versus Serebii's **70/22.5/7.5%** (independent checks). **UNVERIFIED conflict:** these effective rates need further audit. Neither means six normalized species weights. [Altissimo][ALT], [Serebii][SC]; checked 2026-11-04.
- PokéAPI distinguishes a species from its Pokémon varieties. Its species `id` is an identifier; `order` is a different sorting field. Species records also expose a main-series `capture_rate`, which does not itself specify this bot's catch rule. [PokéAPI documentation][API], checked 2026-11-04.

The example species/thresholds agree between Bulbapedia and Pokémon Database. Neither example below reconstructs raw RNG probabilities from coarse rarity labels. Slot labels below are **local labels**, not firmware indices. [Refreshing Field][RF], [RF comparison][RFD], [Noisy Forest][NF], [NF comparison][NFD]; checked 2026-11-04.

**Source discrepancy:** Refreshing Field Nidoran♂ is **500 steps** on Bulbapedia/Pokémon Database/Serebii, versus Altissimo's **2,000**. Correct value: **UNVERIFIED**; the sample preserves both reports and leaves its authoritative threshold unset. [Altissimo][ALT], [RF][RF], [RF comparison][RFD], [Serebii][SC]; checked 2026-11-04.

## Recommendations: schema contract

**RECOMMENDATION — store historical facts separately from bot configuration.** Use the structure below as a small reference catalog. Set any adopted bot thresholds and rates explicitly in a different balance configuration; never silently treat physical steps as chat steps.

| Field/convention | Proposed meaning |
| --- | --- |
| `pokemon_by_species_id` | Map keyed by PokéAPI **species** ID; never by display name, `pokemon` variety ID, or `order`. |
| `slots` | List, even when there is only one entry. Repeated species must retain distinct group/event profiles. |
| `slot_id` | Our stable label within this route; not an HGSS memory/ROM index. |
| `min_steps` / `min_steps_adv` | Historical normal/advantageous Pokémon eligibility thresholds. |
| `rarity` | Source's qualitative label; not a probability or weight. |
| `items` | Tuples `[pokeapi_item_slug, normal_min_steps, rarity]`; array order is presentation only. |
| `radar_group_check_order` / `dowsing_entry_check_order` | Keep group cutoffs and item checks distinct. A `null` order is **UNVERIFIED**; do not infer it by sorting thresholds. |
| `probability_defaults` | Unverified pair probability, Radar cutoff, and dowsing conditional chance remain `null`, inherited by slots/items. `null` never means zero. |
| `sources`, `checked` | Factual provenance/date inherited by every child record; ID/slug mapping uses the separate API sources. |

**RECOMMENDATION — preserve probability semantics.** Keep reused-roll Radar cutoffs, fresh-roll dowsing chances, check order, and effective outcomes separate. Do not normalize raw cutoffs or conditional checks into weights. Label a simplified v1 sampler's independently chosen weights as bot design choices.

**RECOMMENDATION — separate identity and encounter profile.** Keep form/variety, event moves, fixed gender, and other historical restrictions inside a slot profile when needed. Do not collapse repeated entries into one species row. This limited walking-loop sample omits original levels, moves and gender; it is not a complete reconstruction of caught Pokémon. GO-style CP belongs to the separate power design.

## Facts: two example routes

Both are initially available. Each example includes all six Pokémon candidates and all ten item candidates. Names, groups, step minima, advantageous types and rarity labels come from the linked route pages. [RF][RF], [NF][NF], checked 2026-11-04. Numeric species IDs and item slugs were cross-checked against the official PokéAPI source catalogs; they are API identifiers, **not copied HGSS item IDs**. [Species catalog][SPECIES], [item catalog][ITEMS], checked 2026-11-04.

The YAML is a **recommended serialization of historical facts**. Root provenance and unknown defaults apply to both routes. Local `A1`/`A2` labels only distinguish the two slots.

```yaml
schema_version: 1
checked: '2026-11-04'
classification: historical_reference
species_identity_source: 'https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_species.csv'
item_identity_source: 'https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/items.csv'
probability_status: UNVERIFIED
probability_defaults:
  stroll_pair_selection: null
  radar_cutoff_percent: null
  dowsing_check_percent: null
radar_selection_model: reported_single_roll_ordered_cutoffs
radar_selection_status: UNVERIFIED_sources_disagree
radar_group_check_order: [A, B, C]
radar_selection_source: 'https://altissimo1.github.io/Main-Series/HGSS/pokewalker.html'
dowsing_entry_check_order: null
dowsing_entry_check_order_status: UNVERIFIED
item_advantage_modifier_status: UNVERIFIED_sources_disagree
routes:
  refreshing-field:
    name: Refreshing Field
    sources:
      - 'https://bulbapedia.bulbagarden.net/wiki/Refreshing_Field_(Pok%C3%A9walker)'
      - 'https://pokemondb.net/heartgold-soulsilver/pokewalker/refreshing-field'
    unlock: initial
    advantageous_types: [fire, bug, flying]
    pokemon_by_species_id:
      115:
        name: kangaskhan
        slots: [{slot_id: A1, group: A, min_steps: 3000, min_steps_adv: 2250, rarity: uncommon}]
      84:
        name: doduo
        slots: [{slot_id: A2, group: A, min_steps: 2000, min_steps_adv: 1500, rarity: very_common}]
      29:
        name: nidoran-f
        slots: [{slot_id: B1, group: B, min_steps: 500, min_steps_adv: 375, rarity: very_common}]
      32:
        name: nidoran-m
        slots:
          - slot_id: B2
            group: B
            min_steps: null
            min_steps_adv: null
            rarity: very_common
            threshold_status: UNVERIFIED_sources_disagree
            reported_thresholds:
              - {source: 'https://bulbapedia.bulbagarden.net/wiki/Refreshing_Field_(Pok%C3%A9walker)', min_steps: 500, min_steps_adv: 375}
              - {source: 'https://altissimo1.github.io/Main-Series/HGSS/pokewalker.html', min_steps: 2000, min_steps_adv: null}
      16:
        name: pidgey
        slots: [{slot_id: C1, group: C, min_steps: 0, min_steps_adv: 0, rarity: very_common}]
      161:
        name: sentret
        slots: [{slot_id: C2, group: C, min_steps: 0, min_steps_adv: 0, rarity: very_common}]
    items:
      - [revive, 2500, rare]
      - [full-heal, 2000, rare]
      - [burn-heal, 1000, rare]
      - [ice-heal, 900, rare]
      - [chesto-berry, 800, rare]
      - [awakening, 700, common]
      - [cheri-berry, 600, common]
      - [paralyze-heal, 500, common]
      - [oran-berry, 300, common]
      - [potion, 0, very_common]
  noisy-forest:
    name: Noisy Forest
    sources:
      - 'https://bulbapedia.bulbagarden.net/wiki/Noisy_Forest_(Pok%C3%A9walker)'
      - 'https://pokemondb.net/heartgold-soulsilver/pokewalker/noisy-forest'
    unlock: initial
    advantageous_types: [fire, ice, flying]
    pokemon_by_species_id:
      202:
        name: wobbuffet
        slots: [{slot_id: A1, group: A, min_steps: 4000, min_steps_adv: 3000, rarity: rare}]
      69:
        name: bellsprout
        slots: [{slot_id: A2, group: A, min_steps: 3000, min_steps_adv: 2250, rarity: very_common}]
      46:
        name: paras
        slots: [{slot_id: B1, group: B, min_steps: 700, min_steps_adv: 525, rarity: very_common}]
      48:
        name: venonat
        slots: [{slot_id: B2, group: B, min_steps: 700, min_steps_adv: 525, rarity: very_common}]
      21:
        name: spearow
        slots: [{slot_id: C1, group: C, min_steps: 0, min_steps_adv: 0, rarity: very_common}]
      43:
        name: oddish
        slots: [{slot_id: C2, group: C, min_steps: 0, min_steps_adv: 0, rarity: very_common}]
    items:
      - [net-ball, 5000, rare]
      - [revive, 2500, rare]
      - [green-shard, 2000, rare]
      - [ether, 1000, very_rare]
      - [energy-root, 900, very_rare]
      - [energy-powder, 800, common]
      - [big-mushroom, 700, very_rare]
      - [pecha-berry, 500, common]
      - [tiny-mushroom, 200, common]
      - [cheri-berry, 0, very_common]
```

## Recommendations: integration and remaining checks

- **RECOMMENDATION:** author a small v1 route catalog using verified species metadata plus separately approved chat-step thresholds. Keep the above thresholds as historical documentation.
- **RECOMMENDATION:** freeze the route/config version, selected slot/species, eligibility snapshot and shiny result when an encounter is enqueued. Route changes or later activity must not reroll queued encounters.
- **RECOMMENDATION:** resolve normal item slugs through PokéAPI; map rewards into the separately researched GO-style item system. An original item table does not authorize importing its effects or encounter rate into v1.
- **UNVERIFIED:** pair-selection biases, imported raw cutoffs/chances, exact item-check order for these examples, disputed values above, and rounding/edge behavior. Exact reconstruction needs more verification; the proposed bot need not depend on these unknowns.
- **UNVERIFIED:** PokéAPI coverage of complete Pokéwalker course tables. Its verified species identifiers are useful here; do not assume its generic location encounters reproduce Pokéwalker slots.

## Full tables and source register

All links checked **2026-11-04**. No ROM files, binaries, disassembly or copied code are included.

| Source | Use |
| --- | --- |
| [Grinberg write-up][DG] | Primary route-record structure; mechanics authority when independently verified sources disagree. |
| [Serebii: all courses and full encounter/item tables][SC] | Full catalog and group selection; probability/modifier discrepancies flagged above. |
| [Altissimo: mechanics and complete course tables][ALT] | Reused Radar roll versus fresh item checks; disputed thresholds/modifiers. |
| [Bulbapedia route directory][BW] | Links to every individual course; full unlock summary is in `mechanics.md`. |
| [Refreshing Field][RF] / [comparison][RFD] | Example species, items, thresholds and qualitative rarities. |
| [Noisy Forest][NF] / [comparison][NFD] | Example species, items, thresholds and qualitative rarities. |
| [PokéAPI docs][API], [species source][SPECIES], [item source][ITEMS] | Identifier semantics and verified ID/slug mappings. |

[DG]: https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker
[SC]: https://www.serebii.net/heartgoldsoulsilver/pokewalker-area.shtml
[BW]: https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9walker#Routes
[RF]: https://bulbapedia.bulbagarden.net/wiki/Refreshing_Field_(Pok%C3%A9walker)
[NF]: https://bulbapedia.bulbagarden.net/wiki/Noisy_Forest_(Pok%C3%A9walker)
[RFD]: https://pokemondb.net/heartgold-soulsilver/pokewalker/refreshing-field
[NFD]: https://pokemondb.net/heartgold-soulsilver/pokewalker/noisy-forest
[API]: https://pokeapi.co/docs/v2#pokemon-species
[SPECIES]: https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_species.csv
[ITEMS]: https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/items.csv

[ALT]: https://altissimo1.github.io/Main-Series/HGSS/pokewalker.html
