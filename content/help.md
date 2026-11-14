# How Pokéwalker works

**Walk by chatting.** Every word you write in this server's walking channels is a step. Your first 300 counted words in any hour give 1 step each; after that, each word gives 0.25 steps until your last hour drops back under 300.

**What counts.**
- Messages need at least 4 words; up to 20 words per message count.
- The same word counts at most 3 times in one message.
- After a counted message, wait 15 seconds before the next one counts.
- At most 30 words count per minute.
- Repeating a message within 30 minutes doesn't count.

**Encounters.** Every 100 steps a wild Pokémon appears. A ❗ on your message means one is waiting. You can hold up to 3; when your queue is full, steps still count but no new Pokémon appear.

**Catching.** Open `/walker` to see your encounters. Pick a ball and a berry, then **Throw**. Better balls and berries raise your chances; Pinap Berries give extra Candy instead. Pokémon can run away after a miss, but shinies and Legendaries never do. **Run** skips an encounter.

<!-- page -->

**Your companion.** Your starter walks with you and earns 1 Candy for its family every 150 steps. Change your companion any time from Storage.

**Growing stronger.** Candy and Stardust power up your Pokémon. Send spare Pokémon for research to get Candy back. Favorites, shinies and Legendaries are protected from bulk sending, and your companion can never be sent.
Evolution costs Candy and sometimes an item; pick your recipe and preview its target and CP before confirming. For Milcery, choose a sweet, then one of its nine creams.
Open a Pokémon's details to Evolve; use Expand storage in Storage for 50 more slots (5,000 Stardust) or Expand bag in Bag for 50 more units (2,500 Stardust), each up to 1,000.

**Routes.** Pick a route from `/walker`; each favors different Pokémon types. Refreshing Field and Noisy Forest are free; unlock more with lifetime steps in this server.

**Finds and check-ins.** Walking also finds items now and then. Use `/checkin` once an hour, 60 minutes after your last one. It always gives a Poké Ball plus one bonus item: a Great Ball, a Razz Berry, 2 Poké Balls, a Pinap Berry or, rarely, a Vitamin; an item that doesn't fit in your bag becomes 10 Stardust. It also queues one wild encounter if your queue has room; otherwise the reply says your queue is full. You can't check in while you're paused.

**Milestones.** Filling your Pokédex and catching special Pokémon earns reward bundles. Claim them from your inbox; see every milestone in the Pokédex.

Buy evolution items in Bag for 500 Stardust each, or use Buy & evolve on a missing-item preview; use the paged Convert picker to free space for Stardust.

**Shiny Lure.** Activate one from your bag for 4× shiny odds on your next 10 encounters.
**Shiny Charm.** Complete the Pokédex to earn it: 4× shiny odds on every encounter, stacking with a Shiny Lure. Turn it off or on in Bag.
**Star Piece.** Activate one from Bag for 1.5× Stardust on your next 10 catch or find Stardust rewards.

**Vitamins and Bottlecaps.** Use one from a Pokémon's details on its lowest IV: a Vitamin raises it by 1 and a Bottlecap raises it to the max, which can raise its CP and Appraisal stars. Neither works once all its IVs are perfect. Buy Vitamins in Bag for 5,000 Stardust each; Bottlecaps come from gym survivor rewards.
**Trade up.** In Bag, trade 2 Poké Balls for 1 Great Ball, or 2 Great Balls for 1 Ultra Ball.

<!-- page -->

**Gym defenders.** Deploy an eligible Pokémon, Recall it, or use Rewards to add unpaid full hours to your Inbox; recalling forfeits the survivor roll. A defender loses 0.1× battle HP each hour; Feed Razz Berry restores 0.5×, up to 2.0×, once every 10 minutes.

**Gym battles.** Pick one attacker, choose Clear only or claiming the gym with it, then Start; results and Battle log are private. You can battle again 5 minutes after your last battle.

**Defender time.** Gym defenders return automatically after 8 hours.

**World Legendary Ticket.** Use one from Bag and confirm to spawn a World Legendary here for 60 minutes; the ticket cannot be refunded.

**Join a World Legendary.** Use `/raid` while one is active here to join once; use it again to reopen your saved encounter.

**Trading.** In a trade channel, use `/trade member` to invite someone; they're pinged and join by using `/trade` with you as the member. Each of you offers one Pokémon, then both confirm. Favorites, your companion and gym defenders can't be traded. You can trade once per day, and Pokémon you receive count for your Pokédex.

**Your privacy.** The bot reads message text only to count words and never stores it. `/walker-account privacy` explains more; `/walker-account opt-out` stops the bot reading your messages.

