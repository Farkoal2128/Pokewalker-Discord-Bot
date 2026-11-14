# Economy simulation report

## Inputs

- Artifact manifest SHA-256 (`content/manifest.json`): `d46829a01c6aa74fb0ef39384b1a480a5295fea87e17b6864d97ff8b094418a1`
- Artifact SHA-256 (`content/artifact/content.json`): `52301ef0e4b36ba4e76125d3ddf730afbe0ef76f5dda53297a25ec917f1ecfcc`
- Seed: 1 (reset for each scenario and play style)
- Days: 30
- Requested profile: regular
- Profile source: fallback regular: daily message counts, characters/5 word estimate
- G-1: no chat export used; adaptation.md fallback profiles are assumptions, not measured behavior.
- Fallback daily profiles: casual 10 messages x 10 words; regular 25 x 12; active 60 x 15. Daily totals are distributed across active hours.
- Balance table versions:
  - arena.json: v2
  - battle.json: v2
  - capacities.json: v3
  - catch.json: v4
  - checkin_table.json: v2
  - conversion_rates.json: v4
  - cpm.json: v1
  - evolution.json: v1
  - find_table.json: v2
  - gym_income_table.json: v2
  - milestones.json: v1
  - powerup_prices.json: v1
  - routes.json: v2
  - simulation.json: v1
  - step_rules.json: v1
  - survivor_table.json: v3
  - tier_chances.json: v1

All numbers below use the same requested chat profile at 1, 4 and 8 active hours/day; these are activity-duration scenarios.
Continuous resolves encounters as a slot is needed; hourly check clears the queue once per active hour.
routes cycle each active hour; no transfers/evolution, lure or Pinap use; starter favourite. Catches, including virtual catches, stop at full storage (250); no send-to-research is simulated.
Balls supplied include the starter kit, finds, /checkin and claimed milestones. Item values use the authored conversion rates; Candy is family scoped.
First-shiny mean/median are geometric estimates from generated encounter pace, not Monte Carlo sample averages or guaranteed catches.

## 1 active hours/day

| Metric | continuous | hourly check |
|---|---:|---:|
| Encounters | 91 | 90 |
| Encounters / active hour | 3.03 | 3.00 |
| Balls supplied | 390 | 393 |
| Balls spent (stock-limited) | 173 | 173 |
| Candy in (all families) | 372 | 364 |
| Favourite Candy in | 65 | 65 |
| Stardust in | 17800 | 17310 |
| Power-up cost to level 30 (Candy / Stardust) | 100 / 15000 | 100 / 15000 |
| Power-up cost to level 40 (Candy / Stardust) | 180 / 35000 | 180 / 35000 |
| Favourite final level | 24.00 | 24.00 |
| First shiny mean / median (days) | 84.40 / 58.68 | 85.33 / 59.33 |
| Observed first shiny day | not observed | not observed |
| Storage fill day | not observed | not observed |

## 4 active hours/day

| Metric | continuous | hourly check |
|---|---:|---:|
| Encounters | 91 | 91 |
| Encounters / active hour | 0.76 | 0.76 |
| Balls supplied | 410 | 410 |
| Balls spent (stock-limited) | 190 | 190 |
| Candy in (all families) | 364 | 364 |
| Favourite Candy in | 63 | 63 |
| Stardust in | 15100 | 15100 |
| Power-up cost to level 30 (Candy / Stardust) | 100 / 15000 | 100 / 15000 |
| Power-up cost to level 40 (Candy / Stardust) | 180 / 35000 | 180 / 35000 |
| Favourite final level | 23.50 | 23.50 |
| First shiny mean / median (days) | 84.40 / 58.68 | 84.40 / 58.68 |
| Observed first shiny day | not observed | not observed |
| Storage fill day | not observed | not observed |

## 8 active hours/day

| Metric | continuous | hourly check |
|---|---:|---:|
| Encounters | 91 | 91 |
| Encounters / active hour | 0.38 | 0.38 |
| Balls supplied | 455 | 455 |
| Balls spent (stock-limited) | 275 | 275 |
| Candy in (all families) | 374 | 374 |
| Favourite Candy in | 60 | 60 |
| Stardust in | 20380 | 20380 |
| Power-up cost to level 30 (Candy / Stardust) | 100 / 15000 | 100 / 15000 |
| Power-up cost to level 40 (Candy / Stardust) | 180 / 35000 | 180 / 35000 |
| Favourite final level | 23.00 | 23.00 |
| First shiny mean / median (days) | 84.40 / 58.68 | 84.40 / 58.68 |
| Observed first shiny day | 17.25 | 17.25 |
| Storage fill day | not observed | not observed |

## D47 comparison

