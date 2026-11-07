# PokéAPI forms, flags and Candy families

**Checked: 2026-11-04.** Scope: the full roster in a reproducible PokéAPI content build, extending [pokeapi-data.md](pokeapi-data.md). This is research, not an approved change to requirements or a runtime implementation. D37, D38 and D40 refer to the owner's brief for this document; thresholds and Candy prices quoted from that brief are bot rules, not PokéAPI facts.

## Summary

- **Roster:** the inspected master snapshot contains **1,025 species**, **1,351 Pokémon varieties** and **1,579 forms**. Default species plus ordinary regional forms give **1,082 encounter identities** before unresolved nonregional additions: **1,025 + 57**. [Species][species], [Pokémon][pokemon], [forms][forms] — checked 2026-11-04; computed.
- **Classification:** all **224 multi-variety species / 326 nondefault varieties** are covered below. There are **31 species with remaining stat/type-different varieties**, plus form-only type differences for Arceus and Silvally. Their encounter/change policy remains an owner decision. [Pokémon][pokemon], [forms][forms], [stats][stats], [types][types], [form types][formtypes] — checked 2026-11-04; computed.
- **Flag traps:** species-variety default and form default have different scopes. Eternamax has `is_battle_only=0`; all Minior forms also have that flag cleared. A flag-only filter is insufficient. [Forms][forms], [serializer][schema] — checked 2026-11-04.
- **Rarity:** **71 species are Legendary, 23 Mythical**, with no overlap. Ultra Beasts and most Paradox Pokémon have neither flag. Conditional D38 counts and assumptions are in G. [Species][species] — checked 2026-11-04; computed.
- **Families:** use chain ID for shared Candy, genuine species-parent edges for depth, and form-aware recipes for legal evolutions. Family **250** contains Phione and Manaphy without an evolution between them. [Species][species], [evolution details][evolution], [serializer][schema] — checked 2026-11-04.
- **Recommendation:** pin `e5b79b2e15d7c50735a945936afd4cd1cfd94eae` (master commit dated **2026-11-02**), and review changes before rebuilding content. The latest published release is **2.9.0**, published **2025-01-31**; both have 1,025 species, but master has later forms and corrections. [Release][release], [master ref][masterref] — checked 2026-11-04.
- **Open decisions:** nonregional mechanical forms; Minior cores; gender/form identity; species versus form-specific stages; “two-member” versus “two-stage” Candy costs; unsupported evolution items; Shedinja's special route. The final sections provide exact filtering and family/stage pseudocode with these choices explicit.

## Facts

### A. Species → varieties → forms

Sources for this subsection: [API documentation][docs], [pinned models][models], [pinned serializer][schema], [Pokémon][pokemon], [forms][forms], [form types][formtypes] — checked **2026-11-04**.

| Resource / field | Meaning for ingestion |
|---|---|
| `pokemon-species` | Species identity, Legendary/Mythical flags, `evolution_chain`, `evolves_from_species`, and `varieties[]`. |
| `varieties[].pokemon` → `pokemon` | Variety identity, six base stats, types, abilities and `forms[]`. The adjacent `varieties[].is_default` selects the species' default Pokémon variety. |
| `pokemon-form.is_default` | Default form **within its Pokémon variety**, not default variety of the whole species. |
| `pokemon-form.is_battle_only`, `is_mega` | Form-level flags. They are not fields on `pokemon-species`; false does not establish eligibility under D37. |
| `pokemon-form.form_name` | Descriptor such as `alola`, `galar-standard`, `mega-x`; source CSV field is `form_identifier`. It is not a closed enum. |
| Names / suffixes | `-gmax`, `-primal`, `-totem`, `-alola` are useful audited patterns; no `is_regional` or `is_cosmetic` boolean exists. Substring matching alone confuses `alola-cap` with a regional form. |
| Form types / stats | Forms share parent Pokémon stats. Form-specific type rows override parent types; otherwise the serializer falls back to parent Pokémon types. Compare the six-stat vector and types, not BST alone. |
| `trigger_conditions` | Ability/item/move/Gigantamax form-change metadata. This is not an exclusion flag: default Aegislash Shield, Wishiwashi Solo and Minior Meteor also have ability-trigger conditions. |

Every species has exactly one default Pokémon in this pin. Its ID happens to equal its species ID, but these remain separate namespaces. Eight nondefault Koraidon/Miraidon traversal varieties have **no** default-form flag. No selected species-default form is battle-flagged. [Species][species], [Pokémon][pokemon], [forms][forms], [form conditions][conditions] — checked 2026-11-04; computed.

#### A1. Representative records and all non-Mega/Gmax battle-change groups

IDs here are **Pokémon IDs**, except explicitly marked form IDs. `B` = `is_battle_only`; `M` = `is_mega`. These are observed data classifications; D37 filtering is specified under Recommendations. Sources: [Pokémon][pokemon], [forms][forms], [form conditions][conditions], [stats][stats], [types][types] — checked **2026-11-04**.

| Category | Default / ordinary identity | Alternative data and classification |
|---|---|---|
| Mega | Venusaur `3` | `10033 venusaur-mega`: B1/M1. All 97 Mega varieties have these flags. |
| Primal | Kyogre `382`; Groudon `383` | `10077 kyogre-primal`, `10078 groudon-primal`: B1/M0. |
| Gigantamax | Charizard `6` | `10196 charizard-gmax`: B1/M0; all 34 Gmax varieties are battle-flagged. |
| Eternamax | Eternatus `890` | `10190 eternatus-eternamax`, form `10359`: **B0/M0**. The false flag does not settle the transformation's D37 treatment. |
| Totem | Alolan Raticate `10092`; Alolan Marowak `10115` | `10093 raticate-totem-alola`, `10149 marowak-totem`: stat/type-equivalent to those regional counterparts; separate size/status identities. |
| Pikachu costumes/caps | Pikachu `25` | Cosplay/costumes `10080–10085`; caps `10094–10099`, `10148`, `10160`: equal stats/types. `10099 pikachu-alola-cap` is not an Alolan regional variety. |
| Let's Go partners | Pikachu `25`; Eevee `133` | `10158 pikachu-starter`, `10159 eevee-starter`: B0, **different stats**; distinct from cap cosmetics. |
| Ash-Greninja | Greninja `658` | `10116 greninja-battle-bond` has equal stats/types; `10117 greninja-ash` is B1. |
| Castform | `351 castform` | `10013 sunny`, `10014 rainy`, `10015 snowy`: B1, different types. |
| Cherrim | Pokémon `421`, form `421 cherrim-overcast` | Form `10038 cherrim-sunshine`: B1, under the **same Pokémon**. |
| Aegislash | `681 aegislash-shield` | `10026 aegislash-blade`: B1. |
| Darmanitan | `555 darmanitan-standard`; `10177 darmanitan-galar-standard` | `10017 darmanitan-zen`, `10178 darmanitan-galar-zen`: B1. |
| Meloetta | `648 meloetta-aria` | `10018 meloetta-pirouette`: B1. |
| Wishiwashi | `746 wishiwashi-solo` | `10127 wishiwashi-school`: B1. |
| Minior | `774 minior-red-meteor` | Other Meteor colours have equal stats/types; cores `10136–10142` differ. **All 14 forms are B0**; reciprocal Shields Down conditions exist. |
| Mimikyu | `778 mimikyu-disguised` | `10143 mimikyu-busted`, `10145 mimikyu-totem-busted`: B1; `10144 totem-disguised` is a stat/type-equivalent Totem duplicate. |
| Zygarde | `718 zygarde-50` | Complete `10120`: B1; Mega `10301`: B1/M1. 10% / Power Construct alternatives are classified in C. |
| Necrozma | `800 necrozma` | Ultra `10157`: B1; Dusk `10155` / Dawn `10156` are B0 mechanical alternatives. |
| Cramorant | `845 cramorant` | Gulping `10182`, Gorging `10183`: B1. |
| Eiscue | `875 eiscue-ice` | Noice `10185`: B1. |
| Morpeko | `877 morpeko-full-belly` | Hangry `10187`: B1 despite equal stats/types. |
| Crowned legends | Zacian `888`; Zamazenta `889` | Crowned `10188`, `10189`: B1; already covered by D37's battle-form exclusion. |
| Palafin | `964 palafin-zero` | Hero `10256`: B1. |
| Terapagos | `1024 terapagos` | Terastal `10276`, Stellar `10277`: B1. |
| Xerneas | Pokémon `716`, **form `10132 xerneas-neutral`** | Form `716 xerneas-active`: B1. Form and Pokémon IDs must not be interchanged. |
| Ogerpon | `1017 ogerpon` | Masks `10273–10275`: B0, different types. No separate Tera-mask rows are represented in this pin. |
| Koraidon / Miraidon | `1007` / `1008`; default form names `apex-build` / `ultimate-mode` | Traversal alternatives `10264–10267` / `10268–10271`: B0, equal stats/types, no default-form flag on those eight varieties. |

