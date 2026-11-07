# Storage and data model

Scope: A10 and B7–B8. Research checked **2026-11-04**. Start with [README](README.md). This is a schema sketch and design recommendation, not a migration or approved runtime contract.

## Facts — GO storage and available data

Source labels in this section resolve to links checked **2026-11-04**.

| Topic | Finding | Evidence and confidence |
|---|---|---|
| Initial Item Bag | **350 items**; a purchased upgrade adds **50** slots | Official [S1] |
| Initial Pokémon storage | The widely reported starting value is **300**; **UNVERIFIED against a current first-party source** in this review | Current community reference [S7]; do not confuse base capacity with level-up rewards |
| Pokémon storage upgrades | An upgrade adds **50** slots | Official item help [S2] |
| Upgrade price | **200 PokéCoins for +50** Pokémon or item slots is documented by Google Play's game guide and player shop observations | [S3], [S6]; a dated shop price, not a permanent promise |
| Level-up expansions | Since the October 2025 leveling change, level rewards also add storage and can take a player above the purchasable cap | Official [S4] |
| Current maximum | July 2026 player reports distinguish purchasable limits **12,650 Pokémon / 12,000 items**, with level rewards reaching **13,000 / 12,750** at Trainer level 80 | Firsthand reports [S6]. **UNVERIFIED as universal current limits on 2026-11-04**; no current first-party numeric cap was confirmed |
| Historical maximum | Official December 2024 announcement: **9,300 Pokémon / 8,300 items** | [S5]. Historical evidence only, not today's maximum |
| Full bag | Blocks ordinary collection from PokéStops, Gyms and battle rewards; using/discarding items or upgrading frees room. Gifts/stickers are examples of excluded items | Official [S1] |
| Collection management | Search can filter CP, family, favorite and shiny; favoriting protects against transfer | Official [S8] |

**Implication:** there is no single timeless GO storage cap to copy. Distinguish starting capacity, purchased expansion, level rewards and an account's effective capacity. This bot's limits should be its own configuration.

### PokéAPI boundary

PokéAPI documents main-series base stats/types on `pokemon`, species identifiers and evolution-chain links on `pokemon-species`, and branching evolution conditions on `evolution-chain`. Species and battle forms are distinct concepts. These schemas do **not** define GO CP multipliers, GO Candy prices, GO shiny release flags, or GO encounter catch/flee probabilities. Its main-series evolution conditions do not automatically describe GO. Source: [PokéAPI documentation][S9], checked **2026-11-04**.

Discord interactions identify the actor and originating context and support ephemeral replies. Interaction tokens are temporary response credentials, so they are unsuitable as permanent game-state identifiers. Source: [Discord interaction documentation][S10], checked **2026-11-04**.

## Recommendations — v1 capacities and UX

All numbers below are **proposed bot defaults**, not GO facts or measured balance results.

| Setting | Proposed value / rule |
|---|---|
| Pokémon capacity | Start **100**; count all owned Pokémon, including any assigned to an activity |
| Ordinary item capacity | Start **250 units**; a stack of 30 balls occupies 30 units |
| Rare capacity | Separate pockets: **one Master Ball and one Shiny Lure**; neither consumes ordinary bag space |
| Currency | Stardust and family Candy do not occupy item slots; unused Rare Candy does |
| Pokémon expansion | Spend **5,000 Stardust for +50 slots**, up to **1,000** |
| Bag expansion | Spend **2,500 Stardust for +50 units**, up to **1,000** |
| Expansion transaction | Show cost/new capacity; debit and expand atomically; never charge at the hard cap |
| Encounter queue | Provisional **3 unresolved encounters per player globally**, including an open encounter; aligns with the existing draft requirement, subject to step-loop research |

Use one global collection/inventory per Discord user for v1, with guild-scoped step permissions and gyms. Enforce earning limits globally so joining another server does not multiply daily rewards. This is a recommendation; per-guild collections remain an open product decision. Do not let one server admin edit another server's gym configuration or a player's global inventory.

**Full Pokémon storage:** preserve the encounter, explain the capacity, and offer **Open Storage**, **Send for Research**, **Expand**, **Back**. Recheck capacity during each attempted catch before spending items or drawing the catch outcome. Do not replace an existing Pokémon or silently discard the new one. At queue capacity, additional steps may still count, but no new encounters are minted; no hidden unbounded backlog.

