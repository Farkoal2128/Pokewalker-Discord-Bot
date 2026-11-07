# Original Pokéwalker: walking, routes, storage and peers

Scope: A1, A2, A6–A8. **Facts** describe HGSS; **derived pacing** is arithmetic, not a claim about designer intent. All source checks below were made **2026-11-04**. Bot recommendations are in [adaptation.md](adaptation.md).

## Facts — steps and watts (A1)

- **20 recorded steps earn 1 W.** Radar costs **10 W** per search; dowsing costs **3 W** per search. Unspent watts transferred to HGSS accumulate toward route unlocks. [Nintendo HGSS booklet, printed pp. 32, 34, 37–38; checked 2026-11-04][HG].
- **Counters:** daily steps reset at midnight and record at most **99,999**; watts can accrue beyond that. The wallet ceiling is **9,999 W**, not a daily allowance. A separate daily watt-earning ceiling is **UNVERIFIED**. [Bulbapedia, Gameplay/Trivia; checked 2026-11-04][BP].
- **Source discrepancy:** Grinberg's introduction implies 1 W/step without demonstrating that conversion. Nintendo explicitly specifies **20:1**, used here. [Grinberg, User-facing features; checked 2026-11-04][DG].

## Facts — route selection and complete catalog (A2)

Choose the companion and route in HGSS at stroll start. “Receive a gift” transfers catches, items and watts; “Return from a Stroll” also retrieves the companion. [Nintendo HGSS booklet, printed pp. 32–34; checked 2026-11-04][HG].

There are **27 routes: 2 defaults, 18 watt-threshold routes, 7 special unlocks**. Watt thresholds refer to the cumulative total transferred into HGSS, not the device wallet or an individual day's earnings. Unlocking does not subtract the threshold. The documented unlock process reveals at most one eligible route at a time; guides differ on whether every gift-only sync qualifies, so that edge case is **UNVERIFIED**. [Pokémon Database, route catalog][DB]; [PLDH, Watts/Courses][PLDH]; [Bulbapedia, Areas][BP] — checked 2026-11-04.

**Normal routes:** W = cumulative transferred watts; “National Dex” is an additional requirement, not another payment. Source for every row: [Pokémon Database][DB], checked **2026-11-04**; corroborated by [PLDH][PLDH].

| Route | W threshold | Additional gate |
|---|---:|---|
| Refreshing Field | 0 | Default |
| Noisy Forest | 0 | Default |
| Rugged Road | 50 | — |
| Beautiful Beach | 200 | — |
| Suburban Area | 500 | — |
| Dim Cave | 1,000 | — |
| Blue Lake | 2,000 | — |
| Town Outskirts | 3,000 | — |
| Hoenn Field | 5,000 | National Dex |
| Warm Beach | 7,500 | National Dex |
| Volcano Path | 10,000 | National Dex |
| Treehouse | 15,000 | National Dex |
| Scary Cave | 20,000 | National Dex |
| Sinnoh Field | 25,000 | National Dex |
| Icy Mountain Rd. | 30,000 | National Dex |
| Big Forest | 40,000 | National Dex |
| White Lake | 50,000 | National Dex |
| Stormy Beach | 65,000 | National Dex |
| Resort | 80,000 | National Dex |
| Quiet Cave | 100,000 | National Dex |

**Special routes:** separate unlock conditions, not higher watt milestones. Every linked route source was checked **2026-11-04**. “Event” below describes the historical distribution method, not a currently offered download.

| Route | Historical unlock condition | Source |
|---|---|---|
| Beyond the Sea | Receive a foreign Pokémon through the GTS | [Route article][SEA] |
| Night Sky's Edge | Have Jirachi in HGSS; provenance caveat below | [Route article][SKY] |
| Yellow Forest | Obtain its Route Map through an event download, including Wi-Fi distribution | [Route article][YELLOW] |
| Rally | Nintendo event distribution | [Route article][RALLY] |
| Sightseeing | Nintendo event distribution | [Route article][SIGHTS] |
| Winner's Path | Event Route Map; Wi-Fi and venue distributions | [Route article][WINNER] |
| Amity Meadow | Event Route Map; Japanese venue distribution | [Route article][AMITY] |

