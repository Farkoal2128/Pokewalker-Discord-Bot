# Sprites: source, identity, and fallback policy

Research checked **2026-11-04**. This document describes sources; it imports no assets. Recommendations below are project choices.

## Facts

### HGSS paths

PokéAPI's sprite repository documents **80 × 80 PNG** static HeartGold/SoulSilver examples. The eight combinations below use the following base; `{key}` is an asset filename key, commonly a Pokémon ID, but not always a bare number. The README shows Pikachu (`25`) examples, and repository directory checks confirmed `25.png` in all eight locations. Sources: [sprite README](https://github.com/PokeAPI/sprites/blob/master/README.md), [HGSS tree](https://github.com/PokeAPI/sprites/tree/master/sprites/pokemon/versions/generation-iv/heartgold-soulsilver) (**checked 2026-11-04**).

```text
https://raw.githubusercontent.com/PokeAPI/sprites/{ref}/sprites/pokemon/versions/generation-iv/heartgold-soulsilver/
```

| View / appearance | Path appended to base |
|---|---|
| Front, normal | `{key}.png` |
| Front, shiny | `shiny/{key}.png` |
| Front, female | `female/{key}.png` |
| Front, shiny female | `shiny/female/{key}.png` |
| Back, normal | `back/{key}.png` |
| Back, shiny | `back/shiny/{key}.png` |
| Back, female | `back/female/{key}.png` |
| Back, shiny female | `back/shiny/female/{key}.png` |

