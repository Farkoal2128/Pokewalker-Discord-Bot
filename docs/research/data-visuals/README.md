# Data and visuals — research task 4

Checked **2026-11-04**. Scope: species content, shiny-aware assets and Discord rendering for the chat-step bot. The owner's CP, candy/research-transfer, stored rare-item and per-server gym decisions remain the design context. This folder contains research and recommendations, not an implemented asset pipeline.

## Facts — key findings and numbers

| Finding | Source / checked |
|---|---|
| PokéAPI separates species, battle varieties and forms. Its main-series stats and capture metadata are not GO CP data; GO multipliers/moves require another source or authored rules. | [PokéAPI docs](https://pokeapi.co/docs/v2), [official schema](https://github.com/PokeAPI/pokeapi/blob/master/pokemon_v2/serializers.py) · 2026-11-04 |
| Species `capture_rate` is bounded by **255**; `gender_rate` is female chance in **eighths**, with **-1** for genderless. Capture rate divided by 255 is not an established GO catch probability. | [PokéAPI docs](https://pokeapi.co/docs/v2) · 2026-11-04 |
| HGSS static examples are **80×80 PNG** with normal/shiny, front/back and female paths. The repository also documents PNG-named HGSS front animations; complete form/variant coverage is not guaranteed. | [Sprite README](https://github.com/PokeAPI/sprites/blob/master/README.md), [HGSS tree](https://github.com/PokeAPI/sprites/tree/master/sprites/pokemon/versions/generation-iv/heartgold-soulsilver) · 2026-11-04 |
| Discord's default is **20 MiB per file**; Create Message separately documents **25 MiB per request**. Interactions require acknowledgment within **3 seconds**, and their tokens last **15 minutes**. Read `attachment_size_limit`; token expiry is not a message-deletion timer. | [Upload reference](https://docs.discord.com/developers/reference#uploading-files), [message resource](https://docs.discord.com/developers/resources/message), [interactions](https://docs.discord.com/developers/interactions/receiving-and-responding) · 2026-11-04 |
| Animated GIF/WebP are supported, but static output remains useful. Pokémon sprite copyright and repository licenses are distinct; generic CC0 background options exist. | [Discord media formats](https://discord.com/blog/modern-image-formats-at-discord-supporting-webp-and-avif), [sprite licence](https://github.com/PokeAPI/sprites/blob/master/LICENCE.txt), [Kenney](https://kenney.nl/assets/background-elements) · 2026-11-04 |

## Recommendations — v1 scope

- **Content:** Build a versioned local PokéAPI snapshot for an explicitly selected roster. Keep GO-style conversion, CP progression, move rules and routes in small reviewed bot-owned files. Do not fetch upstream during `/walker`.
- **Art:** Start with audited HGSS static variants and original or inspected CC0 backgrounds. Preserve species/form/gender/shiny identity through every fallback; end with a neutral placeholder and an explicit shiny label.
- **Scenes:** Composite encounter, catch result, gym frame and paginated storage views locally; upload PNGs in ephemeral responses. Use Pillow for Python or sharp/Canvas for Node, with nearest-neighbor integer scaling for pixel sprites.
- **Performance:** Bound render concurrency; cache source files and rendered bytes using complete scene/version keys. Proposed defaults: **768×432 scenes**, **12 storage entries/page**, **under 1 MiB output**. These are design choices. Small-VPS timing estimates are **UNVERIFIED**, pending measurement on the target host.

## Open design decisions

1. Exact GO parity or an explicitly authored GO-style balance; which stat era and battle mode?
2. Approved species/forms and asset rights/provenance; strict HGSS appearance or accepted modern fallback?
3. Python or Node renderer, final layouts/fonts, and storage page size?
4. Background pack and night-theme policy; content-refresh ownership and measured host budgets?

## Read by topic

| File | Contents |
|---|---|
| [pokeapi-data.md](pokeapi-data.md) | Endpoints/fields, identity, GO/Pokéwalker gaps, caching, wrapper maintenance |
| [pokeapi-forms.md](pokeapi-forms.md) | Full-roster forms filter, regional forms, Legendary/Mythical flags, families/stages, pinned commit |
| [sprites.md](sprites.md) | Exact HGSS paths, alternatives, coverage, usage statements and fallbacks |
| [backgrounds.md](backgrounds.md) | Fan resources, original/CC alternatives and terrain/gym mapping |
| [discord-rendering.md](discord-rendering.md) | Discord constraints, delivery tradeoffs, Python/Node examples and caches |

**Evidence boundary:** Live Discord client tests, complete asset audits, exact current GO constants and target-host performance remain **UNVERIFIED**. Rendering examples can be checked locally without importing Pokémon assets. Asset adoption and application implementation are later work.