**UNVERIFIED — Jirachi provenance:** current Bulbapedia says owning Jirachi suffices; older PLDH specifies a fateful-encounter Jirachi. No checked reverse-engineering passage settles that distinction. Do not implement the older restriction as confirmed. [Night Sky's Edge][SKY]; [PLDH][PLDH] — checked 2026-11-04.

## Facts — storage and event history (A6)

| Stored object | Capacity | When full / collection behavior | Source, checked 2026-11-04 |
|---|---:|---|---|
| Walking companion | 1 | Separate from catches | [Nintendo operations manual][OPS] |
| Radar-caught Pokémon | 3 | Another catch prompts a replacement/discard decision | [Nintendo operations manual][OPS]; [Serebii][SER] |
| Found/dowsed items | 3 | Another find prompts a replacement/discard decision | [Nintendo operations manual][OPS]; [PLDH][PLDH] |
| Peer-play gift items | 10 | Further connections award watts until gifts are collected | [Nintendo operations manual][OPS] |

These are **already-acquired holdings**, not a queue of unresolved encounters. “Three caught Pokémon” therefore does not establish a historical pending-encounter limit; the bot's queue is a separate design decision.

Reverse engineering identifies separate **one-Pokémon/one-item special-event slots**, apparently unused. These do not establish retail event-route behavior. [Grinberg, Abnormal processes; checked 2026-11-04][DG].

**History:** a **24-event circular log** records catches, items, encounter outcomes, strolls and moods/sleep; **10 peer teams** are retained. New strolls clear both. [Grinberg, Structures/EEPROM map/Walk start; checked 2026-11-04][DG].

## Facts — peer play (A7)

Both users initiate a connection; their Pokémon interact and each user receives a gift. A given pair of devices can connect **once per day**. [Nintendo's launch announcement][NEWS]; [Nintendo operations manual, sections 6/9][OPS] — checked 2026-11-04.

The gift comes from the receiving player's route. Exchanged party data later supplies a Trainer House opponent in HGSS; the walkers' animation is not a remotely controlled trainer battle. [Serebii, Connect][SER]; [PLDH, Interactions][PLDH] — checked 2026-11-04.

**UNVERIFIED — overflow amount:** Grinberg's printed `max(99, seed / 200)` with `seed >= 20,000` implies **at least 100 W**; Bulbapedia reports **1–99 W** using steps alone. Full gifts yield watts; the formula remains unresolved. [Grinberg, Peer play][DG]; [Bulbapedia, Other Pokéwalkers][BP] — checked 2026-11-04.

## Facts — sleep and idle events (A8)

- After **60–90 seconds** without button input, the screen sleeps while steps continue counting; holding the center button for approximately **0.5 seconds** wakes it. Seven days of daily step history are retained, overwriting older days. [Nintendo operations manual, sections 4/8; checked 2026-11-04][OPS].
- Waking after **60 minutes** without a gift has a documented **40%** gift/bored-response check, gated by current-hour steps and friendship. [Bulbapedia, Gifts from Pokémon; checked 2026-11-04][BP].
- Walking without a companion still counts steps and earns watts, but Radar is unavailable. A route Pokémon can later join an empty walker. [Nintendo HGSS booklet, printed p. 33][HG]; [Serebii][SER] — checked 2026-11-04.
- Ordinary Pokéwalker catches cannot be shiny. **Project distinction:** this bot intentionally allows shiny encounters; its shiny rate is a separate design parameter. [PKHeX's documented Pokéwalker generation category; checked 2026-11-04][SHINY].

## Derived pacing — arithmetic, not documented design targets (A8)

| Opportunity / milestone | Walking-only equivalent | Assumptions |
|---|---:|---|
| One Radar attempt | `10 × 20 = 200` steps | No bonus watts; capture is not guaranteed |
| One dowsing attempt | `3 × 20 = 60` steps | No bonus watts; item discovery is not guaranteed |
| One of each attempt | `13 × 20 = 260` steps | Costs combined; not an automatic encounter interval |
| Quiet Cave unlock | `100,000 × 20 = 2,000,000` steps | All watts banked; no minigame spending or gifted watts; National Dex required |

Inputs: [Nintendo HGSS booklet][HG] and [Pokémon Database's Quiet Cave threshold][DB], checked **2026-11-04**. Rare encounter eligibility adds route-specific daily step gates, detailed in [routes-encounters.md](routes-encounters.md). An exact intended “steps per successful catch” or typical user event frequency is **UNVERIFIED**: it also depends on route, availability, player choices and unsuccessful searches.

[DG]: https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker
[HG]: https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/DS_Pokemon_HeartGold
[OPS]: https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/Pokewalker_Tri
[BP]: https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9walker
[SER]: https://www.serebii.net/heartgoldsoulsilver/pokewalker.shtml
[PLDH]: https://pldh.net/guides/heartgoldsoulsilver/pokewalker
[DB]: https://pokemondb.net/heartgold-soulsilver/pokewalker
[SEA]: https://bulbapedia.bulbagarden.net/wiki/Beyond_the_Sea_(Pok%C3%A9walker)
[SKY]: https://bulbapedia.bulbagarden.net/wiki/Night_Sky%27s_Edge_(Pok%C3%A9walker)
[YELLOW]: https://bulbapedia.bulbagarden.net/wiki/Yellow_Forest_(Pok%C3%A9walker)
[RALLY]: https://bulbapedia.bulbagarden.net/wiki/Rally_(Pok%C3%A9walker)
[SIGHTS]: https://bulbapedia.bulbagarden.net/wiki/Sightseeing_(Pok%C3%A9walker)
[WINNER]: https://bulbapedia.bulbagarden.net/wiki/Winner%27s_Path_(Pok%C3%A9walker)
[AMITY]: https://bulbapedia.bulbagarden.net/wiki/Amity_Meadow_(Pok%C3%A9walker)
[SHINY]: https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Legality/RNG/PIDType.cs
[NEWS]: https://www.nintendo.com/en-gb/News/2010/New-Pokewalker-accessory-brings-Pokemon-training-to-the-real-world-252312.html
