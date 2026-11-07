# Research synthesis and review

Reviewed **2026-11-04** by Claude. This is the "Claude reviews the research" step from the
[requirements draft](../features/pokewalker-bot/README.md#delivery-workflow-owner-intent). It
pulls together the six research sets, lists where they disagree, and lists the decisions
the owner must make before `PLAN.md`. It adds no new sourced facts. Anything marked
**proposal** here is a reviewer recommendation, not an approved requirement.

Sources: [Discord/stack](README.md), [Pokéwalker loop](pokewalker/README.md),
[GO progression](go-systems/README.md), [gyms](gyms/README.md),
[data/visuals](data-visuals/README.md), [hosting](hosting/README.md).

## 1. What the research agrees on

These points are consistent across every research set. Planning can treat them as settled
unless the owner objects.

| Area | Consolidated position |
|---|---|
| Stack | Python 3.12+, pinned discord.py, `aiosqlite`, SQLite in WAL mode with `synchronous=FULL`, Pillow for rendering. Classic buttons, not Components V2. One process, one Gateway connection, no inbound port. |
| Intents | `GUILDS`, `GUILD_MESSAGES`, `MESSAGE_CONTENT` only. Message cache off (`max_messages=None`). No message text is persisted or logged. |
| Permissions | `VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`, `ADD_REACTIONS`. **Not** `MANAGE_MESSAGES`: the bot removes only its own ❗. Admin commands use `default_member_permissions=MANAGE_GUILD` and recheck the invoker at runtime. |
| State model | The database is the only source of truth. Ephemeral screens are views that can be rebuilt. `/walker` reconstructs the current state after a restart, dismissal or token expiry. Interaction tokens are never stored. |
| Correctness | One writer owns whole transactions. Encounter identity (species, form, level, IVs, shiny) is frozen when the encounter is **queued**. Catch, spend, storage insert and rewards commit together. A conditional revision check plus a receipt for each logical action make double-clicks return the saved result. Commit first, then edit Discord. |
| Queue | At most 3 unresolved encounters. Steps keep counting while the queue is full, but no encounter "debt" builds up. No automatic expiry. An encounter leaves the queue only when it is caught, when the player Runs, or when it flees after a failed throw (Legendaries and shinies never flee). |
| Steps | *(Superseded: one step per word (D33), rolling-hour limits with no UTC-day budgets (D9, D20), per-server scope (D10). The text below is the original research consensus.)* Count eligible grapheme characters (letters/numbers) at **5 characters = 1 step**. Filters: minimum length, repeated-character cap, a 30-minute normalized-duplicate window, a per-message cap, a cooldown and a rolling-minute cap. Abuse budgets apply across all channels. Edits and backfill earn nothing. Daily windows reset on UTC days. |
| Economy | No spendable watts. Family Candy plus universal Stardust. No Candy XL, Trainer XP, trading, weather, Shadow or Lucky modifiers. GO-style CP from GO base stats, IVs 0–15 and a frozen CPM table. `level_x2` is an integer. |
| Catching | Ball/berry exponent model with throw, curve and medal modifiers fixed at 1. No timing minigame. Bot-defined BCR classes by tier, as in D38: Common 0.50, Uncommon 0.30, Rare and Evolved 0.15, Legendary/Mythical 0.05 (never flee). Master Ball needs a confirmation. Shiny encounters never flee, and Run on a shiny needs a second confirmation. |
| Shiny | 1/256 base. The Shiny Lure gives 4× for encounters **generated** within one real hour of activation. It affects nothing already queued, does not stack, and at most one is held. |
| Content | *(Roster superseded: the full main-series roster, D37 and D51–D58.)* A versioned local PokéAPI snapshot for an explicitly chosen roster. Bot-owned JSON for GO-style stats, CPM, routes, families, evolutions and moves. Nothing is fetched upstream during an interaction. |
| Privacy | Opt-in enrollment plus `/walker-account privacy`, `opt-out` and `delete-data` (renamed from `/walker …`, which can't have subcommands; see D31). A privacy policy URL is required. The database and backups are encrypted at rest. |
| Ops | One hardened systemd unit, an operator-run release-symlink deploy, hourly SQLite `.backup` with an encrypted off-machine copy, monthly restore drills, an external heartbeat, and owner-only `/admin status, errors, restart` (restart exits with code 75). |

## 2. Conflicts that must be resolved

Each research set was written separately, and they contradict each other on the points below.
The planner cannot pick for the owner on 2.1–2.3.

> **Resolved 2026-11-04.** The owner decided 2.1–2.4 in
> [requirements D9–D19](../features/pokewalker-bot/README.md#owner-decisions-after-the-research-review-2026-11-04):
> hourly limits only, with no daily caps; **everything per server**, which reverses the
> "global" proposal in 2.2; passive finds plus an hourly `/checkin`; and D3 kept.
> The proposals below are kept as the review record. Where they conflict, the
> requirements win.

### 2.1 Encounter pacing (blocking)

- **Pokéwalker research:** one encounter per **100** awarded steps, with diminishing returns after 500 steps/day and a hard cap of **1,000 awarded steps/day**. That allows at most 10 encounters a day.
- **GO research (owner-selected):** **3 eligible encounters per active hour**. The 1,000-step daily cap supports that pace for only 3 h 20 min a day.
- "Active hour" has no definition anywhere.

**Proposal:** keep 100 steps per encounter and replace the *daily* diminishing-returns
curve with an *hourly* one: the first **300 awarded steps per rolling hour** count in full,
and later steps count at 25%. Keep a daily safety ceiling of about **3,000 awarded steps**
(30 encounters). The 3-encounter target then becomes the natural rate for an engaged
chatter: roughly one 25-character message a minute. Spam beyond that is heavily discounted.
The queue cap still limits anyone who stops resolving encounters. Define an "active hour"
for metrics as an hour containing at least one credited message.

### 2.2 Progression scope: per-server or global (blocking)

- Pokéwalker and Discord research: player profiles keyed by `(guild_id, user_id)`.
- GO, storage and gym research: **one global collection and inventory per Discord user**,
  global earning caps, steps attributed to the guild they came from, and gyms owned by servers.

**Proposal: global.** Gyms, rare-item caps, Shiny Lure scope, deployment caps and
the gym reward rule are all designed around it. Global anti-farming also stops
someone multiplying rewards by joining more servers. Counting channels, gyms and
admin configuration stay per server. Route choice is the only per-server-flavoured
item: store it per player and validate it against the current server's enabled
routes.

### 2.3 Item supply: passive finds or dowsing (blocking for v1 items)

- Pokéwalker research: dowsing later, one search per 300 steps.
- GO research: **passive finds**, one per 100 awarded steps, up to 10 per UTC day, each with 20 Stardust. "Never run both."

**Proposal:** passive finds in v1. Dowsing can come back later as the *presentation* of a find,
for example "a find gives you a two-guess dowsing panel", so there is still only one
supply budget. **Supply check needed:** at 10 finds per day the expected supply is about
31 balls a day. At roughly 2 throws per encounter that covers about 15 encounters a day.
Under proposal 2.1 a very active player can reach 30, so either raise the find cap
toward 20 or accept that heavy days run short of balls. Settle this with the economy
simulation in §4.

### 2.4 ❗ reaction policy (minor)

There are three versions: requirement D3 (only the first queued encounter), the Pokéwalker
research (every message that creates an encounter) and the Discord research (only when the
queue goes from empty to non-empty). **Proposal:** keep D3 as written. The empty-to-non-empty
rule is the same thing stated precisely. It is quieter and makes fewer reaction calls.

### 2.5 Catch screen flow (minor)

The Pokéwalker research proposes Reveal → Throw/Run (2 presses). The GO research proposes
Ball/Berry/Throw/Later/Run with repeated throws and a 10% flee chance. They fit together:
**Reveal** shows the scene, and then the GO panel. Treat the GO research's version as the
catch contract.

### 2.6 Route rarity versus catch class (minor)

*(Superseded: routes are now type-weighted tier rolls over encounter identities; see D38 and
D50. The six-slot A/B/C model below is historical.)*

Route groups A/B/C (weights 10:30:60, unlocked after 0/100/500 route steps) and species
BCR classes (common/uncommon/rare) are designed separately. **Proposal:** BCR class is a
property of the species in that route slot, so a group-A slot normally holds a rare-class
species. Write both in the same hand-authored `routes.json`.

### 2.7 Corrections to the requirements draft

Both corrections are sourced, not proposals:

- **Manage Messages is not needed** to remove the bot's own ❗. Change the
  "Platform constraints" bullet and drop the related open question.
- **The Message Content review threshold is now 10,000 unique users**, not 100
  servers (changed June 2026). App verification past 100 servers is a separate process.

## 3. Proportion check: what to cut from v1

The research describes far more than a first playable version needs. The gym design in
particular brings leased workers, fencing tokens, reservations, a 60-second processing
deadline and about 14 new tables. That machinery is for multi-worker systems, and this
project is planned as one process with one writer.

> **Superseded 2026-11-04** by the owner-approved split in
> [requirements D35](../features/pokewalker-bot/README.md#d35-release-split). That split
> moves the Pokédex into v1, adds the new features to v1, and makes v2 gyms only.

**Proposed release cut (original review):**

| Release | Contents |
|---|---|
| **v1: walking loop** | Enrollment and privacy commands; server channel config; step counting and anti-farming; queue and ❗; `/walker` reveal and catch with balls/berries; CP/IV/level; collection view with pages; passive item finds; Candy/Stardust; send for research; power-up; 2 routes; shiny plus Shiny Lure; owner `/admin`; backups. |
| **v1.1: depth** | Evolution (Candy plus the 7 stones), Star Piece, storage expansion, a third route and unlocks, rendered scene images (text embeds until then), a Pokédex/collection tracker. |
| **v2: social** | Gyms (individual holders, auto-sim), peer visits, dowsing presentation. |
| **Later** | Interactive battle turns, raids, trading, Candy XL, events. |

Because the database has one writer, gym battles in v2 can be simulated and settled in a
single transaction. Most of the reservation and lease design can stay on paper until there
is more than one process.

## 4. Gaps: further research and work recommended

Ordered by how much each one blocks planning.

1. **Real chat-rate measurement (blocking 2.1).** Every pacing number assumes certain chat
   behaviour. Run the approved D33 word filter and D20 step curve over the target server's
   messages, processing text in memory and keeping only per-member hourly totals of accepted
   words and awarded steps. Plain message counts can't tell a 4-word message from a
   20-word one. Calibrate the economy simulation against those totals. This is better as a small measurement than as web research.
2. **Economy simulation (blocking 2.3).** Build a small Monte Carlo of a player at 1, 4 and 8
   active hours a day. It covers encounters, throws, ball supply, Candy and Stardust income
   against power-up prices, time to the first shiny, and storage fill. It would also check
   the proposed power-up price table, which no one has validated. This is a script, not web
   research, and can live under `scripts/` with a test.
3. **Content import (was "launch roster").** D37 makes the roster every main-series species
   plus regional forms, so there is nothing to hand-pick. This row becomes a build-time
   importer from a pinned PokéAPI snapshot. It derives GO-style stats, rarity tiers, Candy
   families and evolution costs by D38–D41, and validates them: every species has
   stats, a tier and a family, and no Mega, Gigantamax or other battle-only form slips in.
   The derived tier sizes feed the economy simulation. HGSS sprites stop at #493, so v1.1
   images need a different main art family. Research first: the
   [PokéAPI forms brief](briefs/pokeapi-forms.md).
4. **IP and fan-content policy research: dropped by the owner (2026-11-04).** This is a
   personal project, so no further IP research is planned. Requirement D8 still applies: no
   extracted assets are committed. v1 screens and shares hotlink PokéAPI sprites from a pinned
   commit, and Discord fetches them (D48–D49). v1.1 rendered scenes use a local sprite cache
   that is filled at deploy time and never committed. Embed text stays complete if an image
   fails.
5. **Message Content approval strategy.** This only matters past 10,000 users, but record the
   fallback now: what the game becomes if approval is denied (event-count-only steps, with
   no length or duplicate checks).
6. **Privacy policy and terms text.** The Developer Terms require it. Draft it as a project
   document, covering what is processed, what is retained, how long, and the deletion path.
7. **Multilingual counting check.** Steps are now words (D33). Under D33/D43,
   single-ideograph Chinese/Japanese segments are rejected (so they earn nothing) and a run
   of Thai counts as one word. English only is accepted for now (D43); recheck before
   supporting other scripts.

## 5. Scope additions worth considering

None of the research proposes these, but they fit the concept:

- **Walking companion.** The original device is built around one Pokémon you walk with, and
  the research dropped it. A chosen companion could earn its family Candy every N steps,
  which is GO's buddy mechanic and the research's deferred "buddy Candy". It could also
  appear on the `/walker` screen. It costs little, makes `/walker` feel like the device, and
  gives Candy for favourites.
- **Pokédex / collection goals.** Track species seen versus caught per player, with route
  completion. It is cheap, motivates players over time, and fits the private-screen design.
- **Onboarding.** A first `/walker` that explains the loop, grants a starter set (the
  research already proposes 30 Poké Balls) and perhaps a guaranteed first encounter.
- **Moderator tools.** A server moderator can pause a member's earning or exclude them, and
  can see aggregate step stats, without seeing message content. The research covers the
  owner's `/admin`, but not server moderators.
- **Optional public flex.** An opt-in "share this catch" button that posts a single public
  message. This changes D2/D4 (nothing public by default), so it is the owner's call.
- **Send to research from the catch screen** *(owner request 2026-11-04; not yet a
  decision).* After each successful catch, the private result screen asks whether to send the
  new Pokémon for research, as a **Send to research (+1 Candy)** button next to Share and
  Done. It cuts the storage chore at 250 slots.
  - Only the just-caught Pokémon is sent. One press plus a confirmation sends it, and the
    reward is the same as a normal research send (1 family Candy).
  - The research-send protections apply: no button for shinies, Legendary/Mythical
    Pokémon, the starter or the companion.
  - The Pokédex still records the catch.
  - Ignoring the button keeps the Pokémon.

  Open: whether a player can also turn on a per-server setting to send new non-shiny
  duplicates **automatically**, without asking. That is riskier: an unwanted send can't be
  undone.

## 6. Decisions needed before `PLAN.md`

Items 1–3 and 5 were decided on 2026-11-04. All five §5 additions are in scope, along with
`/checkin` and hourly gym income; see requirements D9–D19. Still open:

Still pending: the catch-screen research send in §5 and the Legendary-pacing question in the
requirements' open questions. Both are outside plan scope until decided. The owner decided on
2026-11-04 that §4 items 1–3 become the **first rows
of `PLAN.md`**, ahead of application code. Order: the content import and the chat-rate
measurement (independent), then the economy simulation, which needs both. The simulation must also cover `/checkin` and gym item income. Its results
can change approved numbers only through a deliberate requirements update.

All other settings are approved as D20–D58. The "3 encounters/hour" target is no longer a cap.
The [PokéAPI forms research](data-visuals/pokeapi-forms.md) raised new owner decisions in §7; all were
accepted as D50–D58.

The stack ADR now exists as [ADR 0001](../decisions/0001-application-stack.md) (proposed).
The plan loop can start once PR 7 is merged.

## 7. Review of the PokéAPI forms research (PR 6)

Reviewed **2026-11-04** against D37–D49. The research answers the brief fully, keeps facts
and recommendations separate, and pins its data. The points below are where it changes or
challenges the requirements.

### 7.1 What it settles

- **Pin:** PokéAPI master `e5b79b2e15d7c50735a945936afd4cd1cfd94eae` (2026-11-02). It has
  1,025 species, including all Generation 9 DLC; release 2.9.0 lacks later form fixes. The
  sprite pin for D48 is a separate repository and still needs choosing.
- **Roster size:** 1,025 defaults + **57 regional forms** = **1,082 encounter identities**
  before any non-regional forms are added.
- **Filter:** flags alone are not enough (Eternamax and Minior are not flagged
  battle-only). The research gives an exact filter, a short named-exception list and build
  assertions. The content-import plan row follows §4 of the research together with D51–D58. Anything
  the research leaves pending must be reported by the importer, not guessed.
- **Flags:** 71 Legendary + 23 Mythical. **Ultra Beasts and Paradox Pokémon have neither
  flag** (except Koraidon and Miraidon, which are flagged Legendary), so under D38 they are ordinary species in the tiers D38 assigns (Poipole, at 420 base stats, is Uncommon) and D41's protections do not
  apply to them.
- **Families:** Candy family = evolution-chain ID. Phione and Manaphy share a family with no
  evolution between them.

### 7.2 Problem: tier pool sizes (affects D38/D46)

The research counted the old D38 tiers. *(Pre-D50 analysis: the chances below are the old ones that motivated D50. The approved
chances are 60/30/3/6/1.)* Recounting the pinned data under **D46**, using the
species evolution graph, singletons tiered by stats, and Legendary/Mythical first:

| Tier | Identities | Tier chance | Chance per species |
|---|---:|---:|---:|
| Common | 345 | 60% | 0.17% |
| Uncommon | 204 | 28% | 0.14% |
| Rare | **49** | 9% | **0.18%** |
| Evolved | **387** | 2% | **0.005%** |
| Legendary/Mythical | 97 | 1% | 0.010% |

*(Computed from the pinned `pokemon_species`, `pokemon` and `pokemon_stats` CSVs; the
research's 436 "Rare" = 49 + 387 here, so the counts reconcile.)*

Two consequences:

1. **Each Rare species is as common as a Common one.** Only 49 non-final species reach 500
   base stats (pseudo-legendary middle stages, Ultra Beasts, Paradox, strong singletons), so
   9% spread over 49 gives each one 0.18%.
2. **Each final evolution is half as likely as a Legendary.** 387 species share 2%. That may
   be the intent of D46, but it means a specific wild Charizard is rarer than a specific
   legendary.

Routes filter by type, so some routes will have **no** species in a tier. *(Resolved: D50
redistributes an empty tier's chance across the route's other tiers.)*

**Recommendation (owner decision):** pick tier chances by intended per-species rarity, for
example Common 60%, Uncommon 30%, Rare 3%, Evolved 6%, Legendary 1%. That gives about 0.17%,
0.15%, 0.06%, 0.016% and 0.010% per species: strictly rarer as you go down. When a route has
no species in the rolled tier, redistribute that tier's chance across the route's other non-empty
**non-legendary** tiers; Legendary/Mythical stays at exactly 1% (as D50 records). The economy simulation should confirm the final numbers.

### 7.3 Owner decisions the research could not settle, with recommendations

> **Accepted 2026-11-04.** The owner accepted §7.2 and every row below as written. They are
> recorded as [requirements D50–D58](../features/pokewalker-bot/README.md#forms-research-decisions-d50d58-approved-by-the-owner-2026-11-04).

| # | Question | Recommendation |
|---|---|---|
| 1 | Policy for the 31 species with stat/type-different non-regional forms, plus Arceus and Silvally (research §C1 matrix: separate encounter, default only, or owned form change) | **Default only** for Legendary/Mythical form changes: Deoxys, Origin forms, Therian forms, Kyurem/Necrozma/Calyrex fusions, Hoopa, Shaymin, Zygarde 10%, Arceus/Silvally types, Ogerpon masks, Eternal Floette. **Default only** for Partner Pikachu/Eevee, Rotom appliances and Roaming Gimmighoul. **Separate encounters** for forms the games treat as different wild Pokémon: Wormadam cloaks, Oricorio styles, Pumpkaboo/Gourgeist sizes, Bloodmoon Ursaluna. **Evolution branches** (picked when evolving): Lycanroc forms and Urshifu styles. This keeps D37's "no transformations" spirit and adds no form-change mechanic. |
| 2 | Minior: Meteor only, separate cores, or form change | **Meteor only.** Cores are Minior's in-battle transformation. |
| 3 | Gender. The requirements never say whether a Pokémon has a gender. | *(As recorded in D53, which also rolls Indeedee, Basculegion and Oinkologne 50/50 because the pinned data gives Oinkologne `gender_rate = 0`.)* **Roll gender when the encounter is queued**, using PokéAPI `gender_rate`. Gender picks the female sprite where `has_gender_differences`, and picks the variety for Indeedee, Basculegion and Oinkologne (whose genders have different stats). Meowstic differs only in art. |
| 4 | Stage topology: the species graph or the form-aware graph | **Form-aware graph for evolving, species graph for tiers.** Evolution uses the real routes (Galarian Linoone → Obstagoon; ordinary Linoone has no evolution). Tiers use the simpler species graph, as in §7.2. |
| 5 | Evolution-relevant cosmetic forms (White-striped Basculin, Own Tempo Rockruff, Burmy cloaks) | Collapse them to the default appearance. Because D40 strips non-item conditions, **any** Basculin can evolve to Basculegion and **any** Rockruff can choose its Lycanroc branch. Burmy gives Mothim (male) or Wormadam (female), with the cloak chosen when evolving. |
| 6 | Evolution items: PokéAPI has no Sinnoh or Unova Stone (they exist only in GO), and many main-series items fall outside the 7 | **Replace the GO 7-item list with the main-series items the pinned data actually uses** on retained routes: Fire, Water, Thunder, Leaf, Moon, Sun, Dusk, Shiny, Dawn and Ice stones, King's Rock, Metal Coat, Dragon Scale, Up-Grade and so on. The item drop and 500-Stardust purchase rules already scale to whatever item kinds the enabled recipes use. Mechanical, no hand-authored recipe table. Amends D40. |
| 7 | Shedinja | **Catch-only.** Nincada evolves to Ninjask; Shedinja appears as a wild Evolved-tier encounter. |
| 8 | Should Ultra Beasts and Paradox Pokémon count as Legendary-like? | **Keep PokéAPI flags as they are.** Unflagged Ultra Beasts and Paradox Pokémon are strong but ordinary under D38, which keeps the rule mechanical. Koraidon and Miraidon are flagged Legendary and stay Legendary (D57). |

D40's Candy wording was ambiguous ("one-step family"), and the research read it as "two
members". The requirements now spell out the intended depth-based rule; nothing changed.
