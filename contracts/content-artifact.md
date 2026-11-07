# Contract: installed content snapshot (C1)

## Purpose
Define the deterministic, offline JSON boundary authorized by D34, D38–D40a,
D45, D48–D54 and D59, and PLAN P7/P11.

## Producers
- `python -m content.build [--cache DIR] [--audit-sprites] [--check]`.

## Consumers
- Future bot content loader, encounter services, milestone services and simulation.
- Tests may use the authored `tests/fixtures/content_mini/` snapshot.

## Invariants
- UTF-8 JSON with a final LF; `schema_version: 1`. IDs stay separate:
  `species_id`, `pokemon_id`, `form_id`, and `identity_id` (`pokemon_id:form_id`).
- `identities` contain graph identity fields, D39 derived stats/BST, family topology,
  tier, catch rewards, generation, habitat (identifier or null), `gender_rate`
  (-1 or 0–8), `has_gender_differences`, and `sprites`.
- Indeedee, Basculegion and Oinkologne retain the default male encounter identity;
  `gender_rate` is overridden to 4 (50/50). `gender_varieties.male/female` each
  carry their own IDs, stats and four sprite fields, and inherit male tier/route
  eligibility. Missing varieties or incomplete stats are build errors.
- Sprite keys are `normal`, `shiny`, `female`, `shiny_female`. URLs use the P7
  pinned sprites SHA and that record's own pokemon ID, with path prefixes ``,
  `shiny/`, `female/`, `shiny/female/`. No other form, species or shiny state is
  substituted. Non-default forms use `<pokemon_id>-<form_identifier>` in all four
  paths; a Pokémon's default form keeps `<pokemon_id>`. Confirmed missing images
  are null. Without source CSVs or explicit HEAD auditing, exact URLs are
  unaudited candidates; the manifest says `none`.
  Consumers must tolerate unavailable images. Female keys are null for species
  without gender differences. Gender-variety selection precedes sprite selection.
- `families` maps chain IDs to sorted species IDs; `species` records topology,
  generation, habitat and source flags, independently of encounter multiplicity.
- `routes` maps route IDs to `weights` (identity ID → max type weight) and
  `eligible_counts` by tier. Every non-Legendary/Mythical identity has positive
  weight on at least one route. Habitat is a report field, not a weight override.
- `starters` are the 27 D34 base-stage IDs. `milestones` preserves the authored
  D59 definitions, expands generation and flagged species sets, and adds
  `evolution_lines.families`: family ID, species IDs, Candy, Ultra Ball and
  Stardust rewards. A family qualifies only with ≥2 species and a real parent
  edge; Phione/Manaphy and singletons do not qualify. Every qualifying family
  must have exactly one complete evolution-line milestone.
- `content/manifest.json` records schema/importer versions, full source/sprites
  SHAs, all consumed CSV SHA256s, balance JSON SHA256s, counts, excluded and
  pending source reports, and `sprite_audit` (`none`, `csv`, or `head`). No clocks
  or local absolute paths enter either artifact. The D51 baseline is 1,025 species,
  57 regionals, 71/23 flags, 340 evolution-line families covering 824 species.
- `artifact_sha256` is the SHA256 hex digest of the exact emitted artifact bytes,
  including its final LF. Runtime loaders reject absent or mismatching digests
  before admitting work. This additive field supports M1.2 startup integrity;
  older consumers can ignore it. Artifact contents and schema version stay unchanged.
- A D59 set with absent IDs or inconsistent flags is PENDING; the CLI refuses to
  publish it. Invalid source data, unresolved routes, starters or milestone
  coverage fail the build. `--check` compares both files byte-for-byte, exits 1
  for missing/different files, and never rewrites them. Successful rebuild/check
  exits 0; validation/network errors exit 1 with a diagnostic.
- Cached inputs are hash-verified before use. An already complete pinned cache
  supports offline builds. Network fetching is only needed to populate a cache;
  `--audit-sprites` explicitly enables HEAD requests. Only 404/410 mean absent;
  other network errors fail auditing.
- Balance tables and committed fixture inputs use LF via `.gitattributes` so their
  raw-byte hashes agree across operating systems. Raw downloaded CSV hashes
  continue to describe the upstream bytes exactly.

## Compatibility
This introduces a new persisted boundary with no existing production consumers.
Removing/renaming fields or changing their meanings is breaking and requires a
schema-version change and consumer migration. Source repins and balance changes
require reviewed generated diffs. Rollback restores both committed files together.

## Verification
`tests/test_content_emit.py` covers C1 and the M0.4 ticket's named cases.
`python -m content.build --check` checks the real pinned snapshot.

## Change policy
Requirements and PLAN P7/P11 authorize this initial contract. Deliberate changes
follow `.agents/skills/contract-change/SKILL.md`; an implementation discrepancy
does not authorize changing C1.

## Evolution extension (M6.1a/M6.1b)
D40/D54-D56 and the v1.1/v2 plan Q1/Q6 authorize additive keys with
`schema_version: 1` and `importer_version: "2"`. Existing encounter consumers
continue reading `identities`; no persisted player data changes in this row.
- `evolution_targets` is a list of full identity records (kind `form`, including
  stats, family, English name and four sprite keys), for display and evolution
  only. These records remain in the excluded encounter report and never enter
  `identities`, routes, starter choices or tier pools.
- `evolutions` maps `from_identity_id` to sorted recipe lists. Each recipe has
  `edge_id`, `from_identity_id`, `to_identity_id`, `to_species_id`, `candy`,
  `item` (identifier or null), `gender` (`'female'|'male'|null`) and `label`.
  `edge_id` is `source>target|item-or--|gender-or--`, uniquely identifying the
  normalized recipe, including the sweet choice. Both endpoints resolve in
  identities, their gender varieties or evolution targets; at most 25 distinct
  `item` values (null = Candy only) exist per source and at most 25 recipes exist
  per (source, item). Conditions other than gender and trigger/held item are
  stripped, wildcard sources attach only to species defaults, and Shedinja has
  no incoming evolution. Candy follows family depth under D40.
- `evolution_items` is the sorted list of distinct retained item kinds, each
  with `id` (identifier) and `name_en` from the pin.
- `type_chart` maps all 18 ordinary attacking types to all 18 defending types;
  pinned efficacy 200/100/50/0 becomes 1.6/1.0/0.625/0.390625 respectively.
- Manifest counts add `evolution_targets`, `evolution_edges` and
  `evolution_items`. At the pin exactly three branch targets are retained
  (forms 10228, 10311, 10360), plus 62 non-default Alcremie forms (Q15),
  giving 65 targets and 587 recipes. Alcremie targets remain excluded with reason
  "D52 evolution branch; no separate encounter"; Gmax form 10392 is battle-only.
  Milcery has 63 recipes, nine per sweet, with labels naming the exact form.
  Rollback restores both snapshot files together.