**Limitations:** Minior's Shields Down transition is confirmed by the [official Pokédex](https://www.pokemon.com/uk/pokedex/minior) and [form conditions][conditions]; outside-battle Core persistence was not independently confirmed from a primary gameplay source in this pass (**UNVERIFIED**). The source does not label cores battle-only. Eternamax's false flag is a confirmed data observation; exact player-availability mechanics are **UNVERIFIED** here. Its named exclusion is a recommendation under D37 below. Checked 2026-11-04.

### B. Complete ordinary regional-form roster

There are **57 regional varieties across 54 species**: Alola **18**, Galar **19**, Hisui **16**, Paldea **4**. These are nondefault Pokémon varieties with ordinary regional descriptors, after removing Totem and battle transformations. Source: [Pokémon][pokemon] joined to [forms][forms] and [species][species] — checked **2026-11-04**; computed. Region is the descriptor's region, not the species' generation.

| Species ID | Pokémon variety ID | Exact Pokémon name | Region |
|---:|---:|---|---|
| 19 | 10091 | `rattata-alola` | Alola |
| 20 | 10092 | `raticate-alola` | Alola |
| 26 | 10100 | `raichu-alola` | Alola |
| 27 | 10101 | `sandshrew-alola` | Alola |
| 28 | 10102 | `sandslash-alola` | Alola |
| 37 | 10103 | `vulpix-alola` | Alola |
| 38 | 10104 | `ninetales-alola` | Alola |
| 50 | 10105 | `diglett-alola` | Alola |
| 51 | 10106 | `dugtrio-alola` | Alola |
| 52 | 10107 | `meowth-alola` | Alola |
| 53 | 10108 | `persian-alola` | Alola |
| 74 | 10109 | `geodude-alola` | Alola |
| 75 | 10110 | `graveler-alola` | Alola |
| 76 | 10111 | `golem-alola` | Alola |
| 88 | 10112 | `grimer-alola` | Alola |
| 89 | 10113 | `muk-alola` | Alola |
| 103 | 10114 | `exeggutor-alola` | Alola |
| 105 | 10115 | `marowak-alola` | Alola |
| 52 | 10161 | `meowth-galar` | Galar |
| 77 | 10162 | `ponyta-galar` | Galar |
| 78 | 10163 | `rapidash-galar` | Galar |
| 79 | 10164 | `slowpoke-galar` | Galar |
| 80 | 10165 | `slowbro-galar` | Galar |
| 83 | 10166 | `farfetchd-galar` | Galar |
| 110 | 10167 | `weezing-galar` | Galar |
| 122 | 10168 | `mr-mime-galar` | Galar |
| 144 | 10169 | `articuno-galar` | Galar |
| 145 | 10170 | `zapdos-galar` | Galar |
| 146 | 10171 | `moltres-galar` | Galar |
| 199 | 10172 | `slowking-galar` | Galar |
| 222 | 10173 | `corsola-galar` | Galar |
| 263 | 10174 | `zigzagoon-galar` | Galar |
| 264 | 10175 | `linoone-galar` | Galar |
| 554 | 10176 | `darumaka-galar` | Galar |
| 555 | 10177 | `darmanitan-galar-standard` | Galar |
| 562 | 10179 | `yamask-galar` | Galar |
| 618 | 10180 | `stunfisk-galar` | Galar |
| 58 | 10229 | `growlithe-hisui` | Hisui |
| 59 | 10230 | `arcanine-hisui` | Hisui |
| 100 | 10231 | `voltorb-hisui` | Hisui |
| 101 | 10232 | `electrode-hisui` | Hisui |
| 157 | 10233 | `typhlosion-hisui` | Hisui |
| 211 | 10234 | `qwilfish-hisui` | Hisui |
| 215 | 10235 | `sneasel-hisui` | Hisui |
| 503 | 10236 | `samurott-hisui` | Hisui |
| 549 | 10237 | `lilligant-hisui` | Hisui |
| 570 | 10238 | `zorua-hisui` | Hisui |
| 571 | 10239 | `zoroark-hisui` | Hisui |
| 628 | 10240 | `braviary-hisui` | Hisui |
| 705 | 10241 | `sliggoo-hisui` | Hisui |
| 706 | 10242 | `goodra-hisui` | Hisui |
| 713 | 10243 | `avalugg-hisui` | Hisui |
| 724 | 10244 | `decidueye-hisui` | Hisui |
| 128 | 10250 | `tauros-paldea-combat-breed` | Paldea |
| 128 | 10251 | `tauros-paldea-blaze-breed` | Paldea |
| 128 | 10252 | `tauros-paldea-aqua-breed` | Paldea |
| 194 | 10253 | `wooper-paldea` | Paldea |

All three Paldean Tauros breeds are distinct ordinary regional encounters under D37. Galarian Darmanitan **Standard** is included in this regional roster; Zen `10178` is battle-flagged. Alolan Totem duplicates `10093` and `10149` are not additional regionals. White-striped Basculin is not named/flagged Hisuian in this model. [Pokémon][pokemon], [forms][forms] — checked 2026-11-04.

Regional forms that evolve into new species share their original species' Candy family: Galarian Meowth→Perrserker **863**, Farfetch'd→Sirfetch'd **865**, Corsola→Cursola **864**, Linoone→Obstagoon **862**, Mr. Mime→Mr. Rime **866**, Yamask→Runerigus **867**; Hisuian Qwilfish→Overqwil **904**, Sneasel→Sneasler **903**; Paldean Wooper→Clodsire **980**. These targets are species defaults, not additional regional forms. [Species][species], [evolution details][evolution], [forms][forms] — checked 2026-11-04. E explains source-form routing.

### C. Exhaustive nonregional variety classification

Classification compares **all six base stats and effective types**. “Equivalent” below means cosmetic-equivalent for those two measures, **not proof of identical abilities, moves or evolution behavior**. Battle flags take precedence over numeric similarity. Sources: [Pokémon][pokemon], [forms][forms], [stats][stats], [types][types], [form types][formtypes] — checked **2026-11-04**.

#### C1. Stat/type-different persistent or unresolved groups

Exactly **31 species / 57 nondefault Pokémon varieties** remain after regional, Mega, Primal, Gmax, battle-flagged, Eternamax and Totem categories. `S` = different stat vector; `T` = different types. This table makes no encounter or form-change policy choice; the per-group options are under Recommendations.