Minimal normal/shiny examples: [normal Pikachu](https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iv/heartgold-soulsilver/25.png), [shiny Pikachu](https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iv/heartgold-soulsilver/shiny/25.png) (**checked 2026-11-04**). For reproducibility, the observed `master` commit was [`1b3b7c0a538dd2226ae08d0d2f8955125075bbd4`](https://github.com/PokeAPI/sprites/commit/1b3b7c0a538dd2226ae08d0d2f8955125075bbd4); use a reviewed commit as `{ref}`, rather than assuming `master` is immutable (**checked 2026-11-04**).

**HGSS is no longer a static-only collection.** Its current tree also has `animated/{key}.png`, `animated/shiny/{key}.png`, and female subdirectories. These are PNG-named front animation assets, not `.gif` paths. Exact decoder support and Discord playback for these files are **UNVERIFIED** here; the static PNG family is a separate choice. Sources: [README](https://github.com/PokeAPI/sprites/blob/master/README.md), [animated tree](https://github.com/PokeAPI/sprites/tree/master/sprites/pokemon/versions/generation-iv/heartgold-soulsilver/animated) (**checked 2026-11-04**).

### Other PokéAPI families and coverage

Paths below are relative to `sprites/pokemon/`. The README documents these families and extensions; this table does not assert every species has every variant. Source: [sprite README](https://github.com/PokeAPI/sprites/blob/master/README.md) (**checked 2026-11-04**).

| Family | Representative paths | Documented appearance / scope |
|---|---|---|
| Default pixel art | `{key}.png`, `shiny/{key}.png`, `back/{key}.png`, `back/shiny/{key}.png` | Broad coverage, including community B&W-style art for later species; not uniformly HGSS art. |
| Gen V animated | `versions/generation-v/black-white/animated/{key}.gif`; insert `shiny/`, `back/`, or `back/shiny/` before the filename | Animated pixel art; female variants use corresponding `female/` subdirectories. |
| Showdown | `other/showdown/{key}.gif`, `other/showdown/shiny/{key}.gif`, `other/showdown/back/{key}.gif`, `other/showdown/back/shiny/{key}.gif` | Animated modern appearance; variable dimensions. |
| Pokémon HOME | `other/home/{key}.png`, `other/home/shiny/{key}.png`, plus `female/` and `shiny/female/` | Documented 512 × 512 front renders. |
| Artwork | `other/official-artwork/{key}.png`, `other/official-artwork/shiny/{key}.png` | Documented 475 × 475 illustrations. The README credits custom shiny artwork to community contributors. |
| Newer game families | e.g. `versions/generation-viii/sword-shield/{key}.webp`, `versions/generation-ix/scarlet-violet/{key}.webp` | WebP families and separate PNG icons are documented. |

The inspected HGSS listing contains `493.png` but no `494.png`; it also contains form-specific keys such as `172-spiky-eared.png` and `201-exclamation.png`. Consequently, neither “all species have HGSS art” nor “construct every form URL from a species ID” is a valid contract. Full per-species coverage is **UNVERIFIED** until audited. Sources: [HGSS listing](https://github.com/PokeAPI/sprites/tree/master/sprites/pokemon/versions/generation-iv/heartgold-soulsilver), [contribution/audit guidance](https://github.com/PokeAPI/sprites/blob/master/CONTRIBUTING_SPRITES.md) (**checked 2026-11-04**).

The repository's contribution guidance explicitly addresses missing/corrupt/wrongly sized images and cosmetic-form auditing. Its documentation does not guarantee complete shiny, gender, back, or form coverage. No Pokémon GO-specific family is documented in the inspected repository index; **HOME is not a GO asset set**. Sources: [contribution guide](https://github.com/PokeAPI/sprites/blob/master/CONTRIBUTING_SPRITES.md), [README index](https://github.com/PokeAPI/sprites/blob/master/README.md) (**checked 2026-11-04**).

### Published usage statements and other sources

| Source | Published statement | Documented coverage / unresolved rights |
|---|---|---|
| [PokeAPI/sprites licence](https://github.com/PokeAPI/sprites/blob/master/LICENCE.txt) | Declares image contents copyright The Pokémon Company, then distributes the repository under CC0 1.0. | Rights-holder permission for unrestricted Pokémon-art reuse is **UNVERIFIED**. **Checked 2026-11-04.** |
| [Smogon sprite repository](https://github.com/smogon/sprites#license), [Showdown sprite index](https://play.pokemonshowdown.com/sprites/) | Repository code is MIT; Pokémon art belongs to Nintendo/Game Freak/The Pokémon Company. For community B&W sprites, the README says licensing is still being determined and asks users to contact them first. | The public index includes colored `gen4`, `gen5`, `ani`, shiny and back families. Unrestricted reuse permission is **UNVERIFIED**. **Checked 2026-11-04.** |
| [Pokémon Database gallery](https://pokemondb.net/sprites), [Pikachu gallery](https://pokemondb.net/sprites/pikachu), [usage FAQ](https://pokemondb.net/about) | Galleries include GO images, forms and costumes. The site permits saving/rehosting sprites or asks hotlinkers to use its linking code. Its FAQ describes artwork/sprites as others' creations used under fair use. | The FAQ says no public database/API is provided. Rights-holder authorization for reuse is **UNVERIFIED** despite the site's own usage statement. **Checked 2026-11-04.** |

Noncommercial hobby use alone is **not a confirmed blanket permission** from these sources. Rights-holder authorization for this bot's redistribution of Pokémon art remains **UNVERIFIED**.

## Recommendations

### V1 selection and fallback

Use static HGSS PNGs for an explicitly audited roster. Prefer a coherent art family and restrict encounter eligibility to supported forms; do not promise every National Dex species in v1. Treat exact shiny appearance as part of correctness.

Resolve an asset from `(species_id, pokemon_id, form_key, gender, shiny, view, style_revision)` using a generated manifest. Keep numeric data IDs distinct from filename keys. Start with API-returned sprite URLs where available, then reviewed explicit form mappings; never assume a missing URL is a valid path.

Apply the following fallback **without changing the creature's identity**:

1. Exact HGSS form, required gender appearance, shiny state and view.
2. Exact identity in the reviewed default/Gen V pixel-art family.
3. Exact identity in an approved modern family, such as HOME. When only a front image exists, deliberately use a front-view layout and label the style/view fallback.
4. Original neutral placeholder with the species/form name and explicit shiny indicator; record the missing asset for repair.

A gender-neutral image is acceptable only when the manifest establishes no relevant visual difference. A missing female asset is not evidence that the male image is interchangeable. A shiny request must never silently fall back to normal colors, and a form request must never silently become the base form. Do not synthesize shiny palettes by hue rotation or represent a mirrored front sprite as a genuine back sprite.

For gym scenes, prefer two front sprites when an authentic back is unavailable; make orientation a layout decision. Show the sparkle badge and text “Shiny” from stored encounter/catch state independently of the image. Asset availability does not decide shiny eligibility or odds.

### Other-source tradeoffs and provenance

**Recommendation:** Keep PokéAPI as the primary machine-readable source. Showdown/Smogon is useful for later-species pixel art and animation, but requires name/form mapping and resolution of its community-sprite terms. Pokémon Database is useful for visual comparison and manually reviewed GO/costume gaps; its lack of a public API makes it a poor automated ingestion dependency. Verify the applicable usage statement for every selected asset family.

Preseed only the approved roster. Before activation, verify successful download, decodability, transparency, dimensions, expected frame behavior and checksum. Record source URL, upstream commit/version, author/credits where supplied, usage statement, identity key, and fallback choice. Keep cache misses out of the live interaction path; serve the placeholder and repair asynchronously. Pixel-art scaling and scene caching are covered in [Discord rendering](discord-rendering.md).
