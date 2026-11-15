# EX-Gift — pre-plan synthesis

Status: **intake closed 2026-11-15; ready for planning** (started at `5a68d79`). The owner closed
intake and asked for a plan. Five review rounds (Codex `gpt-6-astra`) are applied, and the synthesis
and command loops both ended at 0 Must; see §9. No questions are open.

Labels: **[O]** is the owner's spec. **[R]** is a recommendation that fills a gap; the owner can
override it. **[Q]** is an open question for the owner. A **recorded reading** is Claude's
interpretation of an owner answer, kept until the owner confirms it.

## 1. Outcome

A new event-gift channel. Owners build gift packages in the admin server and send them to one server
or to every server. Enrolled players open them from a new **EX-Gift** submenu in `/walker`. Gifts can
carry ordinary items and a new **EX-item** type: event-exclusive consumables that regular gameplay
never grants.

## 2. Owner spec

### 2.1 EX-Gift inbox

- **EX-1 [O]** A new `/walker` submenu, **EX-Gift**: a special inbox for event items sent by owners.
- **EX-2 [O]** Items in an EX-Gift can only come from the admin server. No gameplay source grants them.
  *Reading:* gift packages come only from authorized admin sends, and gameplay never grants
  **EX-items**. Ordinary items keep their existing gameplay sources.
- **EX-3 [O]** Claiming an **ordinary** item from EX-Gift moves it to the regular reward inbox.
- **EX-4 [O]** **EX-items** stay in the EX-Gift inventory after claiming. That inventory has **no
  storage limit**, and EX-items are used from the EX-Gift menu.
- **EX-5 [O]** One gift can mix ordinary items and EX-items.
- **EX-6 [O]** Only players enrolled when the gift is sent receive it. Someone who enrolls later
  does not get it, and gifts are never queued for them.
- **EX-18 [O]** (Q5) Unclaimed gifts **never expire**.
- **EX-23 [O]** (Q7) There are **no notifications**. The `/walker` EX-Gift button shows **(!)** when
  a new gift has arrived. It shows **no count** of stored EX-items, unlike the inbox's (#).

**Recorded reading of EX-23:** (!) shows while the player has at least one unclaimed gift, and it
clears once every gift is claimed. Stored or armed EX-items never bring it back.

### 2.2 Sending (admin server)

- **EX-7 [O]** The send command targets either **all servers** or **one server by server ID**.
- **EX-27 [O]** (2026-11-15) A server-ID send then targets either **all users** in that server or
  **one user by user ID**. EX-6 still applies: the user must be enrolled in that server at send.
- **EX-8 [O]** A command opens a **gift manager** where an owner builds a package of up to
  **10 slots**. Each slot holds one item at **quantity 1**.
- **EX-9 [O]** Items are picked from a **dropdown**. The dropdown lists **every non-EX item** in the
  game and picks up new items automatically when they are added.
- **EX-10 [O]** A button in the item picker switches the list between ordinary items and EX-items.
- **EX-17 [O]** (Q1) Gifts carry **items only**: no Stardust and no candy. The ordinary list also
  includes **Arena Tickets** (Bronze, Silver, Gold, Platinum, Diamond) as giftable items.

### 2.3 EX-items

| ID | Item | Effect [O] |
|---|---|---|
| EX-11 | **Time Gear Fragment** | Resets all of the user's cooldowns. It does not touch the force-raid cooldown. |
| EX-12 | **Shiny Patch** | The user picks one Pokémon, which becomes shiny. |
| EX-13 | **Golden Bottlecap** | Maxes all three IVs of one Pokémon. |
| EX-14 | **EX-Attack** | The same ×2 boost as X-Attack, but for one whole Arena run (not a fixed number of fights). It does not stack with the regular X-Attack. |
| EX-15 | **EX-Defense** | The same as EX-Attack, for defense. It does not stack with X-Defense. |
| EX-16 | **Arena EX-Voucher** | Starts a run at **floor 81** straight away (amended by Q9 from 80) and grants every ticket reward for floors 1–80. It also unlocks the floor-40 skip. |