| Species (ID), default variety | Nondefault Pokémon IDs/names | Difference |
|---|---|---|
| pikachu (25), `pikachu` | `10158 pikachu-starter` | S |
| eevee (133), `eevee` | `10159 eevee-starter` | S |
| deoxys (386), `deoxys-normal` | `10001 deoxys-attack`, `10002 deoxys-defense`, `10003 deoxys-speed` | S |
| wormadam (413), `wormadam-plant` | `10004 wormadam-sandy`, `10005 wormadam-trash` | ST |
| rotom (479), `rotom` | `10008 rotom-heat`, `10009 rotom-wash`, `10010 rotom-frost`, `10011 rotom-fan`, `10012 rotom-mow` | ST |
| dialga (483), `dialga` | `10245 dialga-origin` | S |
| palkia (484), `palkia` | `10246 palkia-origin` | S |
| giratina (487), `giratina-altered` | `10007 giratina-origin` | S |
| shaymin (492), `shaymin-land` | `10006 shaymin-sky` | ST |
| tornadus (641), `tornadus-incarnate` | `10019 tornadus-therian` | S |
| thundurus (642), `thundurus-incarnate` | `10020 thundurus-therian` | S |
| landorus (645), `landorus-incarnate` | `10021 landorus-therian` | S |
| kyurem (646), `kyurem` | `10022 kyurem-black`, `10023 kyurem-white` | S |
| floette (670), `floette` | `10061 floette-eternal` | S |
| pumpkaboo (710), `pumpkaboo-average` | `10027 pumpkaboo-small`, `10028 pumpkaboo-large`, `10029 pumpkaboo-super` | S |
| gourgeist (711), `gourgeist-average` | `10030 gourgeist-small`, `10031 gourgeist-large`, `10032 gourgeist-super` | S |
| zygarde (718), `zygarde-50` | `10118 zygarde-10-power-construct`, `10181 zygarde-10` | S |
| hoopa (720), `hoopa` | `10086 hoopa-unbound` | ST |
| oricorio (741), `oricorio-baile` | `10123 oricorio-pom-pom`, `10124 oricorio-pau`, `10125 oricorio-sensu` | T |
| lycanroc (745), `lycanroc-midday` | `10126 lycanroc-midnight`, `10152 lycanroc-dusk` | S |
| minior (774), `minior-red-meteor` | `10136 minior-red`, `10137 minior-orange`, `10138 minior-yellow`, `10139 minior-green`, `10140 minior-blue`, `10141 minior-indigo`, `10142 minior-violet` | S |
| necrozma (800), `necrozma` | `10155 necrozma-dusk`, `10156 necrozma-dawn` | ST |
| indeedee (876), `indeedee-male` | `10186 indeedee-female` | S |
| urshifu (892), `urshifu-single-strike` | `10191 urshifu-rapid-strike` | T |
| calyrex (898), `calyrex` | `10193 calyrex-ice`, `10194 calyrex-shadow` | ST |
| ursaluna (901), `ursaluna` | `10272 ursaluna-bloodmoon` | S |
| basculegion (902), `basculegion-male` | `10248 basculegion-female` | S |
| enamorus (905), `enamorus-incarnate` | `10249 enamorus-therian` | S |
| oinkologne (916), `oinkologne-male` | `10254 oinkologne-female` | S |
| gimmighoul (999), `gimmighoul` | `10263 gimmighoul-roaming` | S |
| ogerpon (1017), `ogerpon` | `10273 ogerpon-wellspring-mask`, `10274 ogerpon-hearthflame-mask`, `10275 ogerpon-cornerstone-mask` | T |

#### C2. Stat/type-equivalent groups

Exactly **17 species / 45 nondefault varieties** remain in this category. Sources: [Pokémon][pokemon], [stats][stats], [types][types], [abilities][abilities] — checked **2026-11-04**. Ability caveats were compared; move behavior was not exhaustively audited.

| Species | Alternatives (Pokémon IDs) | Classification caveat |
|---|---|---|
| Pikachu 25 | Rock Star 10080, Belle 10081, Pop Star 10082, PhD 10083, Libre 10084, Cosplay 10085; Original 10094, Hoenn 10095, Sinnoh 10096, Unova 10097, Kalos 10098, Alola 10099, Partner 10148, World 10160 caps | Cosmetic-equivalent. Costume move/evolution restrictions are not implied by stats equality |
| Basculin 550 | Blue 10016, White 10247 | Equal stats/types; differing abilities; White form matters to Basculegion evolution. **Not safely “pure cosmetic.”** Not named Hisuian/regional in data |
| Keldeo 647 | Resolute 10024 | Cosmetic-equivalent; form trigger references move 548 |
| Greninja 658 | Battle Bond 10116 | Ability-only special variety; Ash 10117 separately excluded |
| Meowstic 678 | Female 10025 | Gender art, same stats/types; hidden ability differs (Prankster/Competitive). Unlike Indeedee/Basculegion/Oinkologne, not stat-different |
| Zygarde 718 | 50% Power Construct 10119 | Ability-only variety; 10% variants belong in stat-different table; Complete excluded |
| Rockruff 744 | Own Tempo 10151 | Ability-only variety tied to evolution; Dusk Lycanroc routing depends on it |
| Minior 774 | Orange 10130, Yellow 10131, Green 10132, Blue 10133, Indigo 10134, Violet 10135 Meteor | Colour-only duplicate shell stats; cores separately discussed |
| Magearna 801 | Original Colour 10147 | Cosmetic-equivalent; both newer Mega forms are excluded |
| Toxtricity 849 | Low Key 10184 | Equal stats/types; ordinary ability slot differs (Plus/Minus); both Gmax varieties excluded |
| Zarude 893 | Dada 10192 | Cosmetic-equivalent |
| Maushold 925 | Family of Three 10257 | Cosmetic-equivalent count/appearance |
| Squawkabilly 931 | Blue 10260, Yellow 10261, White 10262 | Equal stats/types; Yellow/White hidden ability differs from Green/Blue (Sheer Force/Guts) |
| Tatsugiri 978 | Droopy 10258, Stretchy 10259 | Equal stats/types/abilities; move-related behavior not audited; all three Mega forms excluded |
| Dudunsparce 982 | Three Segment 10255 | Cosmetic-equivalent length |
| Koraidon 1007 | Limited 10264, Sprinting 10265, Swimming 10266, Gliding 10267 | Cosmetic-equivalent/noncombat traversal modes; form-default anomaly |
| Miraidon 1008 | Low Power 10268, Drive 10269, Aquatic 10270, Glide 10271 | Cosmetic-equivalent/noncombat traversal modes; form-default anomaly |

The other **11 non-battle-flagged Totem varieties** are stat/type-equivalent to their ordinary counterparts: `10093 raticate-totem-alola`, `10121 gumshoos-totem`, `10122 vikavolt-totem`, `10128 lurantis-totem`, `10129 salazzle-totem`, `10144 mimikyu-totem-disguised`, `10146 kommo-o-totem`, `10149 marowak-totem`, `10150 ribombee-totem`, `10153 araquanid-totem`, `10154 togedemaru-totem`. Mimikyu Totem Busted `10145` is already in the battle category. [Pokémon][pokemon], [forms][forms], [stats][stats], [types][types] — checked 2026-11-04.

#### C3. Form-only differences a varieties-only scan misses

Sources for every row: [forms][forms], [form types][formtypes], [form conditions][conditions], [serializer][schema] — checked **2026-11-04**.

| Group | Classification / model finding |
|---|---|
| Arceus **493** | One Pokémon, **19 forms**: 18 ordinary type identities plus legacy `arceus-unknown`, form **10057**. Same parent stats; alternate types are form-level overrides. |
| Silvally **773** | One Pokémon, **18 type forms**; alternate form IDs **10232–10248**. Same parent stats; form-level type overrides. |
| Cherrim **421**, Xerneas **716** | Battle-only alternatives are form rows within the default Pokémon, as shown in A1. |
| Genesect **649** | Four Drive alternatives retain Bug/Steel and the same stats. Drive/move semantics are outside that comparison. |
| Pichu 172, Unown 201, Burmy 412, Mothim 414, Shellos 422, Gastrodon 423, Deerling 585, Sawsbuck 586, Frillish 592, Jellicent 593, Scatterbug 664, Spewpa 665, Vivillon 666, Flabébé 669, Florges 671, Furfrou 676, Sinistea 854, Polteageist 855, Poltchageist 1012, Sinistcha 1013 | Form-only alternatives share parent stats/types and have battle flag 0. Some still carry evolution meaning, including Burmy cloaks and tea authenticity. |
| Pyroar **668**, Floette **670**, Alcremie **869** | Cosmetic form-only appearances also exist within their default Pokémon, independently of additional Mega/Gmax/stat varieties. |

#### C4. Coverage ledger, including generic transformation-only species

The following precedence partition covers every nondefault Pokémon exactly once. Species can appear in multiple categories; the species union is **224**, with no missing multi-variety species. Sources: [Pokémon][pokemon], [forms][forms], [stats][stats], [types][types] — checked **2026-11-04**; computed.

