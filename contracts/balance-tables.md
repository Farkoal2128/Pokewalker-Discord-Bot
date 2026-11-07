# Contract: Bot-owned balance tables (C4)

## Purpose

Define the authored balance inputs under `content/balance/`, their units,
provenance, and loader boundary. Requirements are the approved decisions in the
[feature README](../docs/features/pokewalker-bot/README.md) and
[PLAN section 4.1](../docs/features/pokewalker-bot/PLAN.md). This contract is assigned
to M0.3 by PLAN section 4.2. Tables encode bot rules; the CPM table freezes the
selected published reference and does not claim publisher-exact live precision.

## Producers

- Repository authors maintain the reviewed JSON files below and in the revisions.
- `content.balance.load_table(name)` reads those local files without network
  access, writes, interpolation, or generated defaults.

## Consumers

- The offline content build and economy simulation consume authored tables.
- Domain/gameplay code consumes the versioned content artifact produced from
  these inputs, as required by ADR 0001; it does not fetch live balance data.
- `tests/test_balance_tables.py` validates the authored rules and loader boundary.

## Invariants

### Common envelope and loader

Each UTF-8 JSON file is an object with `source`, `checked`, and `version`, alongside
the payload named below. `source` is a nonempty citation to the authorizing
requirement/plan/research section or published reference. `checked` is an ISO
calendar date (`YYYY-MM-DD`); it records the reference/rule check date, not a claim
of live game acceptance. `version` is the integer `1` for these initial tables.
Provenance stays in source control with the values it describes.

`load_table(name: str) -> dict` takes a bare lowercase snake_case table stem
matching `[a-z][a-z_]*`, without `.json` or a directory. It returns a fresh decoded
object on each call, so mutating one result cannot alter later loads. Invalid
names raise `ValueError`; valid names without a file raise `FileNotFoundError`;
invalid JSON raises `json.JSONDecodeError`. Other filesystem errors propagate.
It loads trusted repository inputs; full table-shape and rule validation is
performed by the contract tests, not by this small loader at runtime.

Item and route IDs use lowercase snake_case. Species IDs and generation numbers
are integers from the pinned content identity. Probabilities are fractions in
`[0, 1]`; percentage weights below are integer relative weights. Durations are
real seconds. Stardust, Candy, item quantities, accepted words, and capacities
are integer counts unless another unit is explicitly named.

### Table payloads

| File | Payload and units | Required rules |
|---|---|---|
| `step_rules.json` | `rules`: accepted-word counts, durations, and integer step hundredths | First 300 accepted words per rolling hour award 100 hundredths each; later words award 25. Per-message minimum 4, maximum 20, repeat-word cap 3; cooldown 15 seconds; 30 accepted words per rolling minute; duplicate window 1,800 seconds. Encounter/find thresholds are 10,000 hundredths; finds cap at 3 per rolling hour; companion Candy threshold is 15,000 hundredths. |
| `tier_chances.json` | `chances`: tier ID to integer weight | `common` 60, `uncommon` 30, `rare` 3, `evolved` 6, `legendary` 1; total 100. `legendary` includes Mythical identities. |
| `catch.json` | `rules`: probabilities, multipliers, inclusive roll ranges | BCRs: Common .50, Uncommon .30, Rare/Evolved .15, Legendary/Mythical .05. Ball multipliers 1/1.5/2; Razz 1.5, Golden Razz 2.5, Silver Pinap 1.8, Pinap 1. Pinap Candy multiplier 2; Silver Pinap Candy uses numerator 7, denominator 3, rounding `floor`. Flee .10 after ordinary failed throws, zero for shiny and Legendary/Mythical. Shiny probability 1/256; lure probability multiplier 4 for the next `lure_encounters: 10` generated encounters (no duration key). Wild whole-level range 1-20 and each IV 0-15; starter level 10 and each IV 10-15. |
| `find_table.json` | `rows`: weighted item packs | v1 table below totals 9,750, with Star Piece and Evolution item excluded. |
| `checkin_table.json` | `rows`: weighted item packs | Great Ball quantity 1/weight 35; Razz quantity 1/weight 30; Poke Ball quantity 2/weight 20; Pinap quantity 1/weight 15. Total 100. |
| `powerup_prices.json` | `bands`, `cap_level_x2` | Hidden level uses integer twice-level. Each band is lower-inclusive and upper-exclusive, charging for one half-level step from the current level. Bands cover every integer 2-79 exactly once; cap is 80. Costs are listed below. |
| `cpm.json` | `multipliers`: string `level_x2` to numeric multiplier | Exactly 79 entries with keys `"2"` through `"80"`, strictly increasing, for levels 1.0-40.0 in half-level increments. Values are transcribed from the published reference selected by P8; no runtime interpolation. |
| `conversion_rates.json` | `stardust_per_unit`: item ID to integer Stardust | v1 only: Poke Ball 2, Great Ball 5, Ultra Ball 10, Razz/Pinap 5, Golden Razz/Silver Pinap 25, Rare Candy 20, Master Ball/Shiny Lure 500. No v1.1 or v2 items. |
| `capacities.json` | `limits`: counts and `starter_kit` item quantities | Storage 250; bag 250 ordinary item units; separate Master Ball/Shiny Lure pockets 1 each; encounter queue 3; starter kit 30 Poke Balls and 5 Razz. |
| `milestones.json` | Named categories and reward bundles below | All D59 categories, pinned thresholds, explicit species groups, and evolution-line rule are present. |
| `routes.json` | `routes`: unique `id`, `name`, `weights` map | Eight P1 routes. Type weights are integers 1-3; an omitted type has weight zero. Every one of the 18 types has positive weight on at least two routes. Encounter weight is the higher weight of its identity's types; Legendary/Mythical selection ignores route weights (D38). |
| `gym_income_table.json` | `rows`, `tenure_seconds` | D23 full 13-row table below totals 10,000; tenure is 28,800 seconds. `gym_income_table` is gameplay data for v2 and also supports the offline D47 comparison. |
| `simulation.json` | Offline assumptions and previously implicit D12/D22/D29 item rules | Check-in every 3,600 active seconds: guaranteed Poke Ball first, then common pack; ordinary overflow 10 Stardust, duplicate rare find 500. M0.8 supersedes M0.6's five-Poke-Ball reserve with the ordered throw policy below; the legacy table field is retained but unused. Fallback profiles preserve adaptation B1's daily counts (10/25/60 messages) and estimate words as counted characters divided by 5 (10/12/15); distribute each day's messages across its active hours. Research daily award caps are superseded by D20. Measured hourly accepted-word percentiles are sampled equally, reconstructed as spaced messages subject to C2. These are declared simulation assumptions, not measured conversation or new gameplay rules. |

### Offline model boundary (M0.6)

`scripts.economy.model.run_scenario(rng, *, active_hours=1, days=30,
profile="regular", measured_path=None, artifact=None, balances=None,
style="continuous")` takes an injected `random.Random` and optional decoded
fixture inputs. `profile` also accepts exactly one finite nonnegative numeric
`messages_per_hour` or `messages_per_day`, plus positive integer
`words_per_message` for sensitivity tests; booleans are invalid. Styles are
`continuous` and `hourly check`. Unsupported styles/profiles, invalid durations,
and malformed present measurement files raise `ValueError`; only an absent
measurement falls back to regular. No network or private chat inputs are read.
Measured accepted-word percentiles are rounded to whole words and reconstructed
with messages small enough to respect the rolling-minute cap, including across
consecutive active hours. Unsupported totals (above 60 times the minute cap,
or positive totals below the minimum first message) raise `ValueError`.
Default content and balances are loaded from this repository. Routes cycle by
cumulative active hour across days in authored `routes.json` order, starting
with Refreshing Field (P1), independently of artifact map ordering. A starter and queued encounter
are granted at enrollment. No transfers or evolution are simulated; storage
halts catches when full. Milestones award once to an inbox and claim what fits.
Candy is family scoped; the starter is the favourite and receives power-ups.
First-shiny mean/median are labelled geometric expectations using simulated
generated-encounter pace, alongside the observed first-shiny day. Lures and
Pinap are not activated by this fixed throw policy. Outputs are dictionaries
containing labelled inputs, stock-limited item/currency flows, collection pace,
power-up costs, route pools and analytic Legendary identity/group pacing.

This additive table/API has no prior consumers or player migration. Existing
tables retain their values and versions; the content manifest gains the new
table's hash. The existing content builder tolerates additional balance tables.

### Demand accounting and gym comparison (M0.8)