- **EX-19 [O]** (Q2) EX-Attack and EX-Defense are used from the **EX-Gift menu before a run**.
  Using one arms it for the **next Arena run started**. If the player has a paused run, the paused
  run does **not** get the boost: the EX-item stays armed for the next new run.
- **EX-20 [O]** (Q4) Voucher runs **count toward the monthly leaderboard**.
- **EX-21 [O]** (Q3) Using a Shiny Patch on a Pokémon that is already shiny is **refused with a
  message**, and the item is kept. The same applies to a Golden Bottlecap on a Pokémon whose IVs
  are already all 15.
- **EX-22 [O]** (Q6) EX-items **cannot be traded**.
- **EX-24 [O]** An EX-item that is used in a menu other than EX-Gift gets **its own button** in that
  menu. The button is shown **only while the player holds at least one** in the EX-Gift inventory,
  and it is **hidden** otherwise.

**Recorded reading of the Q4 "Yes"** (Q4 asked three things; the owner answered once). Voucher runs
count on the leaderboard. The voucher raises `arena_best_floor` to at least 80 whatever happens on
the run. It only starts a new run, so it obeys the Arena new-run cooldown.

- **EX-25 [O]** (Q8, 2026-11-15) The Time Gear resets **gameplay cooldowns only**: the six D67
  player cooldowns for the profile in the current server.
- **EX-26 [O]** (Q9, 2026-11-15) The voucher starts the run at **floor 81**, not 80.

**Recorded reading of EX-26:** The voucher pays floors **1–80** as real first clears would: one
ticket per scheduled floor, plus the first-clear copy where the floor is above the player's old
best. It sets `arena_best_floor` to at least 80, which unlocks the 40-floor skip. The run starts on
floor 81, so no floor is paid twice and no first-clear bonus is lost.

**EX-11 scope (EX-25):** "All cooldowns" means the six D67 player gameplay
cooldowns (check-in, gym battle, Razz Berry feeding, Arena new run, daily trade and trade invite
ping) **for the profile in the current server**. The anti-abuse limits stay in force: share
cooldowns (`bot/share.py:72`) and message step-credit limits (`domain/steps.py:66`).

## 3. Ground truth from the code (checked 2026-11-15 at `5a68d79`; round-1 corrections applied)