| Category, in precedence order | Nondefault varieties |
|---|---:|
| Mega | 97 |
| Gigantamax | 34 |
| Primal | 2 |
| Other battle-flagged | 22 |
| Eternamax semantic exception | 1 |
| Ordinary regional | 57 |
| Remaining Totem duplicates | 11 |
| Other stat/type-different | 57 |
| Other stat/type-equivalent | 45 |
| **Total** | **326** |

**Mega: 87 species / 97 varieties (battle-only classification).** 3 venusaur, 6 charizard, 9 blastoise, 15 beedrill, 18 pidgeot, 26 raichu, 36 clefable, 65 alakazam, 71 victreebel, 80 slowbro, 94 gengar, 115 kangaskhan, 121 starmie, 127 pinsir, 130 gyarados, 142 aerodactyl, 149 dragonite, 150 mewtwo, 154 meganium, 160 feraligatr, 181 ampharos, 208 steelix, 212 scizor, 214 heracross, 227 skarmory, 229 houndoom, 248 tyranitar, 254 sceptile, 257 blaziken, 260 swampert, 282 gardevoir, 302 sableye, 303 mawile, 306 aggron, 308 medicham, 310 manectric, 319 sharpedo, 323 camerupt, 334 altaria, 354 banette, 358 chimecho, 359 absol, 362 glalie, 373 salamence, 376 metagross, 380 latias, 381 latios, 384 rayquaza, 398 staraptor, 428 lopunny, 445 garchomp, 448 lucario, 460 abomasnow, 475 gallade, 478 froslass, 485 heatran, 491 darkrai, 500 emboar, 530 excadrill, 531 audino, 545 scolipede, 560 scrafty, 604 eelektross, 609 chandelure, 623 golurk, 652 chesnaught, 655 delphox, 658 greninja, 668 pyroar, 670 floette, 678 meowstic, 687 malamar, 689 barbaracle, 691 dragalge, 701 hawlucha, 718 zygarde, 719 diancie, 740 crabominable, 768 golisopod, 780 drampa, 801 magearna, 807 zeraora, 870 falinks, 952 scovillain, 970 glimmora, 978 tatsugiri, 998 baxcalibur.

**Gigantamax: 32 species / 34 varieties (battle-only classification).** 3 venusaur, 6 charizard, 9 blastoise, 12 butterfree, 25 pikachu, 52 meowth, 68 machamp, 94 gengar, 99 kingler, 131 lapras, 133 eevee, 143 snorlax, 569 garbodor, 809 melmetal, 812 rillaboom, 815 cinderace, 818 inteleon, 823 corviknight, 826 orbeetle, 834 drednaw, 839 coalossal, 841 flapple, 842 appletun, 844 sandaconda, 849 toxtricity, 851 centiskorch, 858 hatterene, 861 grimmsnarl, 869 alcremie, 879 copperajah, 884 duraludon, 892 urshifu.

These generic transformation rosters, A1, B, C1, C2 and the Totem list jointly cover every multi-variety species. [Pokémon][pokemon], [forms][forms] — checked 2026-11-04; union validated.

### D. Exact Legendary and Mythical flags

These lists are **species IDs and exact API names**, not a fan taxonomy. The pin has **71 `is_legendary=true`**, **23 `is_mythical=true`**, no overlap. All other species have both flags false. Varieties inherit their species' classification. Source for every entry: [species table][species] — checked **2026-11-04**; complete boolean-column scan.

#### Legendary — 71 species

| Generation in source | Species ID and name |
|---|---|
| 1 | **144** articuno; **145** zapdos; **146** moltres; **150** mewtwo |
| 2 | **243** raikou; **244** entei; **245** suicune; **249** lugia; **250** ho-oh |
| 3 | **377** regirock; **378** regice; **379** registeel; **380** latias; **381** latios; **382** kyogre; **383** groudon; **384** rayquaza |
| 4 | **480** uxie; **481** mesprit; **482** azelf; **483** dialga; **484** palkia; **485** heatran; **486** regigigas; **487** giratina; **488** cresselia |
| 5 | **638** cobalion; **639** terrakion; **640** virizion; **641** tornadus; **642** thundurus; **643** reshiram; **644** zekrom; **645** landorus; **646** kyurem |
| 6 | **716** xerneas; **717** yveltal; **718** zygarde |
| 7 | **772** type-null; **773** silvally; **785** tapu-koko; **786** tapu-lele; **787** tapu-bulu; **788** tapu-fini; **789** cosmog; **790** cosmoem; **791** solgaleo; **792** lunala; **800** necrozma |
| 8 | **888** zacian; **889** zamazenta; **890** eternatus; **891** kubfu; **892** urshifu; **894** regieleki; **895** regidrago; **896** glastrier; **897** spectrier; **898** calyrex; **905** enamorus |
| 9 | **1001** wo-chien; **1002** chien-pao; **1003** ting-lu; **1004** chi-yu; **1007** koraidon; **1008** miraidon; **1014** okidogi; **1015** munkidori; **1016** fezandipiti; **1017** ogerpon; **1024** terapagos |

#### Mythical — 23 species

| Generation in source | Species ID and name |
|---|---|
| 1 | **151** mew |
| 2 | **251** celebi |
| 3 | **385** jirachi; **386** deoxys |
| 4 | **489** phione; **490** manaphy; **491** darkrai; **492** shaymin; **493** arceus |
| 5 | **494** victini; **647** keldeo; **648** meloetta; **649** genesect |
| 6 | **719** diancie; **720** hoopa; **721** volcanion |
| 7 | **801** magearna; **802** marshadow; **807** zeraora; **808** meltan; **809** melmetal |
| 8 | **893** zarude |
| 9 | **1025** pecharunt |

#### Requested category cross-check