The offline policy prefers Poke, Great, then Ultra Ball, falling back to any
remaining ball (including Master Ball); the existing Legendary Master Ball
preference remains. With no stock it rolls a virtual Poke Ball using the same
catch/flee calculation. Only ball consumption is exempt: a selected Razz Berry
is consumed, and subsequent throws lose its multiplier when it runs out.
Virtual catches/flees free the slot, including Legendary/Mythical encounters;
the existing storage limit still applies. `stockout_events` counts encounters
whose first attempted throw begins with zero balls, once per encounter.

`run_scenario` retains actual by-type `balls_supplied` (starter, finds, check-in,
claimed milestones) and `balls_spent`, and adds by-type `unmet_ball_demand`,
labelled **estimate: throws the policy would have made with unlimited supply**.
Scalar `ball_demand` is spent plus unmet across types; `deficit` is
`max(0, ball_demand - balls_supplied)` across types. `minimum_inventory` records
the minimum item balance throughout the run; virtual throws never decrement balls.
Virtual catches feed the same progression and milestones, so these are policy
estimates, not predictions of actual stock-limited catch or income outcomes.

`gym_income.items_per_deployment` maps each D23 item to its expected quantity
(row weight / total weight times quantity times full hours in D24 tenure).
`balls_per_deployment` sums ball items, including Master Balls. Scenario totals
`balls_one_deployment_daily` and `balls_all_day` multiply that expectation by
days and by days times 86,400 / tenure respectively. Reports label (a) one
8-hour deployment per day and (b) held all day with immediate re-deployment,
and compare (a) to the same scenario's total deficit, without tuning balances.
They retain a failed D47 expectation if a run does not establish the intended
shortfall or gym closure. A zero deficit is reported as "no deficit".

The model produces these additive dictionary fields for the report CLI and
economy tests; no persisted player data or migration exists. The M0.8 ticket
intentionally revises the reserve/stockout semantics, so earlier seeded M0.6
numbers must be regenerated. JSON inputs and versions remain unchanged.

### Weighted packs and power-up bands

Each weighted row has unique `item`, positive integer `quantity`, and positive
integer `weight`. A roll selects one entire pack using weights normalized by
that table's own total; weights are not rounded percentages. `stardust` is a
currency pack, not an inventory item. Gym rows preserve find quantities.

| Item | Find quantity | v1 find weight | Gym weight |
|---|---:|---:|---:|
| `poke_ball` | 5 | 5,000 | 4,940 |
| `great_ball` | 3 | 1,800 | 1,800 |
| `ultra_ball` | 1 | 600 | 600 |
| `razz_berry` | 1 | 800 | 800 |
| `pinap_berry` | 1 | 800 | 800 |
| `golden_razz_berry` | 1 | 150 | 150 |
| `silver_pinap_berry` | 1 | 100 | 100 |
| `rare_candy` | 1 | 200 | 200 |
| `stardust` | 100 | 240 | 240 |
| `shiny_lure` | 1 | 50 | 100 |
| `master_ball` | 1 | 10 | 20 |
| `star_piece` | 1 | absent | 50 |
| `evolution_item` | 1 | absent | 200 |

| Current `level_x2` | Candy per half-level | Stardust per half-level |
|---|---:|---:|
| `[2,20)` | 1 | 100 |
| `[20,40)` | 2 | 250 |
| `[40,60)` | 3 | 500 |
| `[60,80)` | 4 | 1,000 |

### Milestone payload

`bundles` maps Bronze/Silver/Gold/Platinum/Diamond lowercase IDs to item/Candy/
Stardust quantity maps, with the exact D59 contents. Each category entry's
`bundle` refers to this map.

- `pokedex`: seven `{percent, species_count, bundle}` entries for 5/10/25/50/75/90/
  100 percent, thresholds 52/103/257/513/769/923/1,025, and bundles Bronze/Bronze/
  Silver/Gold/Platinum/Platinum/Diamond.
- `starter_trios`: nine `{generation, species_ids, bundle}` entries, Bronze each;
  `all_starters`: the same 27 base starter species with Gold.
- `regions`: nine `{generation, bundle}` entries, Platinum each, counting every
  species of that generation including Legendary/Mythical species.
- `first_legendary` and `first_mythical`: Silver each.
- `legendary_groups`: 19 `{id, species_ids, bundle}` entries, Platinum each, with
  the exact D59 Birds-through-Loyal-Three species lists.