**Full ordinary bag:** keep its existing contents. Apply the fixed conversion rule in [items-and-catching](items-and-catching.md); rare pockets remain eligible. Show a private summary rather than generating public item notifications. Unused items do not expire by default; a consumed timed effect uses its explicit expiry.

Show storage in small pages with filters for **family, CP, shiny, favorite and locked**, plus sort by catch date. Make **Send for Research** a preview-and-confirm operation using [the transfer safeguards](candy-transfer-evolution.md#recommendations-bot-v1). Showing only low CP is not a safe release rule.

## Recommendations — schema-level sketch

IDs are stable opaque identifiers; Discord snowflakes are stored losslessly as decimal text or a suitable integer type, never a JavaScript floating-point number. Timestamps are UTC instants. Runtime/SQL implementation is deliberately unspecified.

| Entity | Key and important fields | Purpose / invariants |
|---|---|---|
| **Player** | `player_id`; unique `discord_user_id`; `created_at`; `stardust`; `pokemon_capacity`; `bag_capacity`; `row_version` | Global owner and capacity limits; balances nonnegative. No Trainer XP required in v1 |
| **GuildConfig** | `guild_id`; enabled flag; step/rate policy version; authorized admin policy | Server-scoped configuration; changes do not mint global resources |
| **GuildChannelPolicy** | `(guild_id, channel_id)`; count-steps/reaction flags | Explicit eligible-channel mapping |
| **StepCredit / DailyBudget** | Credit: unique source message ID, owner/guild, credited steps, occurred-at. Budget: `(player_id, UTC_date)`, accepted base steps, awarded steps in fixed-point units, finds issued, remainder | Deduplicate events and enforce global limits after diminishing returns. Store counts/IDs, not message bodies; retention for deduplication is a separate policy |
| **SpeciesFormBalance** | `form_id`; PokéAPI species/Pokémon/form IDs; `candy_family_id`; base stats; types; catch reward tier; BCR/flee class; shiny-enabled flag; version/source metadata | Curated bot balance, distinguishing species, regional/battle form and family. GO exceptions require explicit overrides, not assumptions from PokéAPI |
| **CPMultiplier / PowerUpBand** | `ruleset_version`, integer `level_x2`; multiplier or cost-band bounds; Candy/Stardust price | One deterministic CP/cost ruleset; integer half-level representation |
| **CandyFamily / PlayerCandy** | Stable `family_id`; display species. Balance: `(player_id, family_id)`, quantity | Shared across a curated evolution family; no name-derived wallet keys |
| **EvolutionRule** | `rule_id`; source/target form; Candy family/cost; optional item/quantity; optional structured conditions; ruleset version | Previewable supported evolution recipe. Absence means unsupported, not an inferred zero-cost recipe |
| **PokémonInstance** | `pokemon_id`; owner; species/form; `iv_attack`, `iv_defense`, `iv_stamina`; `level_x2`; `cp_cache`; `cp_ruleset_version`; `shiny`; `caught_at`; unique source encounter; caught guild; favorite; locked; nickname; ownership state; `row_version` | IVs **0–15** and v1 `level_x2` **2–80**; CP derives from inputs. Preserve shiny/IVs across ordinary power-up/evolution. A sent Pokémon is no longer owned |
| **Encounter** | `encounter_id`; owner; source guild/channel/message; queue order; created-at; fixed form/level/IV/shiny; shiny odds/effect snapshot; balance version; state; `attempt_ordinal`; `row_version` | One immutable generated identity. State progresses to caught/fled/released; reconnecting does not reroll it |
| **CatchAttempt** | Unique `(encounter_id, ordinal)`; selected items; evaluated probability; RNG result; flee result; action receipt; committed-at | Records exactly one attempt; failed rendering never repeats spending |
| **ItemDefinition / InventoryBalance** | Item: ID, kind, effect, `max_held`, bag-counting flag. Balance: `(player_id, item_id)`, quantity | Ordinary quantity nonnegative; rare quantities constrained to **0 or 1**. An active effect is not an inventory item |
| **ActiveEffect** | Effect ID; owner; effect type; magnitude; starts-at; expires-at; originating action; ruleset version | One unexpired effect per player/type. Shiny Lure duration **3,600 seconds**; expiry checked against time after restarts |
| **ResearchSendPreview / PreviewMember** | Preview ID; owner; expiry; confirmed state. Member: preview + exact Pokémon ID/version; quoted family reward | Snapshot of selected IDs, protections and rewards; no broad filter re-evaluation on confirm |
| **ActionReceipt / ResourceLedger** | Receipt: unique logical action key, actor, result, committed-at. Ledger: `(source_action_id, line_key)`, resource/family/item, delta, reason | Logical deduplication plus auditable multi-resource transaction; distinguish replay from a new action |
| **Gym / GymAccessChannel** | Gym ID + guild ID; display name; access rows `(gym_id, guild_id, channel_id)` | Only configuration boundary here: a server chooses gym count and channel access. Combat/rewards are separately researched |
| **PokémonAssignment** | Pokémon ID; activity kind/ID; owning guild when relevant; started-at | Prevent research-send or conflicting use while assigned. Gym-specific combat state remains outside this research |

For `PokémonInstance`, `species_id` identifies the biological species and `form_id` identifies the stat-bearing variety; a costume can be separate cosmetic metadata later. Use a positive `level_x2` integer to avoid floating-point equality errors. A cached CP is never the source from which level or IVs are reconstructed.

### Transaction and constraint requirements

1. **Capture:** validate owner, encounter revision, item availability and capacity; commit spend, attempt, terminal state, Pokémon creation and rewards together. Unique source encounter prevents duplicate Pokémon. Serialize competing mutations for one player; counting free slots outside this boundary is unsafe.
2. **Research-send:** recheck every exact selected ID and its current version/protections/assignment. Apply the whole approved selection or return a changed-selection preview; never silently replace it. Mark ownership ended and credit Candy in one transaction. See [transfer flow](candy-transfer-evolution.md).
3. **Power-up/evolution:** compute the displayed before/after CP with the selected ruleset, validate all costs and prerequisites, and change the same instance atomically. Do not reroll IVs/shiny or refund previously spent power-up resources on send.
4. **Rare acquisition/activation:** enforce quantity bounds in persistence as well as UI. Activation consumes one inventory unit and creates the effect together; reject an existing active effect without consumption. A concurrent duplicate find follows the fixed conversion rule exactly once.
5. **Versioning:** preserve source/balance versions for encounters and owned instances. Refreshing PokéAPI must not silently rewrite existing CP or evolution prices mid-action. A deliberate balance migration needs a separate decision and verification.
6. **Expiry and reconnects:** absolute UTC effect expiry determines eligibility; process restarts cannot restart or pause an hour. Ephemeral panels are views; database state survives their disappearance. Store no bot tokens or interaction tokens in game/audit tables.

### Inputs the later gym task needs

Expose **instance ID, owner, form/types, base stats, IVs, level/CPM, derived Attack/Defense/HP, CP and ruleset version**, plus availability/assignment status. CP alone cannot reconstruct those inputs. Moves, damage, HP persistence, gym teams and reward amounts remain decisions for the gym task.

### Open decisions

- Accept global collection ownership or choose per-guild ownership before schema implementation; do not mix both accidentally.
- Measure encounters/day and dust income before locking expansion prices or the 1,000-slot hard caps.
- Select a limited launch species/form roster and approve its stat/evolution sources. Research notes grant no permission to import ripped assets or a complete game data dump.
- Define retention/deletion policy for message-ID deduplication, transfer tombstones and financial-style resource receipts. Keep retained state proportional to the hobby service's actual recovery needs.

## Sources

All checked **2026-11-04**.

[S1]: https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1235-available-items-your-bag/
[S2]: https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1094-types-of-items-and-their-effects/
[S3]: https://play.google.com/store/apps/editorial?hl=en&id=mc_games_editorialevergreen_postinstall_manage_storage_in_pokemon_go_now_fcp
[S4]: https://pokemongo.com/news/pgo-leveling-update-details-2025
[S5]: https://pokemongo.com/news/december-2024-storage-increase?hl=en
[S6]: https://www.reddit.com/r/TheSilphRoad/comments/1uon5c2/storage_expanded_by_1000_slots/
[S7]: https://mattsimplified.com/guide/storage-and-items/
[S8]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/1486-searching-filtering-your-pokemon-inventory/
[S9]: https://pokeapi.co/docs/v2
[S10]: https://docs.discord.com/developers/interactions/receiving-and-responding