| Fact | Where | Consequence for EX-Gift |
|---|---|---|
| Admin commands are a guild-only `/admin` group. `authorize` checks `admin_guild_id` and `owner_ids`, applies a rate limit of 5 per minute, and refuses excluded owners. Restart rechecks exclusion inside its final writer transaction | `bot/admin.py:62`, `:141`; `contracts/discord-commands.md:690` | The manager and the send command are `/admin` subcommands. A multi-click manager needs more than the first `authorize` (R5). |
| D67 resets: `PLAYER` has six gameplay kinds, and `force_raid` is server-only. `reset` writes a `mod_audit` row whose reason is the cooldown choice | `services/cooldowns.py:3`, `:45` | The Time Gear reuses the reset **updates** but not the audit write. Player item use must not land in the retained moderation log (R6). |
| Other cooldown-like limits exist outside D67: share cooldowns and message step-credit limits | `bot/share.py:72`, `domain/steps.py:66` | These are anti-abuse limits, so the Time Gear leaves them alone (EX-11 reading). |
| "Enrolled" means a `profiles` row for (guild, user), per server (D10) | `migrations/0001_core.sql:13`; `docs/features/pokewalker-bot/README.md:33` | A player enrolled in two servers gets one copy per server. This is consistent with EX-6. |
| The reward inbox is `inbox_items(profile_id, milestone_id, resource ∈ item/stardust/candy, resource_id, remaining)` and cascades on profile deletion. Claim keeps rewards it cannot place (a full bag or an occupied rare pocket) in the inbox, with **no** conversion | `migrations/0004_milestones.sql:7`; `services/milestones.py:145`; `contracts/persisted-state.md` M2.6 | EX-3 inserts one `inbox_items` row per ordinary slot, keyed by the gift, with a readable label. Existing retention stays. |
| `items.grant` uses the profile's `bag_limit` (default 250, expandable to 1,000). It converts a duplicate rare-pocket item (Master Ball, Shiny Lure, World Legendary Ticket) to 500 Stardust | `services/items.py:20`; `migrations/0012_capacity.sql:3`; `capacities.json` | Gifts never call `grant` directly. Ordinary items go through the inbox, and EX-items go to their own uncapped table (EX-4). |
| Arena Tickets are not bag items. They live in `arena_tickets(profile_id, tier, quantity)` with no cap. `inbox_items.resource` does not allow them | `migrations/0025_arena.sql:22`; `migrations/0004_milestones.sql:11` | To keep EX-3, gifted tickets go through the reward inbox as a new `arena_ticket` resource. This needs a migration that rebuilds the `CHECK`, and Claim credits `arena_tickets` (R8). |
| Ordinary items come from several sources: conversion-rate items (`conversion_rates.json`, with `evolution_item` a placeholder), rare pockets (`capacities.json`, which adds `world_legendary_ticket`), 50 concrete evolution items (`content.json`), and Arena X-items `x_attack`/`x_defense` (`arena.json:186`), plus the five ticket tiers | as listed; `contracts/balance-tables.md:508` | There are **72** giftable ordinary entries today. No single file lists them all, so the catalog needs a defined union (R1). |
| A Discord select holds at most 25 options; a message has at most 5 action rows. The evolution items alone are 50 (27 sort to A–M) | Discord component reference; `bot/bag.py:104` | Every picker page holds at most 25 options (R1). |
| The Bottlecap and Vitamin raise only the **lowest** IV. `iv_items.apply` treats any item that is not `bottlecap` as Vitamin, and `held` reads only those two IDs | `services/iv_items.py:21`, `:31`, `:38` | The Golden Bottlecap reuses the CP and appraisal calculations and the preview layout, but it needs its own all-three-IVs calculation and an EX-inventory lookup. |
| Pokémon carry `shiny INTEGER CHECK(shiny IN (0,1))` and a `revision` column. Trade, research and evolution confirmations check the revision | `migrations/0001_core.sql:109`, `:119`; `services/trading.py:193` | Shiny Patch and Golden Bottlecap bump `revision`, so stale confirmations elsewhere are refused (R11). |
| X-items are **bought into inventory** for 300 Stardust (`buy_x`) and used during a run's breaks. Each one boosts ×2 for 3 fights through `x_attack_left`/`x_defense_left`, which count down | `services/arena.py:243`, `:339`, `:386`; `arena.json:186`; `migrations/0028_arena_x_items.sql` | A run-long EX flag on `arena_runs` replaces the countdown for that stat. Using the matching X-item is blocked while the flag is on (R9). |
| The skip is `min(best_floor // 2, 40)`. `start` rejects any skip above that, starts at `skip + 1`, and `skip_tickets(skip)` pays one ticket per scheduled floor in 1..skip **without** first-clear bonuses. Floor 80 is a Diamond floor | `domain/arena.py:115`, `:119`; `services/arena.py:139`, `:153`; `arena.json:152` | The voucher needs its own start path, because `start(skip=79)` is refused. Its reward boundary is floors 1–80, and the run starts at floor 81 (R12, EX-26). |
| A boss win updates `arena_best_floor`, writes `arena_month_scores`, and pays a floor ticket plus a first-clear copy when `floor > best_floor` and the tier is Silver or higher | `services/arena.py:366`–`:380`; `domain/arena.py:141` | Leaderboard scores come only from boss wins, so a voucher run scores from its first boss win, on floor 81 (EX-20). The voucher pays the first-clear bonuses for floors 1–80 itself before raising `best_floor` (EX-26). |
| The Arena team screen puts Prev/Next/Sort/Back on row 0, the team select on row 1, Clear/Start on row 2, and the Skip select on a later row. At maximum skip all five rows are used | `bot/arena.py:142`–`:170` | EX buttons go on row 2 with Clear/Start (5 buttons maximum), never a new row (R10). |