- `mythical_sets`: five `{generation, species_ids, bundle}` entries for generations
  3-7, Platinum each, with the exact D59 species lists.
- `all_legendaries` and `all_mythicals`: `species_count` 71 and 23 respectively,
  Diamond each. The build must reconcile pinned species flags; disagreement
  blocks acceptance rather than silently rewriting the authorizing D59 lists.
- `ultra_beast_first_catches`: 11 `{species_id, bundle}` entries, Silver each,
  for species 793-799 and 803-806.
- `evolution_lines`: `minimum_species` 2, `requires_real_evolution` true,
  `family_candy` 25, `ultra_ball` 1, `stardust_per_species` 250;
  `expected_family_count` 340 and `expected_species_count` 824 at the D51 pin.
  A shared chain ID alone is insufficient, so Phione/Manaphy does not qualify.
- `extra_bundle_lines`: five `{id, species_ids, bundle}` entries: Type: Null
  772/773 Gold, Kubfu 891/892 Gold, Meltan 808/809 Gold, Cosmog 789/790/791/792
  Platinum, and Poipole 803/804 Silver, in addition to the evolution-line reward.

Milestones count caught species, folding forms into their species. Deriving the
actual qualifying family list and reconciling pinned flags is the content build's
responsibility; awarding, inbox delivery, and persistence belong to later rows.

## Compatibility

This is the additive initial SI-0 boundary; no older balance consumers or player
data are migrated. Future changes to existing field names, units, ID meanings,
category membership, ordering assumptions, or numerical rules require consumer
review and a deliberate version update. Optional new fields may be additive only
when consumers demonstrably tolerate them. Never silently replace unavailable
inputs with defaults. Old artifacts keep their recorded balance/version inputs;
changing authored tables alone does not mutate running or persisted gameplay.

## Verification

Run `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_balance_tables.py"`
and `git diff --check` (plus `git diff --cached --check` for staged additions).
The test module covers every M0.3 named acceptance case: weighted totals and exact
packs, routes, CPM key count/order/checkpoints, D59 thresholds/categories/groups/
extra bundles, conversion rates, contiguous prices, and metadata. Additional
tests cover step/catch/capacity values, invalid loader paths, missing tables, and
fresh decoded results. CPM checkpoint coverage is not an automated audit of every
published reference value. Full SI-0 checks and independent review remain required
by PLAN; these focused checks alone do not establish launch readiness.

## Change policy

Requirements precede tables. Intentional changes must first reconcile the
[feature decisions](../docs/features/pokewalker-bot/README.md),
[plan](../docs/features/pokewalker-bot/PLAN.md), and
[ADR 0001](../docs/decisions/0001-application-stack.md). Identify producer/consumer
compatibility, deliberately update the contract/version/provenance, add meaningful
RED contract tests, then change data/implementation and verify GREEN. Record a new
ADR before changing the content-source policy. A failing implementation or a
pinned species-flag disagreement never authorizes changing D59 by itself.


## v1.1 balance revision (M6.2)

This revision supersedes the v1 exclusions and single-version rules above under
[PLAN Q1-Q5](../docs/features/pokewalker-v1.1-v2/PLAN.md).
The repository author remains the producer; the loader, offline content builder,
economy model, find/conversion services and route/bag screens consume these tables.
Existing keys and default capacities remain compatible. Find probabilities and
conversion availability deliberately change under D21/D61; their table versions
increase. No persisted records are migrated by this data-only row.

The four revised tables have `version: 2`, a nonempty `source` citing the
requirements/decisions, and `checked: "2026-11-05"`. The new `evolution.json` has
`version: 1` with the same provenance fields/date. All other table versions and
values remain unchanged.

- `find_table.json`: add quantity 1/weight 50 `star_piece` and quantity 1/weight
  200 `evolution_item`; all other packs stay unchanged, giving total weight 10,000.
  The placeholder remains literal until M6.4a resolves it uniformly to a distinct
  enabled evolution-item kind (or 100 Stardust if none exist); this intermediate
  tree is not delivered. Gym table values remain unchanged.
- `conversion_rates.json`: retain all v1 rates and add `star_piece: 50` and
  `evolution_item: 100` Stardust per unit. M6.4a applies the latter to every
  `content["evolution_items"]` kind. `world_legendary_ticket` remains absent.
