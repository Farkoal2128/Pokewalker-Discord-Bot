# GO move data sources

Scope: A6. **Checked 2026-11-04.** This file adds move-data decisions to the existing [CP/resource model](../go-systems/README.md); it does not replace or re-research that model. Facts describe the sources inspected, not a guarantee of live GO server behavior.

## Facts

### Battle modes require different data

The official GO help article explicitly says a Charged Attack's energy requirement can differ between **Gyms/Raids** and **Trainer Battles**. A shared move name therefore does not identify one universal stat record. Source: [official attack help][official-attacks], checked 2026-11-04.

**PokéAPI does not document GO move stats.** Its Move resource exposes main-series fields such as `power`, `pp`, `accuracy`, `priority` and `damage_class`; Pokémon learnsets are associated with game version groups and learning methods. There are no documented GO PvE energy, duration, damage-window or GO-specific move-pool fields. This confirms the limitation of the documented API, not the absence of every possible third-party extension. Sources: [official PokéAPI schema][pokeapi-docs] and [project history identifying main-series data][pokeapi-about], checked 2026-11-04.

### Source comparison

| Source | What it provides | Fitness for this bot | Source; checked |
|---|---|---|---|
| **PokeMiners `game_masters`** | Decoded GO configuration, latest files, historical snapshots and a timestamp file | Useful research/reference input; schema interpretation and live parity need verification | [Repository README][miners-readme]; 2026-11-04 |
| **PvPoke** | A Pokémon GO **PvP** simulator and curated Pokémon/move model | Useful simulation/reference architecture; its PvP values are not gym-PvE values | [Project README][pvpoke-readme]; 2026-11-04 |
| **PoGoAPI** | Separate PvE/PvP move endpoints, species/form move pools and file hashes | Convenient candidate PvE adapter; current correctness is not guaranteed | [Provider documentation][pogoapi-docs]; 2026-11-04 |
| **PokéAPI** | Main-series identities, names, types and move/learnset metadata | Identity/reference input; cannot supply the missing GO combat parameters | [Official schema][pokeapi-docs]; 2026-11-04 |

**PokeMiners details.** The README warns that obfuscated field names may be uncertain or renamed. The latest timestamp-file commit observed was **2026-08-29**, commit `8e227be44f288d34463e23bf04e9b564d3c16f79`; a folder named `latest` does not prove parity with GO on the check date. Exact current completeness and release eligibility remain **UNVERIFIED**. Sources: [README][miners-readme], [observed commit][miners-commit], checked 2026-11-04.

A published consumer of this dataset reads PvE `moveSettings` fields `movementId`, `pokemonType`, `power`, `durationMs` and `energyDelta`; it reads species `quickMoves`/`cinematicMoves` separately from Elite-move arrays. This is inspectable importer behavior, not an official schema contract. A repository issue also reports a missing `damageWindowStartMs` for a PvE move. Missing timing must not silently become zero. Sources: [consumer's source][miners-consumer], [upstream issue][miners-window-issue], checked 2026-11-04.

**PvPoke details.** Its move editor uses `moveId`, `power`, `energy`, `energyGain`, `cooldown` and turn-related fields. A field called `cooldown` here belongs to PvP simulation; it is not evidence of the corresponding gym animation/damage timing. Source: [maintainer's editor implementation][pvpoke-editor], checked 2026-11-04.

**PoGoAPI endpoints.** PvE `fast_moves.json` and `charged_moves.json` expose power, duration, energy delta and type. `current_pokemon_moves.json` separates ordinary/Elite fast/charged pools and forms. The `pvp_*_moves.json` endpoints use PvP values, including turn duration. `api_hashes.json` supports cached-file change detection. Sources: [provider documentation][pogoapi-docs], checked 2026-11-04. Its documented PvE schema does not expose damage windows; exhaustive current payload coverage is **UNVERIFIED**.

### Licenses and usage terms

These are observed notices, not a legal determination that a particular fan project is authorized.

| Source | Confirmed notice or terms | Remaining boundary | Source; checked |
|---|---|---|---|
| PokeMiners | README says educational use and attributes contents to The Pokémon Company/Niantic. No standalone license appeared in the inspected repository root. | No explicit reusable data license was confirmed; redistribution permission **UNVERIFIED** | [README/root listing][miners-readme]; 2026-11-04 |
| PvPoke | Repository software license is **MIT**; retain its copyright and permission notices when copying covered software. The site's footer separately attributes Pokémon material to its owners. | MIT software licensing does not establish permission for all underlying third-party game data, names or artwork; those rights **UNVERIFIED** here | [LICENSE][pvpoke-license], [site notice][pvpoke-notice]; 2026-11-04 |
| PoGoAPI | Legal page asserts fair use, supplies information as-is and warns it can become outdated. Documentation recommends local caching. | No explicit transferable data license, completeness guarantee or update SLA was confirmed; redistribution terms **UNVERIFIED** | [Legal notices][pogoapi-legal], [documentation][pogoapi-docs]; 2026-11-04 |
| PokéAPI | Server repository uses **BSD 3-Clause** terms: retain required notices and do not imply contributor endorsement. Hosted API fair-use rules require local caching. | This software license is not a blanket license for third-party Pokémon assets or GO data | [LICENSE.md][pokeapi-license], [fair-use policy][pokeapi-docs]; 2026-11-04 |

No publisher-supported bulk export of complete GO PvE move stats was confirmed in this review: **UNVERIFIED**, not an assertion that none exists. Community data and game configuration are evidence inputs, not a complete specification of server timing or AI.

## Recommendations — bot design

### v1 source strategy

Use a **small, explicitly bot-balanced move roster** for the supported launch species/forms. Keep the progression research's CP, IV, level, Candy and Stardust model unchanged. The [battle-system proposal](battle-system.md) owns move powers, energy rules and simulation timing; this file owns their provenance boundary.

Define one fast and one charged slot for each battle loadout, backed by a deliberate form-to-move pool. Reuse appropriate identities/types where verified, but label custom combat values as bot values. Do not populate GO legality from PokéAPI's main-series learnset, and do not label a custom roster “exact GO.” Move names, data imports and artwork still follow the repository's content-source decision process.

Defer bulk Game Master imports and live-data synchronization. If closer GO PvE fidelity becomes a requirement, evaluate a **version-pinned PvE adapter** after recording permitted usage/provenance. PoGoAPI is simpler to consume; PokeMiners exposes lower-level configuration but requires more schema validation. PvPoke should be considered only when intentionally adopting its PvP model, not as an interchangeable gym-data source.

### Minimal normalized records — schema only

| Record | Proposed fields |
|---|---|
| `MoveDefinition` | Stable internal `move_key`; `source_mode` (`bot`, `go_pve`, `go_pvp`); upstream identifier/aliases; display name; type; fast/charged kind; power; energy gain or positive cost; duration; explicit duration unit; damage timing policy; balance version |
| `FormMovePool` | Stable species/form key; allowed fast/charged move keys; availability policy; effective version; provenance reference |
| `MoveSourceVersion` | Provider/URL; upstream commit or file hash; retrieval time; schema version; observed license/terms reference; approved-use decision reference; validator version |
| Battle/defender snapshot additions | Selected move keys plus resolved immutable values; type chart, battle-engine and balance versions; source-version identifiers |

Keep PokéAPI IDs, GO IDs and internal IDs distinct with explicit mappings. Match forms deliberately; localized move names are display text, not join keys. Keep normal and event/Elite availability separate even if v1 permits only a small curated subset.

For custom v1 moves, use the battle engine's declared ticks and damage-at-completion policy. For any future PvE import, distinguish **total move duration** from **damage application/window timing** and specify a conversion policy. Never convert milliseconds to turns by assuming that every simulator uses the same clock.

### Update and validation boundary

- Load approved data before play; no provider request belongs inside a battle or button handler. An outage must not change an already accepted result.
- Validate mode, units, positive duration, nonnegative power, energy semantics, known types, legal form pools and unique IDs. Reject an unsupported or incomplete move rather than silently inventing a value.
- Hash and retain the normalized approved configuration needed for replay. A new upstream file becomes a candidate version; it does not rewrite an active defender or battle snapshot.
- Review balance changes and compare representative matchups before activation. Keep outcomes reproducible from the stored snapshots and engine version.
- Do not infer acquisition availability merely because a move/form exists in configuration. Record enabled species/forms and move availability explicitly.

### Open decisions

- Approve the compact launch roster and its bot-specific balance values.
- Decide whether later fidelity requires verified GO PvE damage windows and move pools, or whether custom timing remains the permanent design.
- Record the content-source decision before importing maintained datasets or assets; unresolved third-party rights are not resolved by the hobby/non-commercial description.

## Sources

All checked **2026-11-04**. Links are references; no Game Master tables, binary data, sprites or third-party code are reproduced in this document.

[official-attacks]: https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/1011-fast-attacks-charged-attacks/
[pokeapi-docs]: https://pokeapi.co/docs/v2
[pokeapi-about]: https://pokeapi.co/about
[pokeapi-license]: https://github.com/PokeAPI/pokeapi/blob/master/LICENSE.md
[miners-readme]: https://github.com/PokeMiners/game_masters
[miners-commit]: https://github.com/PokeMiners/game_masters/commit/8e227be44f288d34463e23bf04e9b564d3c16f79
[miners-consumer]: https://github.com/codebox/pokemon-grid/blob/main/scripts/update_data.py
[miners-window-issue]: https://github.com/PokeMiners/game_masters/issues/6
[pvpoke-readme]: https://github.com/pvpoke/pvpoke
[pvpoke-editor]: https://github.com/pvpoke/pvpoke/blob/master/src/js/devtools/gm-editor/GMEditorMoveInterface.js
[pvpoke-license]: https://github.com/pvpoke/pvpoke/blob/master/LICENSE
[pvpoke-notice]: https://pvpoke.com/contact
[pogoapi-docs]: https://pogoapi.net/documentation/
[pogoapi-legal]: https://pogoapi.net/Legal/
