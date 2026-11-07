# Battle backgrounds

Checked **2026-11-04**. This is a source shortlist and rendering policy; no artwork or source-game data is included. See [sprite rights](sprites.md) separately: permission for a background does not establish permission for the Pokémon placed on it.

## Facts — Pokémon-style sources

| Source | Verified material and published usage statement | Unverified scope |
|---|---|---|
| [Pokémon Showdown client backgrounds](https://github.com/smogon/pokemon-showdown-client/tree/master/play.pokemonshowdown.com/fx) | The repository contains `bg-meadow.png`, `bg-forest.png`, `bg-city.png`, `bg-river.png`, `bg-beach.png`, `bg-dampcave.png`, `bg-earthycave.png`, `bg-icecave.png`, and other battle backgrounds. The [credits](https://pokemonshowdown.com/credits) name Kyle Dove for battle backdrops and Andrew Goodsell/Zracknel for weather backdrops. Checked 2026-11-04. | The [README](https://github.com/smogon/pokemon-showdown-client/blob/master/README.md) licenses the **client software under AGPLv3**. An image-specific reuse grant covering each backdrop is **UNVERIFIED**; attribution is not itself permission. |
| [Karthik_ — Bunch Of FRLG Battle Backgrounds](https://eeveeexpo.com/resources/1270/) | The creator describes the collection as FRLG-style backgrounds released for public use. Examples include cave, desert, indoor and underwater scenes, separate battle bases, and editable PSD files. Credits list Desgrades, Thundaga and Karthi; the page makes Karthi's credit optional. Checked 2026-11-04. | This is a fan-resource statement, not a standard CC license. Exact redistribution conditions and the provenance/rights of all constituent artwork are **UNVERIFIED**. |

**Facts:** These are source-page URLs, not a guarantee of permanent hosting. A concrete Showdown source path is [`fx/bg-meadow.png`](https://github.com/smogon/pokemon-showdown-client/blob/master/play.pokemonshowdown.com/fx/bg-meadow.png); GitHub supports commit-pinned file URLs. Coverage of a specifically licensed night background in these candidates is **UNVERIFIED**. Sources: [Showdown directory](https://github.com/smogon/pokemon-showdown-client/tree/master/play.pokemonshowdown.com/fx), [GitHub permanent links](https://docs.github.com/en/repositories/working-with-files/using-files/getting-permanent-links-to-files); checked 2026-11-04.

## Facts — original-art / CC-licensed alternatives

These pages offer generic game artwork independently of Pokémon asset catalogs. “Original-art alternative” does not mean its style exactly matches HGSS.

| Creator / pack | Published license or terms | Coverage / provenance |
|---|---|---|
| [Kenney — Background Elements](https://kenney.nl/assets/background-elements) | The official asset page identifies **CC0**. Kenney's [support page](https://kenney.nl/support) states that assets on its asset pages are CC0, including commercial use, and attribution is optional. Checked 2026-11-04 via indexed primary pages; direct page retrieval was unavailable. | Components for assembling original backdrops, rather than a verified complete battle-scene set. Exact grass/cave/water/city/night coverage is **UNVERIFIED**. |
| [Nidhoggn — Backgrounds](https://opengameart.org/content/backgrounds-3) | The submission identifies Nidhoggn as author, describes RPG battle backgrounds and publishes them under **CC0**. Checked 2026-11-04. | Described as RPG battle backgrounds; requested terrain-by-terrain coverage is **UNVERIFIED** without asset inspection. |
| [Willibab — Free Pixel Battle Backgrounds](https://willibab.itch.io/willibabs-free-pixel-battle-backgrounds) | **Custom terms, not CC:** personal/commercial use and modifications permitted; credit Willibab or Monsteretrope; do not resell the assets or claim authorship. The page lists 320×240, 640×480 and 960×720 sheets and a forest background. Checked 2026-11-04. | Preview sprites are credited to The Mighty Palm, and the shown UI is excluded; a shared license for these preview elements is **UNVERIFIED**. |

**Facts:** [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) permits copying, modification and distribution without asking permission, but does not affect trademark rights or other people's rights. Its grant covers the dedicated work; composing Pokémon sprites over it does not place those sprites under CC0. Checked 2026-11-04.

## Recommendations — v1 selection and mapping

**Recommendation:** Use simple original backgrounds, or a visually checked CC0 pack, for v1. Keep fan-resource candidates as optional alternatives requiring asset-specific rights review. Define local background IDs; do not make gameplay depend on a mutable third-party image URL. Any future content import should follow the repository's asset/ADR process. Compare camera angle and style before selecting a pack; retain listed contributor credits and inspect the downloaded terms. Treat preview sprites, fonts and UI as separately sourced assets.

**Recommendation:** Author one coherent scene family with clear foreground platforms and space for CP/HP labels. The following mapping is a design proposal, not an HGSS or GO rule. An explicit per-server gym theme overrides the route default.

| Route terrain / gym theme | Background ID | Composition |
|---|---|---|
| Grassland; Grass gym | `meadow` | Grass platforms, open horizon |
| Forest; Bug gym | `forest` | Trees behind an uncluttered clearing |
| Cave/mine; Rock or Ground gym | `cave` | Rock platforms, readable interior |
| River/lake/coast; Water gym | `shore` | Shore platforms and water behind them |
| City; Electric or Steel gym | `city` | Plaza/platforms with distant buildings |
| Snow; Ice gym | `snow` | Snowfield with dark-edged platforms |
| Indoor/unmapped gym | `arena` | Neutral arena usable for any type |
| Night route; Dark or Ghost theme | Existing terrain + `night` palette | Preserve label and sprite contrast |

**Recommendation:** Treat night as a palette/lighting variant so terrain remains recognizable. Store the selected background and palette in the encounter/battle snapshot. Timezone-driven night is an open design decision; an explicit theme avoids requiring geographic data.

**Recommendation:** Maintain an asset manifest with `background_id`, creator, source permalink, license/terms URL, checked date, local SHA-256, dimensions, palette variants and sprite anchor points. Pin a repository commit or release and cache selected files locally during asset preparation. Preserve attribution and license text alongside imported assets. This research does not verify archive contents or authorize redistribution of an entire third-party pack.

**Recommendation:** Fallback in order: selected validated background → bundled original neutral arena → flat color. Never block an encounter because a remote image fails. Scale pixel artwork by integer factors with nearest-neighbor and avoid stretching mismatched compositions; see [rendering](discord-rendering.md).

## Open decisions

- Select original commissioned/self-authored scenes, a specific CC0 pack, or an explicitly approved fan resource.
- Inspect actual downloads for terrain coverage, transparent battle bases, dimensions and any license notices before import; these details remain **UNVERIFIED** where marked above.
- Decide whether night is an admin-selected style, route property or time-based variant; it should not silently change battle mechanics.
