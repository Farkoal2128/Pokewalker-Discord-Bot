# Pokéwalker walking and encounter loop

Research task 1 · **Checked 2026-11-04** · Non-commercial hobby fan project.

Read this summary first; open the topic files only as needed. **Facts** describe the original device or documented APIs. **Recommendations** are proposed bot rules, not approved requirements. **UNVERIFIED** marks unresolved evidence. CP, candy amounts, item probabilities and gyms remain separate research tasks.

## Facts: key findings and numbers

| Finding | Evidence, checked 2026-11-04 |
| --- | --- |
| **20 steps → 1 W; Radar 10 W; dowsing 3 W.** Walking-only equivalents are **200** and **60 steps per attempt**, not guaranteed rewards. | [Nintendo booklet][N]; arithmetic from those costs |
| **27 routes:** two defaults, 18 banked-watt unlocks, seven special unlocks. | [Route catalogue][R]; all gates in [mechanics](mechanics.md) |
| **3 caught Pokémon, 3 found items, 10 peer gifts.** The three catches are completed captures, not pending encounters. | [Nintendo operations manual][O] |
| Original captures are **shiny-locked**; this bot's shinies are an intentional extension. | [PKHeX's generation documentation][P] |

Source policy: prefer Grinberg's demonstrated gameplay analysis; supplement gaps with Nintendo manuals and specialist research. Conflicting introductory watt wording and peer-overflow arithmetic are documented in [mechanics](mechanics.md). [Grinberg][D]; checked 2026-11-04.

## Recommendations: v1 baseline

- **Characters:** five eligible characters per chat step; filtered messages, duplicate suppression, cooldown and rate caps. Proposed **100 awarded steps per encounter** gives about **1/day for the casual scenario and 7/day for the active scenario** in [adaptation](adaptation.md), assuming the queue is cleared.
- **Three unresolved encounters**, including the active one; no expiry. When full, keep credited steps for progression and freeze encounter progress without accumulating encounter debt. Collection capacity is separate.
- **No spendable watts.** Keep steps as progress; let the separate GO-style resource design govern power-ups.
- **Two personal route choices** within server policy; explicit bot rarity weights, with original physical-step tables retained only as historical reference.
- **Private reveal and catch**, with optional preparation; save encounter identity and shiny outcome when queued. Resume the same result/state through `/walker` after interruption.
- Add dowsing after item policies exist; peer visits and exact battle replication come later. Retain the decided quiet ❗ notification and one-of-each rare-item constraint.

## Open decisions and evidence gaps

**Product decisions:** accept/tune the proposed step economy; server-local versus global collection ownership; catch/flee probabilities, ball supply and shiny/lure probabilities; item-search cadence. Historical numbers are not defaults for these systems.

**UNVERIFIED:** exact Radar bush deadlines, exact peer-overflow watts, conflicting Jirachi provenance requirements, and some route-table discrepancies. See the local caveats before implementing any historical rule. Discord interaction-token expiry does not expire an encounter.

## Files

| File | Contents |
| --- | --- |
| [mechanics.md](mechanics.md) | Steps/watts, all 27 unlocks, capacities, event log, peers, sleep and pacing |
| [minigames.md](minigames.md) | Radar battle/catch odds, dowsing, proposed short button flows |
| [routes-encounters.md](routes-encounters.md) | Species-ID schema, two example routes, selection semantics and full-table links |
| [adaptation.md](adaptation.md) | All Part B recommendations, anti-farming assumptions, queue invariants and priorities |

[N]: https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/DS_Pokemon_HeartGold
[O]: https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/Pokewalker_Tri
[R]: https://pokemondb.net/heartgold-soulsilver/pokewalker
[P]: https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Legality/RNG/PIDType.cs
[D]: https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker
