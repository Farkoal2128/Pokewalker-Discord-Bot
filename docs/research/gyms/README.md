# Per-server gym research

**Checked: 2026-11-04.** Task 3 research and proposed v1 settings. Builds on [task 2's CP/resource model](../go-systems/README.md) unchanged. These notes do not approve implementation or a game-data import; the planned external research review remains open.

## Facts — key findings and numbers

- GO gyms hold **6 defenders**, limited to **1 per Trainer** and **1 per species**. [Official gym help](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1171-battling-at-gyms/), checked 2026-11-04.
- Defender coins are paid **on return**, capped at **50 per Trainer/day across gyms**. The community rate is **1 coin/10 minutes**; **8 h 20 min** reaches 50, derived. [Official cap](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1172-earning-the-defender-bonus/), [community rate](https://www.serebii.net/pokemongo/gyms.shtml), checked 2026-11-04.
- GO has changed Gym/Raid damage, energy and attack durations. Exact current motivation curves, AI delays and dodge windows are **UNVERIFIED** here; older empirical models are labeled historical. [Official battle update](https://pokemongo.com/news/battle-systems-update), checked 2026-11-04.
- **Move data is mode-specific:** GO distinguishes Gym/Raid and Trainer Battle energy costs; PokéAPI's documented moves lack GO PvE fields. PvPoke targets PvP. [Official attack help](https://scopelyexplore.helpshift.com/hc/en/5-pokemon-go/faq/1160-fast-attacks-charged-attacks/), [PokéAPI schema](https://pokeapi.co/docs/v2), [PvPoke](https://github.com/pvpoke/pvpoke), checked 2026-11-04.
- Dataset availability does not establish unrestricted reuse. [PokeMiners' notice](https://github.com/PokeMiners/game_masters) and [PoGoAPI's terms](https://pogoapi.net/Legal/) leave redistribution permission **UNVERIFIED** in this review; software licenses and third-party game material are distinguished. Checked 2026-11-04.

## Recommendations — proposed v1 scope

All numbers below are **bot defaults requiring playtesting**, not GO rules.

| Area | Recommendation |
|---|---|
| Ownership | Individual holders; **1 defender/gym**, **1 held gym/player/server**, **3 deployments/player globally** |
| Configuration | Admin-managed names, themes and explicit access channels; proposed service cap **10 gyms/server** |
| Battles | Fully simulated; **1–3 attackers**; choose party/order and clear-only or post-win defender; **3–6 setup interactions**, or **2** with saved choices, derived |
| Stats / moves | Preserve task 2's CP and canonical stats; small, versioned **bot-balanced** fast/charged roster; no bulk data import |
| Fatigue | Server dates with **100 awarded steps** qualify; count completed dates after deployment day; return after **5**, with a **7-real-day** backstop |
| Battle condition | Fatigue reduces starting defender HP, not stored CP; no persistent damage or healing costs |
| Rewards | **50 Stardust/player/earning day globally** after **200 same-server awarded steps** plus eligible participation; no win/holding-time bonus; no Star Piece multiplier |
| Abuse limits | **10-minute** battle cooldown, **5 starts/day globally**; **24-hour** same-gym reclaim delay; shared account/activity eligibility |
| Recovery | Frozen snapshots, reserved claim capacity, atomic settlement; **120 ticks** yields a draw, **60-second** processing expiry aborts/refunds |
| Display | Private preview/result image plus accessible text and saved move log |

Defer fixed/custom teams, raids, gym berry feeding, healing, Photo Disc drops, coins and reward-bearing badges. Existing Candy, item, rare-item and storage rules remain unchanged.

## Read only the file needed

| File | Coverage |
|---|---|
| [go-gym-mechanics.md](go-gym-mechanics.md) | A1–A5: control, motivation, battle model, rewards and raids |
| [move-data-sources.md](move-data-sources.md) | A6: PvE/PvP sources, licenses/terms, provenance and normalized fields |
| [discord-gym-design.md](discord-gym-design.md) | B1–B2, B5, B7–B8: administration, ownership, fatigue/rewards, abuse and schema |
| [battle-system.md](battle-system.md) | B3–B4, B6: simulation versus turns, action policy, concurrency and visuals |

## Open decisions

Confirm global collection ownership across tasks; approve the launch move/form roster and source policy; test small-server turnover, newcomer matchups, activity thresholds and reward affordability. Individual holders and the custom move model are recommendations. Confirm these choices before requirements/contracts; raids need a separate later design.