- `evolution.json`: `candy: {single_step: 50, two_step: [25, 100]}`;
  `item_price_stardust: 500`; `star_piece: {multiplier_numerator: 3,
  multiplier_denominator: 2, rewards: 10, rounding: "floor"}`. Q3 replaces the
  researched duration with the next ten catch/find Stardust rewards. There is
  no duration field; the activation/counter service belongs to M6.5a/b.
- `capacities.json`: retain `limits` exactly (250 storage/250 bag enrollment
  defaults and existing rare pockets). Add sibling `expansion` with
  `storage: {step: 50, max: 1000, stardust: 5000}` and
  `bag: {step: 50, max: 1000, stardust: 2500}`. Purchase enforcement is later work.
- `routes.json`: retain route order, IDs, names and type weights; add integer
  lifetime awarded `unlock_steps` of 0, 0, 1000, 2500, 5000, 8000, 12000, 18000 in
  P1 order. Unlock enforcement and current-route backfill belong to M6.7a/b.

Regenerate the production manifest through `python -m content.build`. It hashes
all balance JSONs, including `evolution.json`; the content artifact bytes stay
unchanged because these additions do not alter its emitted payload. Focused
verification runs balance-table, content-integrity, find and economy-model tests,
`python -m content.build --check`, and `git diff --check`. Exact-tree full SI-1
qualification and independent review remain separate G-6 requirements.

## v2 battle and gym balance revision (M7.1)

This revision follows D23/D24/D32/D40b/D60 and the approved
[PLAN Q6/Q7/Q9](../docs/features/pokewalker-v1.1-v2/PLAN.md).
Repository authors produce the tables; the existing loader, content builder and
contract tests consume them. M7.2 consumes battle rules; M7.3 derives rare item
kinds from `limits.rare_pockets`; later gym services consume gym and survivor rules.
The new tables and keys are additive; existing capacities and expansion prices
stay unchanged. No persisted data is migrated. Runtime WLT enforcement and gym
behavior are later rows, so this intermediate tree is not final acceptance.

`battle.json` and `survivor_table.json` have `version: 1`; `capacities.json`
increases to `version: 3`. Each has nonempty `source` and `checked: "2026-11-05"`.

- `battle.json` has `rules`: `fast: {power: 6, energy: 10, ticks: 1}`,
  `charged: {power: 60, energy_cost: 50, ticks: 2}`, `stab: 1.2`,
  `energy_cap: 100`, `tick_limit: 120`, `party_max: 3`, `cooldown_seconds: 600`,
  and `damage: "floor(0.5 * power * attack / defense * stab * effectiveness) + 1"`.
  `defender_hp: {base_factor_x10: 20, per_hour_x10: 1, rounding: "ceil"}` encodes
  `ceil(canonical_HP * (20 - h) / 10)` for full hours `h` from 0 through 7.
  `type_factors: {super: 1.6, neutral: 1.0, resisted: 0.625, immune: 0.390625}`
  must equal the exact set of values in the artifact's `type_chart`, including neutral.
  Ticks are abstract simulation units; cooldown is real seconds and has no daily quota.
- `survivor_table.json` has `stardust_flat: 500` plus eight `rows` of
  `(item, quantity, weight)`: Ultra Ball `(5, 2500)`, Golden Razz `(3, 2000)`,
  Silver Pinap `(3, 1500)`, Rare Candy `(5, 1500)`, Star Piece `(2, 1000)`,
  Shiny Lure `(1, 800)`, Master Ball `(1, 600)`, World Legendary Ticket `(1, 100)`.
  Total weight is 10,000; flat Stardust is paid with every item outcome. D60
  rewards enter the inbox on undefeated tenure expiry, with no overflow conversion.
- `capacities.json` adds `limits.rare_pockets.world_legendary_ticket: 1` and
  top-level `gyms: {per_guild: 10, name_max: 32}`. Gym counts and ticket pockets
  are per server; gym names have 1-32 characters.
- `gym_income_table.json` remains byte-for-byte unchanged: total 10,000,
  Master Ball weight 20, Shiny Lure 100, Poke Ball 4940, tenure 28,800 seconds.
  Its `evolution_item` placeholder is resolved by `items.resolve_item` in M7.4b.

Rebuild the production manifest with `python -m content.build` to record all
balance hashes. Artifact payload and CSV inputs remain unchanged. Focused checks
cover balance tables, content integrity, economy model, the raw-CSV rebuild check
and diff whitespace. G-F2 retains independent review and full-suite qualification.
