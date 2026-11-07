# Discord gym design

Scope: B1–B2, B5, B7–B8. Checked **2026-11-04**. This is research and a proposed design, not an approved contract or implementation. Gyms belong to servers; their access channels, names and themes are administrator choices.

## Facts — platform and existing project inputs

- Discord application commands support guild contexts and `default_member_permissions`; administrators can use commands regardless of ordinary command restrictions. Command visibility can also be configured by roles, users and channels. [Official command documentation](https://docs.discord.com/developers/docs/interactions/slash-commands) — checked 2026-11-04.
- Discord distinguishes `MANAGE_GUILD`, `ADMINISTRATOR`, `VIEW_CHANNEL` and `USE_APPLICATION_COMMANDS`; channel overwrites affect effective permissions, while Administrator bypasses those overwrites. [Official permissions documentation](https://docs.discord.com/developers/topics/permissions) — checked 2026-11-04.
- The existing [progression proposal](../go-systems/README.md) supplies CP, family Candy, universal Stardust and protected Pokémon assignments. Its [economy interface](../go-systems/candy-transfer-evolution.md) reserves a gym reward hook with **zero rewards until a gym budget is defined**. This document proposes that budget without changing the earlier files. Project references checked 2026-11-04.

## Recommendations — proposed bot rules

**Every numeric setting below is a bot design default for playtesting, not a GO fact.** Use the global collection/resource scope recommended by task 2, with server-local gyms and activity attribution. Ownership scope remains an explicit project decision; do not mix global balances with independent per-server earning caps.

### 1. Teams and ownership

| Model | Advantage | Small-server tradeoff | Recommendation |
|---|---|---|---|
| GO's three fixed teams | Familiar identity and cooperative defense | Uneven membership can leave one side without viable opponents; membership changes become a balancing feature | Defer |
| Custom teams per server | Fits an existing community | Adds roster management, switching rules and administrator influence over competitive balance | Consider after the pilot |
| Individual holders | Every other eligible player can challenge; no permanent faction choice | Less cooperative identity | **Use for v1** |

Use **one defender per gym**, at most **one held gym per player in each server**, and **three deployed defenders per player globally**. A Pokémon can have only one assignment anywhere. Start a small server with **one or two gyms**; creating more does not increase anyone's reward cap. A solo player can claim/check in, but competitive battles require another holder.

Attackers select up to **three** available Pokémon. A win removes the defender and either installs the attacker's preselected defender or leaves the gym empty, as chosen before starting. Someone already at a holding limit can still choose **clear only**. There is no reaction-speed contest for the winner to press a claim button. [Battle rules](battle-system.md) define the simulation.

Return the original Pokémon when its assignment ends. Deployment does not change stored CP, level or IVs. While assigned, block research-send, evolution, power-up, another deployment and use in an attacking party. Favorites remain usable in battle; their research protection remains intact. Shininess provides no combat advantage.

### 2. Server setup and commands

Create no gyms automatically. A proposed initial service limit is **10 active gyms per server**, configurable by the bot operator; admins choose the number within that limit. Gym names are **1–32 characters**; themes are approved background/palette keys, with a neutral fallback. Defer arbitrary uploaded backgrounds and remote URLs.

| Admin command | Result |
|---|---|
| `/gym-admin create name theme channel` | Create an empty gym and its first access binding |
| `/gym-admin edit gym name? theme?` | Change presentation without resetting occupancy or reward history |
| `/gym-admin access add gym channel` | Add an existing same-server text channel |
| `/gym-admin access remove gym channel` | Remove a binding; preview consequences if it is the last one |
| `/gym-admin pause gym` / `resume gym` | Pause new actions and return its defender; resume empty |
| `/gym-admin retire gym` | Confirm retirement, return its defender and retain audit/history records |
| `/gym-admin list` / `rules` | Show configuration, access issues and the shared competitive/economy policy |

Use a separate, guild-only admin command root with a `MANAGE_GUILD` default permission. On **every mutation**, require the current guild owner, Administrator, or Manage Server permission; command visibility alone is not authorization. Read the guild ID from the interaction, and verify that every gym/channel record belongs to it. Do not accept a supplied guild ID as authority. The bot manages its own records; do not request Administrator, Manage Server or Manage Roles for this feature. Check its effective channel/attachment permissions before rendering and provide text when image delivery is unavailable.

Ordinary players use `/gyms`, `/gym view`, `/gym defend`, `/gym battle`, `/gym recall`, `/gym rewards` and `/gym history`. All replies are ephemeral. A gym may have several access channels, and a channel may expose several gyms. The user must have current channel access and permission to invoke commands; mutations also recheck the exact gym-channel binding. Initially support explicitly bound guild text channels only; no implicit category, forum or thread inheritance.

Only list gyms accessible from the invocation channel; do not reveal private channel names through errors. Administrators can inspect their server's complete configuration through the admin commands. Gym access does not automatically enable step counting: show both settings in the setup preview so admins can choose suitable counting channels.

A removed last binding, deleted channel with no remaining valid binding, retired gym or departed/banned holder returns the defender without a reward. Keep a personal **Storage → Recall** escape route for the owner even after channel access is lost. Never require access to a deleted server to release an assignment. Pause/retire operations confirm their effect, invalidate pending battle preparations, settle or abort reserved work safely, and retain an audit entry. These actions cannot mint global resources.

### 3. Activity-based fatigue and turnover

Use already-awarded steps from the shared anti-spam ledger, attributed to their source server. Do not recount messages or grant a second step budget.

| Setting | Proposed rule |
|---|---|
| Qualifying server day | A completed **UTC date** with at least **100 awarded steps** in that server |
| Fatigue advance | Add **one** for each qualifying date **after the deployment's UTC date**; placement day is excluded |
| Battle starting HP | `ceil(2 × canonical_HP × (1 − 0.1 × fatigue))` for fatigue **0–4** |
| Mandatory return | On the **fifth qualifying day**, return the defender before further battles |
| Quiet-server safeguard | Return after **seven real days** even if too few days qualified |
| Former-holder reclaim | The same player cannot defend that same gym for **24 hours** after any assignment end |
| Failed challenge | No persistent HP damage, extra fatigue or resource loss for the defender |
| Feeding / refresh | Defer berry feeding and lease refresh; owner activity does not reset fatigue |

These are **battle HP and assignment rules**, not CP decay. At fatigue 0/1/2/3/4, the defender has **2.0/1.8/1.6/1.4/1.2 times canonical HP** before rounding; at 5 it returns. Attack, Defense, stored CP and the original Pokémon's HP remain unchanged. All attackers also recover after a simulation; v1 needs no healing-item economy.

Example, **derived**: a Monday deployment in a server that qualifies every day accumulates fatigue Tuesday through Friday and returns after Saturday completes. A quiet server instead reaches the seven-day deadline. More chat beyond the day's threshold does not accelerate decay. This bounds the effect of an unusually active chatter while allowing inactivity cleanup.

Compute missed fatigue/expiry from persisted dates on startup and before reads/mutations; a stopped background worker must not grant extra tenure. Freeze the current fatigue in the battle snapshot. If a return, pause or revision change invalidates that deployment before settlement, abort settlement and release reservations rather than applying a stale win.

One-gym-per-server ownership, mandatory returns and the reclaim delay prevent one user from continuously occupying every gym. They do not guarantee evenly matched opponents; review battle completion, challenger success and vacant-gym duration during the pilot. Do not tune fatigue according to raw message volume or defender CP.

### 4. Rewards and economy boundary

Offer **50 Stardust per player per UTC earning date globally**, with both conditions met in the **same server and date**:

1. The player earned at least **200 awarded steps** there.
2. They claimed an empty gym, completed a valid battle against another player's defender, or checked in while holding a gym there.

Apply the shared participation-eligibility policy below to claims, battles, check-ins and reward qualification. Check-ins require a valid deployment. Losses and completed draws qualify; rejected starts, canceled previews and system aborts do not. Closing an accepted battle's panel is not cancellation.

Pay automatically when the second condition commits; `/gym rewards` shows receipts and retries an earned but unposted award. Battle participation uses the **settlement UTC date**; claims/check-ins use their successful commit date. An early action can qualify after more steps that same date. Later dates cannot complete an earlier date's eligibility, but an already-earned award does not expire: recovery can post it later against its original earning date. Two eligible servers still produce only one **50-dust** award. Uniquely constrain `(player_id, earning_date, gym_daily)`; late posting does not create another daily allowance.

There are **no additional rewards per win, knockout, defender, ownership hour, recall or raid**, and no Candy, coins, rare items or item-spin drops from gyms in v1. The earlier Star Piece proposal boosts catch/walking Dust only, so it does not multiply this award. Admin-created gyms cannot expand this budget. Cosmetic gym history can record distinct participation dates; defer win-based leaderboards and reward-bearing badges.

**Derived economy comparison:** the daily maximum is half the proposed **100-dust** ordinary catch reward and one-fifth of a proposed **250-dust** power-up step. Over 30 eligible days it adds at most **1,500 dust**, before any spending. The amount is deliberately a modest activity supplement; holding an uncontested gym does not generate unattended income. This is the proposed activation of task 2's reserved gym hook, not an already-enabled payout.

### 5. Abuse, fairness and failure boundaries

| Risk | Proposed control |
|---|---|
| Fresh disposable accounts | Claim/defend, battle, check-in and reward qualification require account age **7 days**, server membership **24 hours**, and **100 lifetime awarded steps in that server**. Read-only listing and owner recall remain available regardless of these gates |
| Battle spam | **One active attacking battle/player globally**, **one active battle/gym**; wait **10 minutes** after a completed rated battle before starting another, and at most **five starts/player/UTC day globally** |
| Collusive swapping | Rewards do not depend on winner or holder duration; preserve the global daily award and reclaim delay. Record repeated reciprocal transfers for review, without automatic accusations |
| Reset by leaving/rejoining or renaming | Retain eligibility, reward receipts and reclaim cooldowns by stable IDs; cosmetic edits do not reset state |
| Double clicks / multiple panels | One operation receipt and conditional version transition; a new interaction ID is not proof of a new intended battle |
| Cross-server farming | Global player, assignment and resource caps; attribute each accepted step to one guild; no server-admin currency settings |
| Resource/assignment races | Reserve the exact party, target deployment and any prospective holding capacity at Start; atomically settle battle, ownership changes and any eligible award |
| System crash or expired job | Resume the same stored inputs/result or abort; release locks and refund reserved start quota once, without reward or cooldown for a system abort |

Reserve start quota in the persisted **accepted-at UTC date** bucket; any refund returns to that same bucket, even after midnight. Invalid previews and busy-gym rejections consume none. A completed loss/draw counts; closing the panel after Start does not cancel or refund it. The cooldown begins at successful settlement. Expiry cleanup cannot refund an already-settled battle. The [battle document](battle-system.md) distinguishes a completed simulation-limit draw from a refunded processing-deadline abort.

Discord accounts are not verified individual people: these controls reduce incentives and bound costs but cannot establish an alt-free population. Do not collect IP addresses or device fingerprints for this hobby game. Keep only relevant account/member dates, credited-step totals and action metadata; do not copy chat bodies into gym history. Give moderators evidence and an appeal path before sanctions. The thresholds above need observation, especially in a newly formed server.

### 6. Schema sketch — extend the existing model

Reuse task 2's `Player`, `PokémonInstance`, `PokémonAssignment`, `StepCredit`, `DailyBudget` and transaction ledger. These are entity boundaries and invariants, not SQL or implementation code.

| Entity | Key fields / constraints |
|---|---|
| **GuildGymConfig** | `guild_id`; enabled; individual-control mode; operator ruleset version; config revision; default theme; administrative policy |
| **Gym** | `gym_id`, `guild_id`; name; theme key; active/paused/retired status; occupancy revision; created/retired timestamps |
| **GymAccessChannel** | Unique `(gym_id, channel_id)`; owning guild; channel kind; validity status; all references same-guild |
| **GuildGymActivityDay** | Unique `(guild_id, UTC_date)`; awarded-step aggregate; qualified flag; source-ledger watermark; no message text |
| **GymDeployment** | ID; gym/guild; owner; Pokémon instance; immutable snapshot ID; placed-at/date; processed-through date; fatigue; hard expiry; end time/reason; version |
| **BattleSnapshot / PartyMember** | Snapshot ID; instance/form/types, canonical combat inputs, `level_x2`, CP, shiny; move IDs/profiles and balance versions; ordered party slot; deployment fatigue. Reuse [task 2's stat contract](../go-systems/storage-and-data-model.md#inputs-the-later-gym-task-needs) |
| **GymBattle** | ID; guild/gym; challenger; target deployment/version; ordered snapshots; chosen post-win defender or clear-only; engine/ruleset versions; status; accepted/settled timestamps; `quota_date`; `participation_date`; deadline; deterministic result and bounded event log; settlement receipt |
| **ActivityReservation** | Owner operation; challenger/gym/Pokémon scopes; prospective guild/global holding slots for Claim mode; expected versions; expiry; uniqueness for active reservations; release/refund status |
| **PlayerGymDailyBudget** | Unique `(player_id, quota_date)`; accepted/reserved starts and original-bucket refunds |
| **PlayerGymState** | `player_id`; active attacking battle; last settlement; next-start-at, preserved across midnight. Defensive participation does not occupy the owner's attacking-battle slot |
| **GymParticipation / RewardReceipt** | Action ID; player/guild; committed participation date; qualifying action; same-guild/date step eligibility; `earning_date`, `earned_at`, `posted_at`. Receipt unique globally by player/earning-date/reward-kind; ledger amount and source action |
| **GymReclaimCooldown** | Unique `(gym_id, player_id)`; last deployment; next-defend-at; preserved after recall/rejoin |
| **GymAdminAudit** | Actor, guild/gym, action, before/after configuration revision, timestamp and reason; no credentials or message content |

Enforce one active deployment per gym and per `(guild, player)`, one assignment per Pokémon, and the global deployment cap transactionally; ordinary claims count prospective holding reservations. Recheck challenger membership/access and nominee ownership/eligibility at settlement. All battle/config lookups include the guild boundary. Ending a deployment and releasing its Pokémon assignment are one operation. A committed result is authoritative even if its ephemeral image fails to send; reopening History renders it again without re-awarding resources.

### Open decisions before implementation

- Confirm global collection ownership across tasks; this proposal builds on task 2's recommendation.
- Accept individual holders and one-slot gyms, or budget a separate team/cooperative design.
- Approve the proposed activity thresholds, reward amount, cooldowns and lease length after measuring the private-server pilot.
- Select a permitted, versioned move/stat/visual source as described in [move-data-sources.md](move-data-sources.md); no imported dataset is approved by these notes.
- Define moderation/retention policy and framework contracts before implementation. The planned external research review remains open.
