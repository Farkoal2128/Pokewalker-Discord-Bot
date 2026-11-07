# Asynchronous gym battles and presentation

Scope: B3–B4 and B6. Checked **2026-11-04**. This is a proposed battle design, not an implementation or an exact GO simulator. Reuse [task 2's CP inputs](../go-systems/cp-ivs-leveling.md#inputs-to-reserve-for-future-gyms) and [resource model](../go-systems/README.md) unchanged. [Server gym design](discord-gym-design.md) owns deployment, fatigue, eligibility, cooldown and reward rules.

## Facts

- **Discord:** an interaction needs an initial response within **3 seconds**; its continuation token is valid for **15 minutes**. Discord supports deferred responses and subsequent edits, including ephemeral replies. Token expiry is a response limitation, not a documented game-state lifetime. [Official interaction documentation](https://docs.discord.com/developers/interactions/receiving-and-responding) — checked 2026-11-04.
- **Community GO model:** the published GO Hub damage calculator uses move power, combat stats and type-related modifiers, rounds damage down, then adds **1**. It explicitly excludes several special mechanics. It is not a specification of every current server rule. See [GO gym mechanics](go-gym-mechanics.md) for the fuller evidence and uncertainties. [Calculator documentation](https://db.pokemongohub.net/tools/breakpoints) — checked 2026-11-04.

## Recommendations — bot rules, not GO facts

Every number below is a **proposed default** or a labeled calculation. Balance examples are not observed player outcomes.

### 1. Choose automatic simulation for v1

Use **one defender against an ordered party of one to three attackers**. The attacker chooses counters, order and the desired ownership outcome before confirming. The service resolves the fight against an immutable defender snapshot and returns one result. The defender's owner need not be online.

| Option | Player decisions | Discord interaction cost | Tradeoff |
|---|---|---|---|
| **Automatic simulation — recommended v1** | Party/order; clear-only or nominated post-win defender | **3–6** for a fresh party; **2** with a valid saved party and displayed default outcome | Predictable completion, small UI surface, easy recovery; strategy concentrates on preparation |
| Interactive turns — later option | Preparation, then Fast / Charge / Dodge / Switch | Illustrative **15–30**, derived below; more without a decision cap | More tactical agency, but repeated clicks, abandoned turns, stale controls and longer reservations |

Do not add cosmetic “aggressive/defensive” stances without distinct, tested policies. V1 uses a visible **charge-when-affordable** policy for both sides. Deterministic outcomes make counter selection understandable; players cannot reroll a favorable result by repeating the same battle.

### 2. Private preparation and result flow

1. **Open:** `/gym battle gym:<name>` in an allowed channel shows its current holder, defender, canonical CP, battle HP/fatigue, types and move profile. Load the saved attacking party when available.
2. **Choose party:** select **one to three distinct Pokémon instances**, in displayed order. Show their CP, types, moves and assignment availability. A deployed defender cannot also attack. Favorite/lock status alone need not prohibit a non-destructive battle.
3. **Choose outcome:** **Clear only** or **Claim with [party member]**. Make the choice explicit in the final preview; a saved preference may preselect it. Check ownership caps and assignment eligibility before Start. A player already at a holding cap can still choose clear-only when otherwise eligible.
4. **Confirm Start:** revalidate actor, guild/channel, exact Pokémon versions, current gym/deployment revision and the shared limits. Atomically accept the battle and reserve its required state. A stale preview returns an updated preview; it does not silently fight a different defender. An empty gym uses the separate claim flow rather than a synthetic victory.
5. **Result:** show win/loss/draw, the resulting holder, party survivors, decisive move events and any participation reward actually committed. **Battle Log** opens the saved narrative; **Close** dismisses the view. Victory and the preselected claim commit together, avoiding a race to click “claim” afterward.

**Derived click budget:** one command + **1–3** party-slot selections + **0–1** outcome selection + one Start = **3–6 interactions**. A valid saved party/outcome needs only the command and Start. Paging, changing order or opening the optional log adds interactions; these counts are not Discord limits or measured averages.

### 3. Small, explicit simulation contract

Use the [move-source recommendation](move-data-sources.md): a compact **bot-balanced** roster with one fast and one charged profile per enabled form. Record `source_mode=bot`; display the values as this bot's rules. Exact GO move timing and learnsets require a separate approved data decision.

| Element | Proposed v1 rule |
|---|---|
| Stats | Read canonical Attack, Defense and HP derived by task 2; **never use a CP ratio as damage** |
| Attacker starting HP | Its canonical maximum HP; all bench members begin healthy |
| Defender starting HP | `ceil(2 × canonical_HP × fatigue_factor)`; the factor comes from the gym design and is frozen at Start |
| Stored Pokémon | CP, level, IVs and canonical HP are unchanged by deployment fatigue or battle damage |
| Energy | Each entering Pokémon starts at **0**; cap **100**; no energy from taking damage |
| Fast template | Power **6**, grants **10 energy**, duration **1 tick** |
| Charged template | Power **60**, costs **50 energy**, duration **2 ticks** |
| Move types | Explicit, versioned form-to-profile mapping; never infer GO move legality from a main-series learnset |
| Damage timing | Apply damage at move completion; pay charged energy when the move starts; gain fast energy on completion |
| Action policy | At each ready point, use charged if affordable; otherwise fast. Identical policy for attacker and defender |
| End bound | At most **120 virtual ticks**, including all attacker substitutions; then a **completed draw** with no ownership change |

A tick is an **abstract simulation unit**, not a wall-clock second or a requested Discord edit. These two templates are starting balance values, not extracted GO attacks. Species-specific exceptions, additional charged slots, move unlocking and TMs are deferred.

Select this damage rule, based on the ordinary model discussed in [GO gym mechanics](go-gym-mechanics.md):

`damage = floor(0.5 × power × attack / opposing_defense × STAB × effectiveness) + 1`

Use **STAB 1.2** when the move matches either attacker type, otherwise **1**. Use the versioned GO-style type factors **1.6** for weakness, **0.625** for resistance and **0.390625** for a main-series immunity; multiply factors across both defending types. Weather and other external boosts are **1** in v1. Do not add critical hits, random damage spread, shields, stat stages or a PvP-specific multiplier. Pin numeric precision and rounding with the engine version.

**Derived check:** with equal combat Attack/Defense, matching-type attacks and neutral effectiveness, the proposed fast template deals `floor(0.5×6×1.2)+1 = 4`; charged deals `floor(0.5×60×1.2)+1 = 37`. Five completed fast moves fund one charge; that cycle takes **7 ticks**, produces **57 damage** and requires no live clicks in automatic mode. This checks the stated arithmetic, not overall balance.

**Event order:** start ready actions together; advance to the next completion tick; calculate all hits due then from the state immediately before that tick and apply them simultaneously. A move from a Pokémon already fainted on an earlier tick is canceled. Resolve KOs, then substitute the next attacker immediately without an extra tick; its energy starts at zero. The defender retains its in-battle HP/energy between attacker substitutions. Pending attacks target the opposing active slot, so a later hit can strike a replacement.

The attacker wins if the defender faints and at least one party member remains healthy after that tick. If both sides have no healthy Pokémon, record a draw. Process completions through tick 120 only; if neither side has won then, record a completed draw with reason `tick_limit`. Losses and draws retain the holder, consume start quota, apply cooldown and can qualify as daily participation. A failed challenge leaves no persistent HP damage or extra fatigue. Discard combat-local damage/energy afterward; the nominated party member can deploy fresh even if it fainted during the winning battle. No healing item is consumed.

### 4. A concrete interactive alternative

If later playtesting warrants turns, pause the same engine whenever the active attacker is ready. The defender remains automated. Candidate buttons are:

| Choice | Proposed effect |
|---|---|
| **Fast** | Commit the one-tick move; damage/energy at completion |
| **Charge** | Enabled only with sufficient energy; one click commits the full two-tick action |
| **Dodge** | Spend one tick; reduce the next hit landing during that tick to `max(1, floor(damage/4))`; no damage/energy gain |
| **Switch** | Spend one tick to bring in an available bench member; preserve each member's battle HP/energy |

These dodge/switch rules are **future bot proposals**, not GO timing claims. Show the defender's already-committed action before requesting a choice; it cannot choose in reaction to a button it should not yet know. Pending damage hits the currently active slot at completion. Later implementation must define whether switching permits temporary absence; the recommended answer is no.

**Derived workload example:** ten Fast choices fund two Charges, totaling **12 battle decisions**. One or two such attacker sequences give **12–24 decisions**, plus **3–6** setup interactions: **15–30**. This is an illustrative planning range, not a measured “typical battle.” Require a user-study check before adopting it. A possible usability bound is **24 player decisions**, then finish automatically; after **30 seconds** without input, auto-complete rather than holding the gym indefinitely. Such live turns are deferred from v1.

### 5. Persistence, concurrency and recovery

- **One accepted battle, one outcome.** A preview/Start nonce identifies the logical action; different Discord interaction IDs from double-clicks must not create separate battles. Enforce the player/gym concurrency and daily limits in [server gym design](discord-gym-design.md), not only disabled buttons.
- Snapshot participant IDs/versions, form/types, canonical stats, CP, move profiles, order, nominee, fatigue, gym/deployment revision, and all relevant ruleset hashes. Store ordered events and the engine version. V1 is deterministic and needs **no RNG seed**; a future randomized mode must add a stored seed and versioned PRNG.
- Protect the participating instances and defender deployment from conflicting transfer, upgrade, evolution or assignment mutations. Claim mode also reserves the prospective `(guild, player)` holding slot and one global deployment slot; other claims count those reservations. Recheck capacity atomically at settlement; never silently change Claim into Clear-only. Simulation occurs outside a long database transaction; a leased worker with a fencing token prevents duplicate commits.
- Set a proposed **60-second absolute processing deadline** from acceptance to settlement, distinct from the 120 virtual ticks. Restarts/retries preserve it. At expiry, atomically abort unsettled work, release reservations and refund its original `quota_date` bucket once, without reward or cooldown. A stale worker cannot commit afterward; an already-settled result cannot be refunded.
- Commit the result, old defender's return, optional new deployment, assignment release and any eligible participation receipt atomically. A changed/deleted gym, invalidated deployment, lost reservation, revoked challenger membership/access or invalid nominee causes a system abort. Participation uses the settlement UTC date; start quota/refunds use the acceptance UTC date. Persist both, as specified in the shared design.
- Canceling a **preview** has no gameplay effect. After Start, closing the UI does not cancel the accepted simulation. Restart recovery resumes the same snapshot; missing pinned rules or unrecoverable work aborts without awarding a result. Rendering failures cannot roll back or repeat a committed outcome.
- Acknowledge/defer the interaction before simulation or image rendering. Recover via a fresh `/gym` view when the old response token expires. Persist no Discord interaction tokens in battle history. Recheck viewer authorization when serving results or logs.

### 6. Battle display

Use one static matchup preview and one result image; the renderer consumes saved battle data and approved cached artwork. It never decides damage or fetches gameplay data. A missing sprite falls back to a silhouette plus species/form name; an unavailable renderer returns the same result as text.

| Display element | Required information |
|---|---|
| Header | Server gym name/theme, holder, attacker, result/state |
| Combatants | Sprites, species/form, shiny text/icon, canonical CP, type labels; attacker bench/order |
| HP | Numeric current/max values plus bars; defender's battle HP multiplier/fatigue visibly distinguished from stored CP |
| Energy and moves | Energy amount, selected fast/charged labels and types; threshold indicators |
| Short log | Opening matchup, important charges, substitutions/KOs and final outcome; optional full text log |
| Footer | Resulting ownership, participation reward actually received, battle ID; no implied reward for every KO |

Keep foreground contrast high and theme backgrounds decorative. Do not convey types, shininess, HP or winners through color alone. Supply a concise text result and attachment description so the battle remains understandable without the image. Full hit-by-hit rendering, animation, public battle spam and raids are outside v1.

### Open decisions before implementation

- Approve the supported form/profile roster and test whether three attackers versus doubled defender HP produces useful counterplay across low/high CP and defensive species.
- Check tick-limit, simultaneous-KO, substitution, stale-preview and crash-recovery examples against the eventual contract; no executable simulator or tests were produced by this research.
- Measure the proposed click counts and readability in the private-server pilot before considering interactive turns.