## 4. Recommendations

- **R1 [R] Item catalog and picker.** The ordinary catalog is built at runtime from the union in §3:
  concrete conversion-rate items without the `evolution_item` placeholder, rare pockets, every
  `content.json` evolution item, the Arena X-items and the five ticket tiers. It is deduplicated and
  excludes currencies. The picker groups items into categories (Balls, Berries, Rare, IV items,
  Arena, Evolution), and **every category is paged at 25 options or fewer**, with Prev/Next. A
  coverage test fails if any item the game can grant is missing from the catalog, so new items
  appear automatically (EX-9). The EX toggle (EX-10) sits with the category buttons.
- **R2 [R] Quantity.** Each slot holds quantity 1 (EX-8). Duplicate items in separate slots are
  allowed, so five Poké Balls take five slots.
- **R3 [settled by EX-17]** No Stardust or candy in gifts.
- **R4 [R] Delivery and claim model.**
  - A confirmed send is one immutable `ex_gifts` row: package, target, owner and a send ID. The send
    ID belongs to the **draft revision** and is created with it, so every confirm callback and retry
    for that revision carries the same ID. Its receipt is keyed by that send ID, so a second confirm
    or a retried click cannot deliver twice.
  - Every player operation (claim, use, arm, voucher start) has a stable operation key tied to the
    session and screen revision. It writes a profile-owned receipt and ledger lines in the same
    transaction as its effect. Authorization is checked before the receipt lookup. A replayed key
    returns the recorded outcome and repeats no effect.
  - Recipients are inserted in one set-based `INSERT … SELECT` from `profiles` in the target scope,
    inside the same writer transaction (the EX-6 snapshot). `(gift_id, profile_id)` is unique.
  - The send receipt is aggregate-only (counts, no recipient IDs). No Discord I/O happens inside the
    transaction.
  - Claim is one atomic `unclaimed → claimed` transition per recipient row. It moves the whole mixed
    package at once: ordinary slots into `inbox_items`, EX slots into the EX inventory. A second
    session claiming the same gift finds it already claimed and changes nothing.
  - EX-Gift lists are indexed by profile and paged, because gifts never expire (EX-18).
  - A representative fan-out benchmark (every enrolled profile) must stay well under the 5 s health
    probe (`bot/heartbeat.py:69`). If it does not, the plan batches without changing the snapshot.