Unmet demand is an estimate: throws the policy would have made with unlimited supply. Virtual throws use the preferred Poke Ball, consume available selected berries, and resolve catches/flees to free queue slots, including Legendary/Mythical encounters.
Virtual catches also feed progression and milestones; these policy estimates are not predictions of actual stock-limited catches or income.
Gym assumptions: (a) one 8-hour deployment per day; (b) held all day with immediate re-deployment. One weighted reward pack per full hour held; values below are expected quantities before inventory limits, not simulated gym gameplay.
All comparison amounts cover the full scenario duration. Deficit = max(0, spent + unmet - supplied); aggregate ball counts treat types as substitutable.

| Hours/day | Style | Supplied | Spent | Unmet demand (estimate) | Demand | Deficit | Stockout encounters | Gym balls (a) | Gym balls (b) | (a) closes deficit? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | continuous | 390 | 173 | 0 | 173 | 0 | 0 | 725.28 | 2,175.84 | no deficit |
| 1 | hourly check | 393 | 173 | 0 | 173 | 0 | 0 | 725.28 | 2,175.84 | no deficit |
| 4 | continuous | 410 | 190 | 0 | 190 | 0 | 0 | 725.28 | 2,175.84 | no deficit |
| 4 | hourly check | 410 | 190 | 0 | 190 | 0 | 0 | 725.28 | 2,175.84 | no deficit |
| 8 | continuous | 455 | 275 | 0 | 275 | 0 | 0 | 725.28 | 2,175.84 | no deficit |
| 8 | hourly check | 455 | 275 | 0 | 275 | 0 | 0 | 725.28 | 2,175.84 | no deficit |

| Gym item | Expected quantity per 8-hour deployment |
|---|---:|
| poke_ball | 19.36 |
| great_ball | 4.32 |
| ultra_ball | 0.48 |
| razz_berry | 0.64 |
| pinap_berry | 0.64 |
| golden_razz_berry | 0.12 |
| silver_pinap_berry | 0.08 |
| rare_candy | 0.16 |
| stardust | 19.20 |
| shiny_lure | 0.08 |
| master_ball | 0.02 |
| star_piece | 0.04 |
| evolution_item | 0.16 |
| vitamin | 0.08 |
| **All balls (including Master Ball)** | **24.18** |

## Arena ticket income

Reference floors from Arena requirements sections 6.1 and 8 are assumptions, not predictions; no fights are simulated.
Repeat tickets only, first-clear bonuses excluded. A skip changes fights and payment timing, not total tickets from floors 1 through the cleared floor.
Encounter totals are upper bounds assuming room at every redemption; fill uses the live queue capacity. Roll values are before inventory limits; encounter value and berry costs are excluded.
Skip 40 / floor 40 means start and back out: no fights, all tickets paid at start.
Cooldown: 64,800 seconds; 1.33 runs/day.
Income roll value: 25.61 Stardust; survivor reward value (including flat Stardust): 754.25 Stardust.
Unpriced items (counted as zero): world_legendary_ticket.
Arena payouts below are separate from walking/catching income and the existing Checks; no approved Arena income expectation exists.

| Skip | Floor cleared | Fights | Tickets | At start | Encounters (max) | Stardust | Income rolls | Survivor rolls | Stardust-equivalent | At-start Stardust-equivalent | Stardust-equivalent/day |
|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | 10 | 30 | 1 Bronze, 1 Silver | none | 3 | 300 | 2 | 0 | 351.23 | 0.00 | 468.31 |
| 0 | 20 | 60 | 2 Bronze, 2 Silver | none | 6 | 600 | 4 | 0 | 702.46 | 0.00 | 936.61 |
| 0 | 30 | 90 | 2 Bronze, 3 Silver, 1 Gold | none | 11 | 1200 | 10 | 0 | 1,456.15 | 0.00 | 1,941.53 |
| 0 | 40 | 120 | 2 Bronze, 4 Silver, 2 Gold | none | 16 | 1800 | 16 | 0 | 2,209.84 | 0.00 | 2,946.45 |
| 40 | 40 | 0 | 2 Bronze, 4 Silver, 2 Gold | 2 Bronze, 4 Silver, 2 Gold | 16 | 1800 | 16 | 0 | 2,209.84 | 2,209.84 | 2,946.45 |
| 40 | 60 | 60 | 2 Bronze, 4 Silver, 4 Gold, 2 Platinum | 2 Bronze, 4 Silver, 2 Gold | 28 | 4600 | 40 | 2 | 7,133.10 | 2,209.84 | 9,510.80 |
| 40 | 80 | 120 | 2 Bronze, 4 Silver, 6 Gold, 3 Platinum, 1 Diamond | 2 Bronze, 4 Silver, 2 Gold | 40 | 9400 | 80 | 6 | 15,974.70 | 2,209.84 | 21,299.60 |
| 40 | 100 | 180 | 2 Bronze, 4 Silver, 8 Gold, 3 Platinum, 3 Diamond | 2 Bronze, 4 Silver, 2 Gold | 52 | 16200 | 136 | 12 | 28,734.64 | 2,209.84 | 38,312.85 |

## Checks

PASS/FAIL compares these model outputs with the expectations; FAIL does not authorize tuning tables.
D47: Scarcity is intended. Walking finds plus /checkin deliberately do not fully cover a top-pace player's ball use; gym income is the intended extra source.
- **FAIL — 8-hour continuous ball shortfall (M0.8): 0.** Actual spending is stock-limited; unmet demand is estimated separately. This profile/seed does not establish the intended top-pace shortfall; no values were tuned to force it.
- **FAIL — gym assumption (a) closes a positive 8-hour continuous deficit.** See both holding assumptions above.

D59: every bundle must be strictly smaller than one month of each scenario's income, compared in stardust equivalent (items plus Stardust; income normalized to 30 days).

| Expectation | continuous | hourly check |
|---|---|---|
| D59 bronze, 1 hours/day | PASS: 575 < 19,696.00 | PASS: 575 < 19,310.00 |
| D59 diamond, 1 hours/day | FAIL: 52,500 >= 19,696.00 | FAIL: 52,500 >= 19,310.00 |
| D59 gold, 1 hours/day | PASS: 6,050 < 19,696.00 | PASS: 6,050 < 19,310.00 |
| D59 platinum, 1 hours/day | PASS: 16,250 < 19,696.00 | PASS: 16,250 < 19,310.00 |
| D59 silver, 1 hours/day | PASS: 2,215 < 19,696.00 | PASS: 2,215 < 19,310.00 |
| D59 bronze, 4 hours/day | PASS: 575 < 16,847.00 | PASS: 575 < 16,847.00 |
| D59 diamond, 4 hours/day | FAIL: 52,500 >= 16,847.00 | FAIL: 52,500 >= 16,847.00 |
| D59 gold, 4 hours/day | PASS: 6,050 < 16,847.00 | PASS: 6,050 < 16,847.00 |
| D59 platinum, 4 hours/day | PASS: 16,250 < 16,847.00 | PASS: 16,250 < 16,847.00 |
| D59 silver, 4 hours/day | PASS: 2,215 < 16,847.00 | PASS: 2,215 < 16,847.00 |
| D59 bronze, 8 hours/day | PASS: 575 < 23,085.00 | PASS: 575 < 23,085.00 |
| D59 diamond, 8 hours/day | FAIL: 52,500 >= 23,085.00 | FAIL: 52,500 >= 23,085.00 |
| D59 gold, 8 hours/day | PASS: 6,050 < 23,085.00 | PASS: 6,050 < 23,085.00 |
| D59 platinum, 8 hours/day | PASS: 16,250 < 23,085.00 | PASS: 16,250 < 23,085.00 |
| D59 silver, 8 hours/day | PASS: 2,215 < 23,085.00 | PASS: 2,215 < 23,085.00 |

Planner expectation (not an approved balance rule): level 30 reachable within 30 days at 4 hours/day.

- **FAIL — continuous**: favourite final level 23.5 after 30 days. This run does not establish level 30 within 30 days.
- **FAIL — hourly check**: favourite final level 23.5 after 30 days. This run does not establish level 30 within 30 days.

Failed checks are retained for G-2 owner review. No approved values were changed.

## Legendary pacing

This is a report for the open question, not a decision. Expectations describe appearances before catch time; they do not claim group catches or milestone completion.
Identity expectations use the Legendary/Mythical tier split; group expectations allow species with multiple identities and measure seeing every member.
Hours divide expected encounters by this run's continuous generated-encounter pace (1 / 4 / 8 hours/day), not by available balls.

| Identity | Expected encounters | Expected active hours (1 / 4 / 8) |
|---|---:|---:|
| Articuno (`144:144`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zapdos (`145:145`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Moltres (`146:146`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Mewtwo (`150:150`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Mew (`151:151`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Raikou (`243:243`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Entei (`244:244`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Suicune (`245:245`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Lugia (`249:249`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Ho-Oh (`250:250`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Celebi (`251:251`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Regirock (`377:377`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Regice (`378:378`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Registeel (`379:379`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Latias (`380:380`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Latios (`381:381`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Kyogre (Kyogre) (`382:382`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Groudon (Groudon) (`383:383`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Rayquaza (`384:384`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Jirachi (`385:385`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Normal Deoxys (`386:386`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Uxie (`480:480`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Mesprit (`481:481`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Azelf (`482:482`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Dialga (`483:483`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Palkia (`484:484`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Heatran (`485:485`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Regigigas (`486:486`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Altered Giratina (`487:487`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Cresselia (`488:488`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Phione (`489:489`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Manaphy (`490:490`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Darkrai (`491:491`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Land Shaymin (`492:492`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Normal Arceus (`493:493`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Victini (`494:494`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Cobalion (`638:638`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Terrakion (`639:639`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Virizion (`640:640`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Incarnate Tornadus (`641:641`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Incarnate Thundurus (`642:642`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Reshiram (`643:643`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zekrom (`644:644`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Incarnate Landorus (`645:645`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Kyurem (Kyurem) (`646:646`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Ordinary Keldeo (`647:647`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Aria Meloetta (`648:648`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Genesect (`649:649`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Neutral Xerneas (`716:10132`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Yveltal (`717:717`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zygarde (50% Forme) (`718:718`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Diancie (`719:719`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Confined Hoopa (`720:720`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Volcanion (`721:721`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Type: Null (`772:772`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Silvally (Type: Normal) (`773:773`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Tapu Koko (`785:785`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Tapu Lele (`786:786`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Tapu Bulu (`787:787`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Tapu Fini (`788:788`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Cosmog (`789:789`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Cosmoem (`790:790`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Solgaleo (`791:791`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Lunala (`792:792`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Necrozma (`800:800`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Magearna (`801:801`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Marshadow (`802:802`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zeraora (`807:807`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Meltan (`808:808`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Melmetal (`809:809`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zacian (`888:888`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zamazenta (`889:889`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Eternatus (`890:890`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Kubfu (`891:891`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Single Strike Urshifu (`892:892`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Zarude (`893:893`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Regieleki (`894:894`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Regidrago (`895:895`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Glastrier (`896:896`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Spectrier (`897:897`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Calyrex (`898:898`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Incarnate Enamorus (`905:905`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Wo-Chien (`1001:1001`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Chien-Pao (`1002:1002`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Ting-Lu (`1003:1003`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Chi-Yu (`1004:1004`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Koraidon (Apex Build) (`1007:1007`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Miraidon (Ultimate Mode) (`1008:1008`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Okidogi (`1014:1014`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Munkidori (`1015:1015`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Fezandipiti (`1016:1016`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Teal Mask Ogerpon (`1017:1017`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Normal Form Terapagos (`1024:1024`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Pecharunt (`1025:1025`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Galarian Articuno (`10169:10328`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Galarian Zapdos (`10170:10329`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |
| Galarian Moltres (`10171:10330`) | 9,700.00 | 3,197.80 / 12,791.21 / 25,582.42 |

| Named group (seeing every member) | Expected encounters | Expected active hours (1 / 4 / 8) |
|---|---:|---:|
| birds | 8,891.67 | 2,931.32 / 11,725.27 / 23,450.55 |
| beasts | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| tower_duo | 14,550.00 | 4,796.70 / 19,186.81 / 38,373.63 |
| regis | 23,765.00 | 7,834.62 / 31,338.46 / 62,676.92 |
| eon_duo | 14,550.00 | 4,796.70 / 19,186.81 / 38,373.63 |
| weather_trio | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| lake_trio | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| creation_trio | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| swords_of_justice | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| forces_of_nature | 20,208.33 | 6,662.09 / 26,648.35 / 53,296.70 |
| tao_trio | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| aura_trio | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| guardian_deities | 20,208.33 | 6,662.09 / 26,648.35 / 53,296.70 |
| light_trio | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| hero_duo | 14,550.00 | 4,796.70 / 19,186.81 / 38,373.63 |
| calyrex_and_steeds | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |
| treasures_of_ruin | 20,208.33 | 6,662.09 / 26,648.35 / 53,296.70 |
| paradox_duo | 14,550.00 | 4,796.70 / 19,186.81 / 38,373.63 |
| loyal_three | 17,783.33 | 5,862.64 / 23,450.55 / 46,901.10 |

## Route tier pool sizes

| Route | Common | Uncommon | Rare | Evolved | Legendary/Mythical |
|---|---:|---:|---:|---:|---:|
| refreshing_field | 154 | 91 | 23 | 177 | 97 |
| noisy_forest | 138 | 74 | 20 | 174 | 97 |
| rugged_road | 108 | 78 | 32 | 155 | 97 |
| beautiful_beach | 167 | 109 | 27 | 190 | 97 |
| suburban_area | 173 | 121 | 35 | 224 | 97 |
| dim_cave | 145 | 86 | 24 | 206 | 97 |
| blue_lake | 168 | 91 | 30 | 200 | 97 |
| volcano_path | 134 | 95 | 34 | 196 | 97 |

Numbers above change approved settings only through a README edit by the owner (G-2)