The group labels below are lookup labels; the species schema provides the two booleans, not `is_ultra_beast`, `is_paradox` or a sub-Legendary category. Sources: [species table][species], [models][models]; [taxonomy issue #1034](https://github.com/PokeAPI/pokeapi/issues/1034) — checked **2026-11-04**. Each row reports the actual flags for the listed IDs.

| Group / species | Legendary | Mythical | D38 consequence |
|---|---|---|---|
| Ultra Beasts: 793 Nihilego, 794 Buzzwole, 795 Pheromosa, 796 Xurkitree, 797 Celesteela, 798 Kartana, 799 Guzzlord, 803 Poipole, 804 Naganadel, 805 Stakataka, 806 Blacephalon | False | False | Ordinary stage/BST rules; Poipole/Naganadel are not Legendary through these flags. |
| Paradox: 984–995, 1005 Roaring Moon, 1006 Iron Valiant, 1009 Walking Wake, 1010 Iron Leaves, 1020 Gouging Fire, 1021 Raging Bolt, 1022 Iron Boulder, 1023 Iron Crown | False | False | Ordinary stage/BST rules, including legendary-looking relatives. |
| 1007 Koraidon; 1008 Miraidon | True | False | Legendary override. |
| 772 Type: Null; 773 Silvally | True | False | Legendary override. |
| 789 Cosmog; 790 Cosmoem; 791 Solgaleo; 792 Lunala | True | False | Entire family, including weak pre-evolutions, receives the override. |
| 891 Kubfu; 892 Urshifu | True | False | Both receive the override. |
| 808 Meltan; 809 Melmetal | False | True | Mythical override. |
| Loyal Three: 1014 Okidogi; 1015 Munkidori; 1016 Fezandipiti | True | False | Legendary override. |
| 1025 Pecharunt | False | True | Mythical override. |

“Sub-Legendary” must not be inferred as a third boolean: species commonly grouped that way, such as the legendary birds/beasts, still simply have `is_legendary=true`. Likewise Ultra Beast and Paradox are not synonyms for either stored flag. [Species][species], [models][models] — checked 2026-11-04.

### E. Evolution chains, stages and recipes

#### E1. Family and stage representation

- `pokemon_species.csv` supplies `evolution_chain_id` and `evolves_from_species_id`; `evolution-chain` presents species links with `evolves_to` and incoming `evolution_details`. Evolution conditions belong to a species edge; their `party_species` and `trade_species` are requirements, not parent/child relationships. The pin has **1,025 species**, **540 chain IDs**, **484 genuine parent edges**, and **676 condition records covering all 484 evolved species**. Every referenced parent exists and belongs to the same family. Maximum parent depth is **2**. [Species CSV][species], [evolution CSV][evolution], [serializer][schema] — checked 2026-11-04; counts computed from these files.
- Important exception: **Phione 489 and Manaphy 490 share family 250, but both have null parents and no evolution records**. They share a Candy family if D40 follows chain IDs literally; they do not have a genuine evolution edge in the source species data. The pinned serializer starts with Phione and attaches an unmatched later member to the initial root, producing misleading Phione→Manaphy nesting with empty evolution details. The nested tree therefore disagrees with the genuine parent graph in this one family. [Species CSV][species], [serializer `build_evolution_tree`][schema] — checked 2026-11-04.
- `baby_trigger_item` is a **breeding** condition, not an evolution-item requirement. An `is_baby` flag does not define all roots; most roots are not babies. National ID or generation ordering cannot determine stage. [Official evolution documentation][docs], [chain CSV][chains] — checked 2026-11-04.

| Family ID | Actual shape (root depth 0) | Implication |
|---:|---|---|
| 67 | Eevee → eight depth-1 evolutions | Nine species but only two stages; “two-member” is not “two-stage.” |
| 47 | Tyrogue → Hitmonlee / Hitmonchan / Hitmontop | All targets are depth 1, despite earlier National IDs for two targets. |
| 135 | Wurmple → Silcoon → Beautifly; Wurmple → Cascoon → Dustox | Both branches share one family and each has depths 0/1/2. |
| 10 | Pichu → Pikachu → Raichu | Later-added baby is the root; Pikachu depth 1. |
| 90 | Azurill → Marill → Azumarill | Later-added baby is the root; Marill depth 1. |
| 72 | Munchlax → Snorlax | Two actual members, depths 0/1. |
| 144 | Nincada → Ninjask; Nincada → Shedinja | Shedinja is a depth-1 sibling, trigger `shed`; it is not evolved from Ninjask. |
| 299 and 312 | Karrablast → Escavalier; Shelmet → Accelgor | Separate families. Reciprocal `trade_species` conditions must not merge them. |
| 442 | Applin → Flapple / Appletun / Dipplin → Hydrapple | One family has depth-1 final branches and a depth-2 final branch. |
| 250 | Phione; Manaphy (two roots) | Shared family ID without an evolution; explicit tree-validation exception. |

Table source: [species CSV][species] and [evolution CSV][evolution] — checked 2026-11-04; shape/depth computed.

#### E2. Current evolution-detail schema and regional routes

The **exact API names** are `required_pokemon_form` and `evolved_pokemon_form` (not `required_form`/`evolved_form`). Version and region metadata are now present. The pinned models expressly define null `required_pokemon_form` as unrestricted by form, null `evolved_pokemon_form` as the target default form, and null `region` as unrestricted by region. Nonetheless many ordinary historical routes retain null required form alongside specific regional routes. Literal wildcard application can expose unwanted ordinary targets to a regional source. [Models][models], [serializer][schema], [evolution CSV][evolution] — checked 2026-11-04.

| Source identity | Pinned target identity / distinguishing metadata |
|---|---|
| Ordinary Meowth / Alolan Meowth / Galarian Meowth | Persian / Alolan Persian / Perrserker; regional sources explicitly named. |
| Ordinary Wooper / Paldean Wooper | Quagsire / Clodsire. |
| Galarian Farfetch’d, Mr. Mime, Corsola, Linoone, Yamask | Sirfetch’d, Mr. Rime, Cursola, Obstagoon, Runerigus respectively. |
| Hisuian Qwilfish / Sneasel | Overqwil / Sneasler. |
| White-striped Basculin | Basculegion male or female; red/blue-striped sources are not specified. |
| Ordinary Rockruff / Own Tempo Rockruff | Midday or midnight Lycanroc / dusk Lycanroc. Own Tempo matters to evolution identity despite identical stats/types. |
| Burmy cloaks | Required cloak selects Wormadam cloak; generic Burmy→Mothim has null required form. |
| Pikachu, Exeggcute, Cubone | Ordinary and Alolan targets use separate rows; regional target rows carry Alola region. |
| Quilava, Dewott, Petilil, Rufflet, Goomy, Bergmite, Dartrix | Hisuian Typhlosion, Samurott, Lilligant, Braviary, Sliggoo, Avalugg, Decidueye have distinct target-form records and Hisui region. |
| Koffing / Mime Jr. | Galarian Weezing / Galarian Mr. Mime have Galar-region target records. |

Table source: [evolution CSV][evolution], joined to [forms CSV][forms] and [species CSV][species] — checked 2026-11-04. Audit of the 57 regional varieties (excluding cap/Totem/Zen): all **25 regional sources whose species has children** have explicit matching-source `is_default=1` evolution records.

`is_default` on an evolution **record** is distinct from species-variety or Pokémon-form default flags. It marks an expected evolution method; distinct form/target branches can each have a default method. Historical methods coexist: e.g. Leafeon’s old special-rock records are non-default, while Leaf Stone is default; Urshifu’s towers are non-default while the two scroll items are default. Taking the first row or indiscriminately retaining every historical method changes the bot’s item rules. [Evolution CSV][evolution], [official docs][docs] — checked 2026-11-04.

#### E3. Complete trigger and condition catalog

| IDs | Trigger identifiers | Examples / item implications |
|---|---|---|
| 1, 2, 3 | `level-up`, `trade`, `use-item` | Level-up/trade can also require held items; inspect both `item` and `held_item`. |
| 4, 5 | `shed`, `spin` | Shedinja; Alcremie (spin records also require a held sweet). |
| 6, 7 | `tower-of-darkness`, `tower-of-waters` | Urshifu historical methods. |
| 8, 9 | `three-critical-hits`, `take-damage` | Sirfetch’d; Runerigus. |
| 10, 11, 12 | `in-battle-level-up`, `agile-style-move`, `strong-style-move` | Maushold; Wyrdeer; historical Overqwil method. |
| 13, 14 | `recoil-damage`, `use-move` | Basculegion; Annihilape and an Overqwil method. |
| 15, 16, 17 | `three-defeated-bisharp`, `gimmighoul-coins`, `meltan-candies` | Kingambit; Gholdengo; Melmetal. The last trigger does not supply a bot Candy-cost field. |
| 18 | `unclassified` | Catalog entry; no evolution rows use it at this pin. |

[Trigger CSV][evotriggers], [evolution CSV][evolution] — checked 2026-11-04. There are 18 trigger identifiers, 17 used.

Complete current API condition/metadata fields:

- Identity/history: `version_group`, `is_default`, `region`, `required_pokemon_form`, `evolved_pokemon_form`.
- Event/items: `trigger`, `item`, `held_item`.
- Ordinary gates: `gender`, `location`, `min_level`, `known_move`, `known_move_type`, `min_happiness`, `min_beauty`, `min_affection`, `relative_physical_stats`, `time_of_day`, `party_species`, `party_type`, `trade_species`, `needs_overworld_rain`, `turn_upside_down`, `needs_multiplayer`, `near_special_rock`.
- Newer gates: `used_move`, `min_move_count`, `min_steps`, `min_damage_taken`, `allowed_natures`, `condition_expression`.
- `condition_expression` contains `expression`, `percentage_chance`, `variables`. It is RPN, not Python/JavaScript. The four variable symbols are `EC`, `PID`, `SPIN_DIR`, `SPIN_SEC`; current expression-bearing targets are Silcoon, Cascoon, Alcremie, Maushold, Dudunsparce. CSV `nature_bitmask` is exposed as `allowed_natures`; percentage is nested in the API expression object. Time values present: `day`, `night`, `dusk`, `full-moon`.

[Serializer][schema], [models][models], [evolution CSV][evolution], [variables CSV][variables] — checked 2026-11-04. These are main-series condition fields, not bot levels, rewards or rates.

#### E4. The seven supported evolution items

| Bot item | PokéAPI item ID | Main-series evolution records in this pin |
|---|---:|---|
| Sun Stone | 80 | Gloom→Bellossom; Sunkern→Sunflora; Cottonee→Whimsicott; Petilil→ordinary/Hisuian Lilligant; Helioptile→Heliolisk (`item`, use-item). |
| King’s Rock | 198 | Poliwhirl→Politoed; ordinary Slowpoke→Slowking (`held_item`, trade). Galarian Slowking instead uses Galarica Wreath. |
| Metal Coat | 210 | Onix→Steelix; Scyther→Scizor (`held_item`, trade). |
| Dragon Scale | 212 | Seadra→Kingdra (`held_item`, trade). |
| Up-Grade | 229 | Porygon→Porygon2 (`held_item`, trade). |
| Sinnoh Stone | Absent | No identifier/recipe in the pinned item or evolution tables. |
| Unova Stone | Absent | No identifier/recipe in the pinned item or evolution tables. |

[Items CSV][items], [evolution CSV][evolution] — checked 2026-11-04. These are **PokéAPI/main-series mappings**, not a complete Pokémon GO recipe table. A GO-style Sinnoh/Unova mapping cannot be mechanically inferred from this source; the exact GO-style recipes are **UNVERIFIED** in this research scope.

Other main-series evolution requirements include Fire/Water/Thunder/Leaf/Ice Stones, Galarica Cuff/Wreath, Black Augurite, Peat Block, scrolls, armors, teacups, sweets and Metal Alloy. These are outside the brief's seven-item list. [Items][items], [evolution details][evolution] — checked 2026-11-04. Their bot treatment is unresolved under Recommendations.

### F. Completeness, releases and upstream issues

#### F1. Release versus inspected master

Counts come from the committed CSVs, not a live endpoint's pagination count. Sources: [latest release metadata][releasemeta], [tag target][releasetag], [master ref][masterref], [release commit][releasecommit], [master commit][mastercommit], [release CSV directory][releasecsv], [pinned CSV directory][pincsv] — checked **2026-11-04**.

| Snapshot | Full commit | Date | Species / highest species ID | Pokémon / forms |
|---|---|---|---:|---:|
| Latest published release **2.9.0** | `41c48560b317ce91020c18cddb44adedb13a576d` | Published **2025-01-31**; commit **2025-01-23** | **1,025 / 1,025** | **1,304 / 1,527** |
| Master observed on check date | `e5b79b2e15d7c50735a945936afd4cd1cfd94eae` | Commit **2026-11-02** | **1,025 / 1,025** | **1,351 / 1,579** |

Both snapshots contain all Gen IX DLC species **1011–1025**: Dipplin, Poltchageist, Sinistcha, the Loyal Three and Ogerpon; Archaludon, Hydrapple, Gouging Fire, Raging Bolt, Iron Boulder, Iron Crown and Terapagos; epilogue Mythical Pecharunt. Thus Kitakami/Blueberry roster coverage is present, including **1024 Terapagos** and **1025 Pecharunt**. This does not establish complete moves, locations or evolution methods. [Release species][releasespecies], [pinned species][species] — checked 2026-11-04.

Master contains version groups **30 `legends-za`, 31 `mega-dimension`, 32 `champions`** (version IDs 47–49), and no species beyond 1025. It includes later Mega forms such as Greninja, Zygarde and Raichu X/Y, excluded by D37. Relevant additions: [Lumiose Megas, 2025-10-15](https://github.com/PokeAPI/pokeapi/commit/7dfbf5bf6cb965a4d4cd3781d44cb6d997b7eacf), [Hyperspace Megas, 2025-12-10](https://github.com/PokeAPI/pokeapi/commit/b369a1c44ab9343fb41ed18e076453235e1f3884), [form follow-up, 2026-01-19](https://github.com/PokeAPI/pokeapi/commit/8a8ef7b41444070e56a5f73d43a74a856dba32df), [Champions learnsets, 2026-06-24](https://github.com/PokeAPI/pokeapi/commit/286d7a071bc50ec4a57e3f3f506a13220ce6f903). [Version groups][versiongroups], [versions][versions], [Pokémon][pokemon] — checked 2026-11-04. Exhaustive correctness against every later game through this date remains **UNVERIFIED**; version presence is not completeness certification.

Post-release corrections include [Bloodmoon Ursaluna's nondefault variety flag, 2025-08-06](https://github.com/PokeAPI/pokeapi/commit/ba182fef0cb347d2c561c219e5af3c5888e287fd), [Ultra Necrozma's battle flag, 2026-07-26](https://github.com/PokeAPI/pokeapi/commit/b519bb02e18f90d57c8689319de34176299fd454), and [all Minior battle flags cleared, 2026-08-18](https://github.com/PokeAPI/pokeapi/commit/8413a0ae609dd9186bc428221d2e10ea4db76e42). These are merged changes, not current open defects. Checked 2026-11-04.

#### F2. Relevant open issue register

All issue states were checked **open on 2026-11-04** via GitHub. An issue is evidence of a report/discussion, not proof that current data is incorrect.

| Issue | Confirmed relevance / limitation |
|---|---|
| [#1700: Runerigus Z-A evolution](https://github.com/PokeAPI/pokeapi/issues/1700) | Pinned evolution data has only Runerigus row 459, version group 20, source form 10338, damage 49; no Z-A row. This narrower omission is confirmed. Exact Z-A gameplay condition remains independently **UNVERIFIED**. |
| [#1026: species/form attributes](https://github.com/PokeAPI/pokeapi/issues/1026) | Regional evolution-model discussion. Current master already has form-aware evolution fields; do not repeat the old issue as proof they are absent. |
| [#563: Magearna grouping](https://github.com/PokeAPI/pokeapi/issues/563) | Cosmetic Original Color is a separate Pokémon variety. Variety count is not a count of mechanical forms. |
| [#1568: multiple defaults](https://github.com/PokeAPI/pokeapi/issues/1568) | Default-scope discussion; species-variety default and form default differ. |
| [#1280: Xerneas default](https://github.com/PokeAPI/pokeapi/issues/1280) | Interpretation dispute. The pin has Active form 716 nondefault/B1 and Neutral form 10132 default/B0. |
| [#1685: form type schema](https://github.com/PokeAPI/pokeapi/issues/1685) | Schema-cleanup proposal; not evidence that all form types are wrong. |
| [#1034: subcategories](https://github.com/PokeAPI/pokeapi/issues/1034) | Two booleans do not encode every legendary/Ultra Beast/Paradox taxonomy. |

Pinned checks for the concrete rows: [evolution details][evolution], [forms][forms] — checked 2026-11-04. Targeted issue searches did not establish a specific current base-stat error; **UNVERIFIED** whether every stat/type entry is correct. Public REST/GraphQL deployment parity with either inspected Git commit is also **UNVERIFIED**.

### G. Conditional D38 tier sanity check

**Computed scenario, not a settled interpretation of ambiguous owner rules.** Use all 1,025 default identities and 57 regionals; omit pending C additions. Give every parentless species (including a singleton) the base role; non-root with children = middle; non-root leaf = final. Apply flags first, then `BST ≥ 500`, then final/middle/base. Use the species-parent graph for every variety, even where legal form routes differ. BST is the sum of that Pokémon variety's six current base stats. Sources: [species][species], [Pokémon][pokemon], [stats][stats], [forms][forms]; D38 thresholds from the owner's brief — checked **2026-11-04**; independently recomputed.

| Baseline set | Common | Uncommon | Rare | Legendary/Mythical | Total |
|---|---:|---:|---:|---:|---:|
| Default species | 328 | 192 | 411 | 94 | 1,025 |
| Added regional forms | 17 | 12 | 25 | 3 | 57 |
| **Combined** | **345** | **204** | **436** | **97** | **1,082** |

The combined flagged bucket is **74 Legendary + 23 Mythical profiles**; the three additions are the Galarian birds. If parentless singletons instead count as final, the same roster becomes **336 Common / 137 Uncommon / 512 Rare / 97 flagged**: 76 profiles move into Rare. Neither table is an encounter-rate recommendation. [Species][species], [stats][stats], [forms][forms] — checked 2026-11-04; computed under the stated alternatives.

| Sanity case | Result in the stated scenario |
|---|---|
| Pichu 205 / Azurill 190 / Munchlax 390 BST | Base-stage babies → Common. Later National IDs do not determine stage. |
| Shuckle 505 BST; Duraludon 535 BST | Rare through BST, even though Shuckle is single-stage and Duraludon is now a base stage. |
| Shedinja 236 BST | Rare as a non-root final, despite low BST and special evolution semantics. |
| Wishiwashi Solo 175 BST | Common as a singleton/base; excluded School form 620 BST must not supply its tier or CP inputs. |
| Cosmog 200 / Cosmoem 400 BST | Both flagged Legendary before stage/BST logic. |
| Poipole 420 / Naganadel 540 BST | Uncommon / Rare, with neither legendary flag. |
| Ordinary and Galarian Linoone 420 BST; Mr. Mime 460 BST | Species topology calls both varieties middle/Uncommon; legal form topology would make ordinary Linoone/Mr. Mime final/Rare. |
| Minior Meteor 440 / Core 500 BST | Default Meteor Uncommon; a separately approved core would be Rare. Core is not in these totals. |

Sources for every row: [species][species], [Pokémon][pokemon], [stats][stats], [evolution details][evolution] — checked 2026-11-04; classifications derived from the scenario above.

[species]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_species.csv
[pokemon]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon.csv
[forms]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_forms.csv
[stats]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_stats.csv
[types]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_types.csv
[formtypes]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_form_types.csv
[abilities]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_abilities.csv
[conditions]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_form_conditions.csv
[formtriggers]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_form_triggers.csv
[evolution]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/pokemon_evolution.csv
[chains]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/evolution_chains.csv
[evotriggers]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/evolution_triggers.csv
[items]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/items.csv
[variables]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/evolution_variables.csv
[versiongroups]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/version_groups.csv
[versions]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv/versions.csv
[models]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/pokemon_v2/models.py
[schema]: https://github.com/PokeAPI/pokeapi/blob/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/pokemon_v2/serializers.py

[docs]: https://pokeapi.co/docs/v2
[release]: https://github.com/PokeAPI/pokeapi/releases/tag/2.9.0
[releasemeta]: https://api.github.com/repos/PokeAPI/pokeapi/releases/latest
[releasetag]: https://api.github.com/repos/PokeAPI/pokeapi/git/ref/tags/2.9.0
[releasecommit]: https://github.com/PokeAPI/pokeapi/commit/41c48560b317ce91020c18cddb44adedb13a576d
[mastercommit]: https://github.com/PokeAPI/pokeapi/commit/e5b79b2e15d7c50735a945936afd4cd1cfd94eae
[masterref]: https://api.github.com/repos/PokeAPI/pokeapi/branches/master
[releasecsv]: https://github.com/PokeAPI/pokeapi/tree/41c48560b317ce91020c18cddb44adedb13a576d/data/v2/csv
[pincsv]: https://github.com/PokeAPI/pokeapi/tree/e5b79b2e15d7c50735a945936afd4cd1cfd94eae/data/v2/csv
[releasespecies]: https://github.com/PokeAPI/pokeapi/blob/41c48560b317ce91020c18cddb44adedb13a576d/data/v2/csv/pokemon_species.csv

## Recommendations — importer policy, not upstream facts

### 1. Preserve the owner's nonregional-form choices

For **each** stat/type-different group below, expose the same explicit policy choices. None is selected by this research:

- **E — Separate encounters:** retain the alternative's exact Pokémon/form IDs and stats/types; authored encounter weights are a separate decision.
- **D — Default only:** keep the species default as the only encounter identity; the alternative remains documented as excluded by owner policy.
- **H — Owned form change:** catch an approved base identity, then change it using a separately defined item/command rule. Preserve instance identity and Candy family. This does not add an evolution stage.
- **H\* — Custom owned conversion:** same implementation option, but changing a sex/size/starter/unique identity would be a bot invention, not a claim about a canonical held-item mechanic.

| Stat/type-different group from C | Available owner choices |
|---|---|
| Partner Pikachu | E / D / H* |
| Partner Eevee | E / D / H* |
| Deoxys | E / D / H |
| Wormadam cloaks | E / D / H* |
| Rotom appliances | E / D / H |
| Dialga Origin | E / D / H |
| Palkia Origin | E / D / H |
| Giratina Origin | E / D / H |
| Shaymin Sky | E / D / H |
| Tornadus Therian | E / D / H |
| Thundurus Therian | E / D / H |
| Landorus Therian | E / D / H |
| Kyurem fusions | E / D / H |
| Eternal Flower Floette | E / D / H* |
| Pumpkaboo sizes | E / D / H* |
| Gourgeist sizes | E / D / H* |
| Zygarde 10% | E / D / H |
| Hoopa Unbound | E / D / H |
| Oricorio styles | E / D / H |
| Lycanroc forms | E / D / H* |
| Minior cores | E / D / H, after interpreting D37's transformation exclusion |
| Necrozma fusions | E / D / H |
| Indeedee gender varieties | E / D / H* |
| Urshifu styles | E / D / H* |
| Calyrex riders | E / D / H |
| Bloodmoon Ursaluna | E / D / H* |
| Basculegion gender varieties | E / D / H* |
| Enamorus Therian | E / D / H |
| Oinkologne gender varieties | E / D / H* |
| Roaming Gimmighoul | E / D / H* |
| Ogerpon masks | E / D / H |
| Arceus ordinary type forms | E / D / H |
| Silvally type forms | E / D / H |

For fusions, H also needs companion-possession/consumption/reversibility rules. For gender varieties, specify whether rolled gender selects a mechanical identity or whether all instances use default stats/art. For typed forms/masks/appliances, form-change items are separate from the seven **evolution** items. Do not infer recipes or consumption from the label H.

For equal-stat/type groups, collapse appearance only when the approved bot model ignores the differing behavior. Preserve source-form provenance and form-conditioned evolution routes. White Basculin and Own Tempo Rockruff must not silently become ordinary Basculin/Rockruff for evolution. A form's appearance can be collapsed without discarding its evolution identity; whether to retain those owned identities remains an owner choice.

### 2. Pinning and build checks

Pin the full master SHA **`e5b79b2e15d7c50735a945936afd4cd1cfd94eae`**, using every related table and serializer/schema interpretation from that commit. Record the source SHA, file hashes, importer version, exception/policy version and bot balance version in the generated content manifest. Never mix a release species table with master forms or live API evolution responses.

On an explicit update, resolve the upstream ref once, fetch that immutable commit, and review a diff of IDs/names, both default scopes, transformation flags, stats/types, Legendary/Mythical flags, parents/families, required/target forms, evolution methods/items and condition schema. Publish a new content artifact atomically after approval; gameplay continues to use its installed snapshot.

Build assertions should verify: one species-default variety; one default form for every **included** variety; complete six-stat/type data; all foreign keys resolve; every variety/form is classified; no parent cycles or cross-family edges; every genuine species edge has source evolution details; each candidate bot recipe is approved or explicitly pending/excluded. No unsupported types or unresolved item/form decisions become runtime routes. Compare the snapshot's count report with the previous version. Counts are review signals, not universal constants.

Keep named exceptions short: Eternamax's exclusion; Phione/Manaphy family 250; unsupported legacy Arceus Unknown; Minior's unresolved transformation interpretation. Automatically report evolution/form dependencies and unexpected data instead of maintaining a giant hand-picked encounter allowlist. The C policy matrix reflects real product choices, not failures a better name regex can resolve.

### 3. D40 recipe conversion and ambiguous stages

Use chain ID for shared Candy. Use species-parent depth for a reproducible baseline, while storing both `evolution_depth` and role so the owner can choose species-level or form-specific rarity. Never use National ID, generation, `is_baby`, number of varieties, or BST to compute evolution depth.

Recommend canonical `evolution_details.is_default=true` methods before dropping gates. Retain all distinct source/target identities; then remove D40's non-item gameplay conditions. This avoids historical special-rock/tower methods bypassing modern items. Store original version/region metadata for audit. Null source-form rules need the regional safeguard in the final algorithm; this is an explicit bot policy for this pin, not a reinterpretation of upstream null semantics.

| Source requirement | Proposed D40 treatment |
|---|---|
| Level, happiness/beauty/affection, gender, time/weather/location/region, known/used moves, party/trade partner, nature/random expressions, counters, walking/spin/critical-hit/damage/action triggers | Remove the gameplay gate after resolving source/target identity; Candy-only if no item requirement remains. Recommend player choice among retained branch targets. |
| `item` or `held_item` = one of the five present supported items in E4 | Keep that item alongside Candy. Consume a held evolution item directly; do not implement trading merely to use it. |
| Unsupported item, including sweets/scrolls/armors/ordinary stones | Leave recipe unresolved until the owner chooses retention, an explicit mapping, or Candy-only conversion. D40's “non-item” clause does not decide it. |
| Sinnoh / Unova Stone | Require a separately sourced or owner-authored recipe mapping; neither can be inferred from PokéAPI. |
| `shed` | Keep the genuine Nincada→Shedinja edge in research; ask the owner to choose direct evolution, bonus creation, or catch-only before generating a runtime recipe. |
| Required/evolved form, parent edge, family, canonical-method selector | Preserve identity/structure. These are not gameplay gates to erase. |

Under a **literal two-member-family interpretation**, count distinct species in the chain: a genuine edge in a two-species family costs **50 Candy**; other depth 0→1 edges cost **25**, depth 1→2 edges **100**. Thus Eevee's nine-species/two-stage family would cost 25 per branch. These are D40-derived consequences, not a chosen balance recommendation. The owner must settle “two-member” versus “two-stage”; Phione/Manaphy gains no edge under either interpretation.

### 4. Exact filter — plain-language pseudocode

1. **Load one pinned graph.** Join species, Pokémon varieties and forms through their foreign keys. Keep `species_id`, `pokemon_id` and `form_id` distinct. For each species require exactly one variety marked species-default; resolve its form default separately. For a variety that will be included, missing/duplicate form defaults are build errors. Do not select the lowest ID.
2. **Filter individual forms first.** A form is excluded when `is_mega` or `is_battle_only` is true. Also exclude transformation descriptors/names with a whole `mega` token or terminal `gmax`, `primal`, `eternamax` token; record Eternamax Pokémon 10190/form 10359 as the known false-flag exception. Check all patterns against the pinned classification, and require review for a new pattern. Reject Totem-token duplicates before regional matching. A battle alternative does not reject its parent Pokémon's ordinary form.
3. **Validate default coverage.** Keep each species' default variety/default form if it survives step 2. An excluded/missing species default is an error requiring a documented resolution, not permission to substitute a different form. This retains Cherrim Overcast, Xerneas Neutral, Aegislash Shield, Wishiwashi Solo, Palafin Zero, Terapagos Normal and Minior Red Meteor. Do not exclude forms merely because they have a trigger condition.
4. **Add ordinary regionals.** First inspect surviving forms of nondefault varieties for an exact `form_name` in `{alola, galar, hisui, paldea, galar-standard, paldea-combat-breed, paldea-blaze-breed, paldea-aqua-breed}`. For each matching variety, require the matching form to be its unique default form; include it once. Unmatched varieties, including the eight traversal alternatives without defaults, continue to classification. Region-name substrings alone never qualify: Pikachu `alola-cap` stays out; Totem Alolan duplicates and Galarian Zen were removed earlier. This step adds 57 identities and step 3 adds 1,025 in this pin.
5. **Classify everything remaining.** Compare its six parent stats and effective form types with the species default, including form-only overrides. Stat/type-different alternatives go to the C owner-policy registry. Type identifiers outside the approved ordinary type set are quarantined, specifically Arceus Unknown form 10057. Equal stats/types go to the cosmetic-equivalent group plus a dependency report for differing abilities/moves and required/target evolution forms; equality alone does not authorize losing those dependencies.
6. **Apply only explicit policy.** For a C group with E, add approved alternative encounter identities; with D, keep default-only; with H/H*, keep approved encounters and generate separately approved owned-form-change rules. With no decision, output `PENDING OWNER POLICY` and no alternative encounter/change route. For ordinary cosmetics, use default appearance per D37 while retaining any required evolution provenance. Minior cores remain explicitly pending; do not relabel them battle-flagged or replace the Meteor default.
7. **Emit and validate.** Deduplicate by approved Pokémon/form identity, inherit species flags and Candy-family ID, compute stats/BST from that exact identity, and produce an included/excluded/pending report. The baseline expected count is 1,082; C choices can change it. Stop content promotion for new unclassified forms or unresolved rules needed by the selected scope. No live data request is part of play.

### 5. Family, stage and evolution algorithm — plain-language pseudocode

1. **Build families.** For every species, read its evolution-chain ID and optional `evolves_from_species`. Group by chain ID. Index children only from genuine non-null species-parent references. Validate parent existence, same-family membership and absence of cycles. Do not create edges from `party_species`, `trade_species` or breeding `baby_trigger_item`.
2. **Validate chain trees.** Compare API `evolves_to` links against those parent references and associated evolution details. Require details for every genuine edge. Document family 250 as two roots, Phione 489 and Manaphy 490, with no connecting edge; ignore its serializer-generated empty-detail nesting. A new inconsistency requires review.
3. **Compute depth.** Assign every root depth 0, each child parent-depth + 1, independent of National ID or generation. Record parent/child presence. For the provisional G interpretation, root/singleton=base, non-root with children=middle, non-root leaf=final. If the owner chooses form-specific stages, build the approved form-route graph first and recompute roles; do not mix topology choices in one count.
4. **Assign D38 tier.** Test Legendary/Mythical species flags first. Otherwise Rare if the selected identity's BST ≥ 500 or its chosen role is final; otherwise Uncommon if middle or base with BST 400–499; otherwise Common for base BST < 400. Tier is not a substitute for evolution depth or a Candy price.
5. **Resolve legal identities before stripping gates.** For each genuine edge, inspect canonical default-method details. An explicit `required_pokemon_form` must match the source; an explicit `evolved_pokemon_form` fixes the target; a null target selects that target species' default. Preserve ordinary→regional targets. For regional source varieties, use explicit matching-source canonical records only on this pin; do not also inherit old null-source ordinary routes. All 25 relevant regional sources currently have such records; absence after an update is a review failure. Do not apply this regional shortcut to all other forms: generic Burmy→Mothim legitimately coexists with cloak-specific Wormadam routes.
6. **Preserve form dependencies.** A white-striped-Basculin-only route does not make red Basculin evolve into Basculegion; an Own-Tempo route does not make ordinary Rockruff evolve into Dusk. If source/target form policy is unresolved or excluded, report the unavailable route rather than substituting defaults. Every target species can still be caught through its D37 default encounter.
7. **Convert approved recipes.** Retain structural identity, family and item requirements; discard the D40 non-item gates as in recommendation 3. Deduplicate identical resulting source/target/item recipes and, if approved, let players choose branches. Apply the confirmed family-size/stage Candy formula; unresolved supported-item mappings, unsupported items or `shed` behavior stay pending. Never evaluate the source condition expression as executable code.

### Owner decisions this research cannot settle

1. **Choose E/D/H per C1 group and Arceus/Silvally** using the complete matrix above; no choice was made here. Fusion partners, reversibility and form-change items need rules if H is selected.
2. **Interpret Minior under D37:** Meteor-only encounters, separate cores, or an owned form change; literal battle flags do not settle it.
3. **Set gender and equivalent-form semantics:** how gender chooses stats/art for Indeedee/Basculegion/Oinkologne; how cosmetic collapse retains White Basculin, Own Tempo Rockruff, Burmy/tea form identities and other ability/move distinctions.
4. **Choose D38 stage topology and singleton precedence:** species graph or legal form graph; parentless singletons as base or final. G is conditional until this is settled.
5. **Clarify D40 pricing and branches:** exactly two species versus two stages, including Eevee/Tyrogue/Slowpoke and mixed-depth Applin; whether the player chooses targets after condition removal.
6. **Resolve item coverage:** unsupported main-series evolution items and explicit Sinnoh/Unova recipes. These cannot be deduced from the seven-item list.
7. **Choose Shedinja behavior:** selectable evolution, bonus creation, or catch-only. Shared family and depth do not determine that transaction.
