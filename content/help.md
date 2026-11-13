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

# Server setup (admins and moderators)

**Server gyms.** Members with Manage Server can create, remove and list gyms with `/walker-admin gyms`.

**Gym moderation.** Members with Moderate Members can use `/walker-mod gym-recall gym reason`; completed hours are paid, while exclusion forfeits unpaid hours.

**Server raids.** Manage Server can enable World Legendary spawns with `/walker-admin raids on` and a text channel, or disable them with `off`; raids start off.

**`/walker-admin`** (needs Manage Server)
- `channels add|add-all|remove|list`: choose the walking channels where words count.
- `trade-channels add|add-all|remove|list`: choose the channels where members can trade.
- `gyms create|remove|list|legendary`: manage this server's gyms; legendary on or off allows or blocks Legendary and Mythical defenders (blocked by default).
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