- **R5 [R] Admin trust boundary.** A draft and its confirmation are bound to the owner who opened
  them, the admin guild, the package revision and the target. Every callback re-runs the owner and
  guild check; the commit re-checks exclusion inside the writer transaction, as restart does. The
  server validates item IDs against the catalog, 1–10 slots, quantity 1, that the target server
  exists, and for a one-user send that the user has a profile in that server. If not, the send is
  refused (like D67's `no_profile`) and nothing is written. Discord roles grant nothing. Before sending, a preview shows the server and recipient
  counts, marked provisional. After commit the bot reports the committed counts.
- **R6 [R] Time Gear record.** The Time Gear reuses the D67 reset updates through a shared helper
  that does not write `mod_audit`. It records its use in a profile-owned receipt and ledger line,
  which cascades with the profile.
- **R7 [settled by EX-20]** Voucher runs count. They score through normal boss wins, starting with
  floor 81.
- **R8 [R] Ticket gifts keep EX-3.** A migration widens `inbox_items.resource` to include
  `arena_ticket` (a table rebuild that keeps the existing rows). Claim credits `arena_tickets`, which
  has no cap, so ticket rows never wait. The inbox renders them as "Bronze Arena Ticket" and so on.
- **R9 [R] Armed EX boosts.**
  - Using EX-Attack or EX-Defense debits one from the EX inventory and sets a durable armed flag on
    the profile, in one transaction.
  - Arming while already armed is refused, and nothing is spent.
  - A successful new-run commit moves the flag onto the new `arena_runs` row. A failed or cancelled
    start leaves it armed. Resuming a paused run never reads it, and a restart keeps it.
  - An ended run never refunds an effect that has been consumed.
  - While a run has an EX flag, using the matching regular X-item in that run is refused, and the
    item is kept. Buying X-items stays allowed for later runs. Exactly one ×2 applies.
- **R10 [R] EX-24 placement.** These are extra entry points; every EX-item can still be used from
  EX-Gift (EX-4, EX-19).

  | EX-item | Other menu | Placement |
  |---|---|---|
  | Shiny Patch, Golden Bottlecap | Pokémon details | Next to Bottlecap and Vitamin (`bot/iv_items.py:34`), each with a preview and confirm. |
  | EX-Attack, EX-Defense | Arena team screen | Row 2, with Clear and Start. Hidden on resume. Once armed, the screen shows an "armed" line rather than the button. |
  | Arena EX-Voucher | Arena team screen | Row 2. It starts the run at floor 81 in place of a skip. |
  | Time Gear Fragment | None | EX-Gift only. |

  Using the voucher from EX-Gift opens the Arena team selection. The voucher is spent only when the
  start commits.
- **R11 [R] Pokémon effects are atomic.** Each Shiny Patch or Golden Bottlecap use checks
  ownership, owned state, the EX-21 refusals and the preview revision at commit. It applies the
  effect, debits the item and bumps `revision` in one transaction. The existing gym-deployed refusal
  for IV items applies to the Golden Bottlecap too. Live Arena team snapshots stay unchanged (AR-7).
- **R12 [R] Voucher start path.** The voucher has its own start path; normal skips stay validated
  as they are. It starts the run at floor 81, pays floors 1–80 as first clears (EX-26), raises
  `arena_best_floor` to at least 80, debits the voucher and obeys the new-run cooldown, all in one
  transaction.
- **R13 [R] Target population.** "All servers" means every persisted guild row. A one-user send
  (EX-27) is the single profile for (server, user). Recipients are all
  profiles in scope at commit. Restrictions (exclusion, opt-out) are enforced when the player claims
  or uses an item, not at send. Deleting and re-enrolling a profile never brings back an old gift.

- **R14 [R] Command shape.** `/admin gift scope:<all|server> [server_id] [user_id]` opens the
  manager. `all` takes neither ID. `server` requires `server_id`, and no `user_id` means every
  enrolled user there (EX-27). Every other combination is refused privately, and nothing is
  written. IDs are strings checked with `config.snowflake`, the way D67 does it (`bot/admin.py:160`,
  `:183`). An unknown server or a user with no profile is refused, as in D67. The new commands are
  synced to the admin guild only.
- **R15 [R] Manager layout** (fits discord.py 2.7.1, as pinned):

  | Row | Contents |
  |---|---|
  | 0 | Five category buttons |
  | 1 | The sixth category, EX toggle, Prev, Next |
  | 2 | The item select (at most 25 options) |
  | 3 | The slot select (choose a slot to remove) |
  | 4 | Remove, Clear, Preview, Cancel |

  That is five rows and 15 components. The preview has Confirm, Edit and Cancel (one row), and the
  final receipt has no components. Picking an item adds it to the next free slot, and duplicates
  are allowed (R2). With 10 slots full, the item select is disabled. With 0 slots, the slot select
  is **omitted** (an empty select is an invalid payload, as `bot/bag.py:111` already handles), so
  the screen is 4 rows and 14 components, and Preview is disabled. Remove stays disabled until a
  slot is selected. Changing the category or the EX toggle goes back to page 1.
- **R16 [R] Draft lifetime and states.** Drafts are temporary and held in memory, and discarded on
  restart.
  - Each draft has an **absolute deadline 15 minutes after it is created**. Edits and previews do
    not extend it. The view timeout is set to whatever time is left. Expiry is checked again before
    commit.
  - Each callback acknowledges **its own** interaction within 3 seconds and replies with that
    interaction's token.
  - States run `editing → sending → sent`. Confirm moves the draft to `sending` before waiting on the
    writer. While `sending`, Edit and Cancel are refused. A commit makes it `sent` for good, and any
    retry or stale preview click returns that same send. A confirmed rollback (nothing committed)
    goes back to `editing` with the same revision and send ID.
  - Deleting a profile drops every in-memory draft that targets that user. Only committed sends are durable. An
  expired draft cannot be confirmed. Every screen and refusal is ephemeral, with mentions
  suppressed. Callbacks are acknowledged before waiting on the writer.
- **R17 [R] Callback checks vs rate limits.** Every callback, history pages included, checks the
  owner, the admin guild and current exclusion. There are two buckets, both **per owner and
  process-wide**, shared by every open draft:
  - the existing 5-per-minute `authorize` bucket: running `/admin gift`, running
    `/admin gift-history`, and Confirm;
  - a 30-per-minute callback bucket: item and slot picks, Remove, Clear, categories, the EX toggle,
    Prev/Next, Preview, Edit, Cancel and history paging. Building a 10-slot package fits easily. A refused callback changes nothing.
- **R18 [R] Preview contents.** The preview shows the **send ID**, the scope, the exact target (the server ID, and
  the user ID for a one-user send), every slot, and the provisional counts: targeted servers,
  servers with recipients, and recipients. A send with zero recipients is refused, and no gift is
  created. Restricted profiles are still included, as R13 says.
- **R19 [R] History and cancel.** `/admin gift-history` lists the owner-visible sends, paged: send ID,
  time, scope and server, package and committed counts, with no recipient lists. This is how an
  owner checks whether a send landed after losing the acknowledgement, without sending again.
  The owner looks it up by the exact send ID shown in the preview (R18) and in the receipt.
  Cancel discards only an uncommitted draft. Revoking a gift after it is sent is **deferred**: the
  owner spec does not ask for it, and it would need rules for items already claimed.
- **R20 [R] Retention.** `ex_gifts` is the owner-side send audit: send ID, the **sending owner's
  ID** (kept for accountability), commit time, package, scope and server, and committed counts. It
  never holds a **recipient** ID, including for a one-user send. A recipient exists only in a
  profile-owned recipient row, which cascades on deletion. Drafts targeting that user are dropped
  (R16). EX-Gift adds no recipient ID to receipt keys, payloads, logs or `mod_audit`. Existing
  retention contracts (moderation audit, deletion markers) are unchanged.

## 5. Contract and migration impact

| Contract | Amendment |
|---|---|
| C3 `persisted-state.md` | New tables: `ex_gifts`, recipients and EX inventory. Arming flags on `profiles`, EX flags on `arena_runs`. The `inbox_items.resource` rebuild. Receipt ownership (profile-owned use receipts, an aggregate send receipt). M2.6 inbox, M4.1 deletion/replay, IV mutations, the Arena lifecycle (voucher start, X/EX effects, monthly scores) and D67 reuse. |
| C5 `discord-commands.md` | `/admin gift` (R14–R18) and `/admin gift-history` (R19). The `/walker` EX-Gift screen and its (!). EX buttons on Pokémon details and the Arena team screen. Private-session rules, and the M4.5a owner-administration rules. |
| C4 `balance-tables.md` | EX-item definitions, the giftable catalog rule, and the Arena voucher and EX rules. |
| C1 / C2 | C1 only if the content artifact structure changes. C2 only if the Time Gear reading is widened to step limits (it is not, by default). |

New numbered migrations keep existing data, and new effect columns default to off.

## 6. Acceptance cases the plan must cover

- Duplicate slots in one package; a 10-slot mixed package.
- Two sessions claiming the same gift; a lost acknowledgement followed by a retry; a rollback mid-claim.
- A retried send; a forged or other-owner callback; an owner excluded after preview.
- Every invalid scope/ID combination; the command parameter manifest.
- The full manager screen at 10 slots and at 0, checking the serialized payload after opening, Clear, and removing the last slot; removing and clearing slots; paging resets.
- A draft expiring; a restart before confirm; a restart after commit; recovering a send through `/admin gift-history`.
- Throttled edits and confirms; exclusion after opening and after preview; a zero-recipient send.
- After a one-user recipient's profile is deleted, no EX-Gift table, receipt or log holds their ID, while the sending owner's ID stays in `ex_gifts`; an owner sending to themself.
- Confirm racing Edit or Cancel; a lost response after commit followed by a stale preview click; two identical one-user sends where only one commits, recovered by send ID.
- A draft past its 15-minute deadline while in active use; several drafts and history sharing one owner's rate buckets.
- A one-user send to an enrolled user, to an unenrolled user ID, and to a user enrolled only in another server.
- Deleting, re-enrolling and restoring a profile, and a member prune, with gifts and EX-items held.
- A stale Pokémon preview after a trade, research or evolution; EX-21 refusals; a gym-deployed target.
- The voucher pays floors 1–80 (with and without an earlier best floor) and starts at 81; the voucher at maximum skip; a voucher run's first boss win scoring.
- A restart while armed; arming with a paused run; using a matching X-item during an EX run.
- The largest picker page (25 options) and the full Arena team screen with EX buttons.
- A global send at production scale, measured against the health probe.

## 7. Open questions for the owner

Answered: Q1 → EX-17, Q2 → EX-14 and EX-19, Q3 → EX-21, Q4 → EX-20, Q5 → EX-18, Q6 → EX-22,
Q7 → EX-23, Q8 → EX-25, Q9 → EX-26.

No questions are open.

## 8. Intake log

| Date | Input |
|---|---|
| 2026-11-15 | Initial spec: EX-Gift inbox, gift manager, six EX-items (EX-1..EX-16). |
| 2026-11-15 | Answers Q1, Q2, Q4, Q5: items only plus Arena Tickets (EX-17), no expiry (EX-18), EX boosts armed for the next new run (EX-19), voucher runs count on the leaderboard (EX-20). |
| 2026-11-15 | Answers Q3, Q6, Q7: refusals for a shiny or already-perfect target (EX-21), no trading (EX-22), (!) badge with no count (EX-23). |
| 2026-11-15 | EX-items used in other menus get their own button there, shown only while held (EX-24). |
| 2026-11-15 | Answers Q8, Q9: the Time Gear resets gameplay cooldowns only (EX-25); the voucher starts at floor 81 (EX-26). |
| 2026-11-15 | A server-ID send targets all users or one user ID (EX-27). |
| 2026-11-15 | The owner closed intake and asked for a plan. |

## 9. Review log

| Round | Reviewer | Must | Should | Nit | Result |
|---|---|---|---|---|---|
| 1 | Codex `gpt-6-astra` | 10 | 10 | 0 | All 20 accepted and applied. Q8 and Q9 opened. |
| 2 | Codex `gpt-6-astra` | 0 | 1 | 0 | 19 of 20 round-1 fixes verified. The one Should (send-ID stability and player operation receipts) is applied in R4. Loop stopped: Must = 0. |
| 3 (command) | Codex `gpt-6-astra` | 2 | 5 | 1 | All 8 accepted. Added R14–R20 and an EX-2 reading. |
| 4 (command) | Codex `gpt-6-astra` | 1 | 4 | 0 | All 5 accepted. R16 gets an absolute deadline and draft states, R17 per-owner buckets, R18/R19 recovery by send ID, R20 owner vs recipient retention. |
| 5 (command) | Codex `gpt-6-astra` | 0 | 1 | 0 | Accepted: the empty manager omits the slot select (R15). Loop stopped: Must = 0. |
