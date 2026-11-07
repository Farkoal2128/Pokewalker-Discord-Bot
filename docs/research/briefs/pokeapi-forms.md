# Research brief: PokéAPI forms, flags and families for the full roster

> **Historical prompt (completed by PR 6).** The rules quoted below are as they stood when the
> brief was written. The current rules are D38/D46/D50 for tiers, D40/D54/D55 for evolution
> costs and items, and D51–D58 for forms, all in the
> [requirements draft](../../features/pokewalker-bot/README.md).

Written **2026-11-04** for one GPT Pro research pass. Paste this whole file as the prompt.
Write the result to `docs/research/data-visuals/pokeapi-forms.md`.

## Context

The bot builds its content at build time from a pinned PokéAPI snapshot, never live during
play. See [pokeapi-data.md](../data-visuals/pokeapi-data.md) for the data model already
researched. The owner's decisions in the
[requirements draft](../../features/pokewalker-bot/README.md) are:

- **D37:** every main-series species is catchable. Each species' default form and its
  **regional forms** (Alolan, Galarian, Hisuian, Paldean) are separate encounters.
  Legendaries and Mythicals are included. Mega, Primal, Dynamax/Gigantamax, Z-Moves,
  Terastallization and other **battle-only** forms or transformations are excluded.
  Cosmetic forms use the default form.
- **D38 as amended by D46:** each encounter rolls a rarity tier from evolution stage and
  base-stat total (BST). Common is a base or single-stage species with BST < 400. Uncommon
  is a middle stage with BST < 500, or a base/single-stage species with BST 400–499. Rare is
  any non-final or single-stage species with BST ≥ 500. Evolved is the final stage of a
  family with 2 or more members. Anything flagged `is_legendary` or `is_mythical` is
  Legendary/Mythical.
- **D45:** routes are type-themed and the planner sets how many there are. Report how
  complete PokéAPI's `habitat` field is, by generation, so it can help assign routes.
- **D40:** Candy families come from evolution chains. Evolution costs Candy by stage (25 for
  the first stage, 100 for the second, 50 in two-member families), and non-item conditions
  become Candy-only.

The content importer needs mechanical rules that implement these decisions without
hand-picking more than a short, documented exception list.

## Questions

### A. How PokéAPI represents variants

Explain how these are modelled across `pokemon-species` → `varieties` (`pokemon`) →
`pokemon-form`, and which fields identify each: `is_default`, `is_battle_only`, `is_mega`,
`form_name`, and name suffixes such as `-gmax`, `-totem` and `-alola`.

- Mega and Primal; Gigantamax and Eternamax.
- Totem Pokémon; Pikachu costume and cap forms; Partner Pikachu and Eevee (Let's Go);
  Ash-Greninja.
- Battle-only form changes: Castform, Cherrim, Aegislash, Darmanitan Zen (including
  Galarian), Wishiwashi, Minior, Mimikyu, Palafin and similar.

**Output:** an include/exclude filter rule that the importer can apply. Show it working on at
least one example from every category above.

### B. Regional forms

Give the complete list of regional forms in the current PokéAPI data, with the species ID,
the variety (`pokemon`) ID and name, and the region. Include special cases such as Paldean
Tauros breeds, Galarian Darmanitan (and its Zen form), and regional forms whose evolutions
differ (for example Galarian Meowth → Perrserker, Hisuian forms with new evolutions).

### C. Non-regional forms with different stats or types

D37 only decides regional and cosmetic forms. Classify every other multi-variety species as
**stat-different** (different base stats or types), **cosmetic**, or **battle-only**. This
includes:

- gender forms (Meowstic, Indeedee, Basculegion, Oinkologne)
- Rotom appliances; Deoxys, Wormadam, Shaymin, Giratina, Kyurem and Necrozma fusions
- Lycanroc, Oricorio, Toxtricity, Urshifu, Calyrex riders, Zacian/Zamazenta Crowned
- Ogerpon masks, Terapagos, Basculin stripes, Zygarde percentages, Hoopa
- anything else you find

For each stat-different group, list what an importer could do (treat as separate encounters,
use the default form only, or make it a held form change) without picking one. The owner
will decide.

### D. Legendary and Mythical flags

List exactly which species PokéAPI flags `is_legendary` and `is_mythical`. Then report how
these groups are flagged: Ultra Beasts, Paradox Pokémon, Type: Null/Silvally, Cosmog line,
Kubfu/Urshifu, Poipole/Naganadel, Meltan/Melmetal, the Loyal Three and Pecharunt. Note
where common fan categories ("sub-legendary", "Ultra Beast") don't match the flags.

### E. Evolution chains for Candy families (D40)

- How to compute a species' evolution **stage** and **family** reliably from
  `evolution-chain`. Cover branched chains (Eevee, Tyrogue, Wurmple), baby Pokémon added
  later (Pichu, Azurill, Munchlax), regional-form-specific branches, and cross-species
  conditions (Shelmet/Karrablast).
- List the evolution triggers and conditions PokéAPI uses: `level-up`, `use-item`, `trade`,
  `shed`, `spin`, `three-critical-hits` and so on. Mark which use one of the 7 supported
  evolution items (Sun Stone, King's Rock, Metal Coat, Dragon Scale, Up-Grade, Sinnoh Stone,
  Unova Stone) and which would become Candy-only.
- Note any family where "stage" is ambiguous. Shedinja is one example.

### F. Data completeness and pinning

- Species count and highest species ID in the latest PokéAPI release and on `master`.
  Include the release date and commit.
- Coverage of the Generation 9 DLC (Kitakami, Blueberry Academy, Terapagos, Pecharunt), and
  of any species or forms added by later games up to the check date.
- Known open data issues on GitHub that affect stats, types, forms, flags or evolution
  chains.
- A recommended commit or release to pin, and how to detect upstream changes.

### G. Tier sanity check (optional, if you can compute it)

Apply the D38 tier rule to the data and report the number of species and regional forms in
each tier. Flag oddities: babies, single-stage high-BST species, Shedinja, Wishiwashi, and
legendary-flagged pre-evolutions such as Cosmog.

## Deliverable format

- One topic file following the house rules: **Facts** (each with a source link and checked
  date) and **Recommendations** in separate sections, with gaps marked **UNVERIFIED**.
- Lists of IDs and names are fine. Do not paste PokéAPI JSON, sprites or other bulk data.
- Close with the exact filter rule and stage/family algorithm as plain-language pseudocode,
  plus the list of owner decisions the research could not settle (from section C).