Use `/readme` to see this again.

<!-- page -->

**Arena.** Open Arena from `/walker` and choose a fixed team of 3. Climb through three fights per floor: entry, middle and boss. Fight instantly, or heal before the next fight. HP carries between fights; berry healing uses Razz or Pinap Berries from your bag. A win revives fainted team members at 1 HP.

**X items.** X-Attack doubles every party member's attack; X-Defense doubles their defense. Each lasts 3 fights. Buy either for 300 Stardust each on the Arena home or break screen, and use held items during any break, including before the first fight. You can have one of each kind active at a time. Both work together; unused fights are lost when the run ends.

Skip up to half your best floor (at most 40 floors) when choosing a team. Skipped reward floors pay their tickets immediately, without first-clear bonuses or Candy.

Fight until hurt resolves fights in sequence without spending a berry. It stops when a member is below your threshold, is revived at 1 HP, a floor pays a ticket, or on defeat. A member already below the threshold will not fight; heal first or use Fight. Choose Stop below 10% through 90% (50% by default). Auto-order puts members with the highest HP percentage first before each chain fight, keeping ties in their current order. Changing a setting on another screen stops the chain; paused players can continue an existing run. The result lists every enemy fought and shows the party order left.

Each 18-hour run ends on defeat or expiry. The 18-hour cooldown starts when the run starts. Backing out does not pause the clock; Resume returns to the same enemy and team HP. Your team cannot change during the run, and later power-ups or evolutions do not change its saved stats.

**Arena rewards.** Each knockout gives Candy to the team member who dealt the final blow. Special Pokémon earn Candy only from boss knockouts. Boss wins at reward floors earn Bronze, Silver, Gold, Platinum or Diamond Tickets. Open Tickets in the Arena to see counts and contents, then confirm a redemption with at least one free encounter slot. Encounters join your queue; Stardust and item rewards wait in your Inbox. Tickets can be redeemed during a live run or while the server's Arena is off.

The monthly server leaderboard ranks your best floor fully cleared that month. Months reset on the 1st at 00:00 UTC. Ties favor whoever reached the floor first, then the older profile, then profile ID. Rewards need floor 10 or higher. 1st: Master Ball, Shiny Lure, World Legendary Ticket. 2nd: Master Ball, Shiny Lure. 3rd: Master Ball. Rewards wait in your Inbox, paid when anyone next opens the walker home, Arena, Leaderboard or Inbox after the month ends. Open Leaderboard in Arena for the top ten, your place, the reset countdown and last month's paid places, even while Arena is off.

A live Arena team member cannot defend or attack a gym, enter a trade, or be sent for research until the run ends. Other Pokémon remain available for those activities.

<!-- page -->

# Server setup (admins and moderators)

**Server gyms.** Members with Manage Server can create, remove and list gyms with `/walker-admin gyms`.

**Gym moderation.** Members with Moderate Members can use `/walker-mod gym-recall gym reason`; completed hours are paid, while exclusion forfeits unpaid hours.

**Server raids.** Manage Server can enable World Legendary spawns with `/walker-admin raids on` and a text channel, or disable them with `off`; raids start off.

**Server Arena.** Manage Server can use `/walker-admin arena on|off reason`; the Arena starts on. Turning it off blocks new runs while existing runs can finish and tickets can still be redeemed. A reason is required and the change is audited.

**`/walker-admin`** (needs Manage Server)
- `channels add|add-all|remove|list`: choose the walking channels where words count.
- `trade-channels add|add-all|remove|list`: choose the channels where members can trade.
- `gyms create|remove|list|legendary`: manage this server's gyms; legendary on or off allows or blocks Legendary and Mythical defenders (blocked by default).
- `arena on|off <reason>`: enable or disable new Arena runs in this server.
- `raids on|off <channel>`: turn World Legendary spawns on in a text channel, or off.
- `force-raid <reason>`: spawn a World Legendary in the raid channel now (once per 24 hours per server).
- `sharing on|off`: allow or block Share buttons in this server.
- `reset <member> <reason>`: permanently reset a member's game data in this server.

**`/walker-mod`** (needs Moderate Members)
- `pause`, `resume`: pause a member's earning, or lift the pause.
- `exclude`, `include`: block a member from this server's game, or reverse it.
- `share-ban`, `share-unban`: disable or restore a member's Share buttons.
- `gym-recall`: return a gym defender and pay its completed hours.
- `status`: show a member's game and moderation summary.
- `log`: show the last 25 moderation actions.
