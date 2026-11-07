# Species data via PokéAPI

Scope: content ingestion for this bot; Pokémon GO parity is a separate decision. Facts below were checked on **2026-11-04**. Suggested files and policies are recommendations, not upstream guarantees.

## Facts

### Resource map

Base URL: `https://pokeapi.co/api/v2/`. `{key}` below accepts an endpoint's numeric ID or API name. Resources have separate ID namespaces; the response links identify their relationships. [PokéAPI documentation](https://pokeapi.co/docs/v2) — checked 2026-11-04.

| Need | Endpoint and response fields | Source; checked |
|---|---|---|
| Species identity/display name | `pokemon-species/{key}/`: `id`, `name` (slug), `names[]` with `language.name` and localized `name` | [Live Pikachu species](https://pokeapi.co/api/v2/pokemon-species/25/); 2026-11-04 |
| Types | `pokemon/{key}/`: `types[].slot`, `types[].type.name` | [Official serializers](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/serializers.py); 2026-11-04 |
| Base stats | `pokemon/{key}/`: `stats[].stat.name`, `stats[].base_stat`; `effort` is a separate field | [Official serializers](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/serializers.py); 2026-11-04 |
| Capture difficulty | `pokemon-species/{key}/`: `capture_rate`, integer up to **255**; larger means easier | [Documentation](https://pokeapi.co/docs/v2); 2026-11-04 |
| Gender ratio | Species `gender_rate`: female probability in eighths; **-1** means genderless. `has_gender_differences` describes visual differences | [Documentation](https://pokeapi.co/docs/v2); 2026-11-04 |
| Varieties/forms | Species `varieties[].pokemon` and `is_default` → Pokémon `forms[]` → `pokemon-form/{key}/`: `pokemon`, `form_name`, `names`, `form_names`, `types`, `sprites`, `is_default`, `is_battle_only`, `is_mega`, `version_group` | [Official serializers](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/serializers.py); 2026-11-04 |
| Evolution graph | Follow species `evolution_chain.url` → `evolution-chain/{id}/`: recursively traverse `chain.species`, `evolves_to[]`, `evolution_details[]` | [Live Pikachu family chain](https://pokeapi.co/api/v2/evolution-chain/10/); 2026-11-04 |

The checked Pikachu response has species ID **25**, `capture_rate: 190`, and `gender_rate: 4`, meaning **4/8 = 50% female**. Its evolution chain ID is **10**, not 25. [Species response](https://pokeapi.co/api/v2/pokemon-species/25/) and [gender semantics](https://pokeapi.co/docs/v2) — checked 2026-11-04.

Current evolution details include version, region, required/evolved form references, and ordinary triggers/items/conditions. The checked family includes distinct Raichu and Alolan Raichu conditions. Treating an evolution chain as one unqualified list loses information. [Live chain](https://pokeapi.co/api/v2/evolution-chain/10/) — checked 2026-11-04.

### Minimal requests

Documented GET requests; no credentials are needed. The species request was checked directly; the Pokémon request uses the documented endpoint. [API documentation](https://pokeapi.co/docs/v2) — checked 2026-11-04.

```bash
curl --fail --silent --show-error \
  https://pokeapi.co/api/v2/pokemon-species/25/
curl --fail --silent --show-error \
  https://pokeapi.co/api/v2/pokemon/25/
```

### Data boundaries and gaps

| Bot requirement | What is confirmed | Source; checked |
|---|---|---|
| GO Attack/Defense/Stamina | Pokémon `stats` are main-series statistics. No GO-specific base-stat resource appears in the documented v2 routes/schema | [API routes](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/urls.py), [schema](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/serializers.py); 2026-11-04 |
| GO stat derivation | Community analysis describes calculating GO base stats from main-series values, combining physical/special stats and incorporating Speed. The author warns that parts may be outdated. **UNVERIFIED:** official Niantic specification, complete exceptions, and exact current parity | [Author's mechanics analysis](https://www.dragonflycave.com/pokemon-go/stats/); 2026-11-04 |
| GO moves and progression | No documented GO fast/charged-move energy/duration schema, CP-multiplier table, GO power-up costs, or GO catch-probability contract | [API routes](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/urls.py), [schema](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/serializers.py); 2026-11-04 |
| Pokéwalker routes | No dedicated route/group/step-unlock/item-table contract. A generic `pokewalker` location exists in the source catalog; complete route-table coverage is **UNVERIFIED** | [API routes](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/urls.py), [location catalog](https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/locations.csv); 2026-11-04 |
| This bot's rules | No API resources for chat-step awards, encounter queues, shiny-lure effects, rare-item inventory caps, research-transfer rewards, or server gyms | [API routes](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/urls.py); 2026-11-04 |

### Fair use and wrappers

PokéAPI provides public GET access without authentication. Its fair-use policy requires local caching of requested resources. Although fixed rate limiting was removed, users are asked to limit request frequency and abuse may result in an IP ban. No numeric requests-per-second allowance is promised. [Fair-use documentation](https://pokeapi.co/docs/v2) — checked 2026-11-04.

| Candidate | Verified capability/maintenance evidence | Source; checked |
|---|---|---|
| Python: **PokeLance** | Async `aiohttp` wrapper with typed models and caching; release **v0.2.17**, **2026-08-04** | [Maintainer README](https://github.com/FallenDeity/PokeLance), [release](https://github.com/FallenDeity/PokeLance/releases/tag/v0.2.17); 2026-11-04 |
| Node: **pokedex-promise-v2** | Promise API, caching, ESM; release **4.2.2**, **2026-02-24**. A cache-TTL unit fix was merged **2026-07-26**, after that release | [Maintainer README](https://github.com/PokeAPI/pokedex-promise-v2), [release](https://github.com/PokeAPI/pokedex-promise-v2/releases/tag/4.2.2), [fix](https://github.com/PokeAPI/pokedex-promise-v2/commit/d8d1aad4503a03a2c968e53d8af370b41f26d80a); 2026-11-04 |
| Python: **PokéBase** | README explicitly says unsupported and lists no maintainer; recent repository activity alone is insufficient maintenance evidence | [Maintainer README](https://github.com/PokeAPI/pokebase); 2026-11-04 |

## Recommendations

### Ingestion and identity

**Pre-seed the approved v1 species/form roster during a content-build job.** Publish a versioned SQLite database or compact JSON snapshot with the bot. Discord interactions should read local content, allowing encounters and storage to work during upstream outages. Lazy fetching is useful for an admin-only import command or development, but adds avoidable latency and failure paths to ordinary interactions.

Keep these identities distinct:

- `species_id`: species identity, localization, capture metadata; candy-family grouping is a separate mapping.
- `pokemon_id`: selected battle variety and its stats/types.
- `form_id`: selected appearance/form resource, where applicable.
- Bot-owned caught-Pokémon ID: individual ownership, shiny flag, gender, power-up state, and other persistent attributes.

Follow returned resource links instead of assuming these IDs match or assigning alternate forms by arithmetic. Parse stats by `stat.name`, not array position; select localized names by language code; preserve missing values. Prefer a form's explicit display name when available, with species-name fallback. Choose the stat/type era explicitly; an HGSS visual style does not require historical HGSS balance.

Store upstream URLs, retrieval timestamp, content hash, importer version, and the bot's `balance_version`. Deduplicate species/evolution-chain requests and persist raw JSON for reproducibility. Refresh explicitly or on a chosen content-maintenance schedule, validate relationships, and promote the new snapshot atomically. Use bounded concurrency, timeouts, and backoff; do not turn “no fixed rate limit” into an unlimited crawler. Sprite caching is covered in [sprites.md](sprites.md).

### Fill gaps with small, reviewable content files

These are proposed filenames, not files created by this research task.

| Gap | Recommended v1 source of truth |
|---|---|
| GO-style stats | Deterministic build-time conversion from main-series stats, backed by an approved written mechanics source; `go-stat-overrides.json` keyed by `pokemon_id` for audited exceptions. Mark derived results and formula version explicitly |
| CP progression | `cp-multipliers.json` plus a separately documented CP function. Choose either sourced, frozen GO values or an explicitly authored bot curve; never label an approximation “GO-exact.” Keep internal upgrade state even when the UI shows CP |
| GO move behavior | Small `battle-moves.json` keyed by PokéAPI move ID, with separate bot/GO energy, power, duration, and mode fields; `learnsets.json` keyed by `pokemon_id`. Import main-series names/types only; don't interpret main-series PP or power as GO behavior |
| Routes | Hand-authored `routes.json`: terrain, unlock rules, encounter species/form IDs, weights, and item pools. Historical fidelity can be added later from cited descriptions; don't infer routes from generic habitats |
| Candy/evolutions | `candy-families.json` keyed by species ID, plus explicit evolution targets/costs by variety/form. Review branching and regional cases; main-series level/item conditions do not automatically implement this bot's CP progression |
| Economy and catching | Versioned bot configuration for catch probabilities, rewards, shiny odds/lures, and inventory caps. Keep upstream `capture_rate` as metadata or a documented difficulty input; **190/255 is not a justified GO catch probability** |

Prefer PokeLance for an async Python importer or `pokedex-promise-v2` for Node if a wrapper helps. Pin the dependency and validate required fields against the current schema. Check whether the Node TTL fix is in the installed package; do not assume repository `master` equals the published release. A small direct HTTP importer with a persistent cache is also sufficient. Neither wrapper's convenience cache replaces the shipped content snapshot.

**Open decisions:** exact GO parity versus authored GO-style balance; included forms; stat era used for conversion; move/battle mode; evolution/candy policy; refresh ownership. Until resolved, current GO constants and historical Pokéwalker encounter rates remain **UNVERIFIED**, not defaults to invent.
