# Radar and dowsing

Scope: original Pokéwalker minigames and their proposed Discord equivalents. Every source below was checked **2026-11-04**. Citations attach that date to their associated facts. Proposed settings are balance choices, not historical mechanics.

## Facts — A4: Poké Radar

**Entry:** one use costs **10 W**; select the indicated patch among **four** before its marker disappears. Failure ends that use. Either Pokémon reaching zero HP ends battle without a capture. [Nintendo, pp. 37–38][N]

### Bush sequence

Selections may start battle early; **two distinct rounds show `!`**. [Bulbapedia][B]

| Round | Display | Possible group |
| --- | --- | --- |
| First | `!` | C |
| Second | `!` | C or B |
| Third | `!!` | B or A |
| Fourth | `!!!` | A |

Source: [B]. Wrong first-round choices do nothing; later errors lose the encounter. Exact deadlines in seconds and stage-transition probabilities: **UNVERIFIED**. [B]

### Battle

Both start with **4 HP**. Player actions: Attack/Evade/Catch; opponent actions: Attack/Evade/Flee. [The Cave of Dragonflies][C]

| Player / opponent | Result |
| --- | --- |
| Attack / Attack | Each loses 1 HP |
| Attack / Evade | Player loses 1 HP |
| Attack / Flee | Wild loses 2 HP; player loses 1 HP |
| Evade / Attack | Wild loses 1 HP |
| Evade / Evade | Staredown; no damage |
| Evade / Flee | Wild escapes |
| Catch / any | Capture check; failure ends encounter |

Source: [C]. Attack/Flee is critical; enemy choices depend on battle history. [C]

A failed throw makes the wild Pokémon flee; reducing it to zero also loses the capture. Losing the walking Pokémon costs up to **10 additional W**, beyond entry. [Serebii][S]

### Catch odds

Capture requires **three independent shake checks**, each with HP-only success chance `q`: `P(capture)=q³`. Species is irrelevant. [C]

| Wild HP | Per-check `q` | Capture `q³` |
| --- | --- | --- |
| 4 | 56% | 17.56% |
| 3 | 66% | 28.75% |
| 2 | 79% | 49.30% |
| 1 | 97% | 91.27% |

Rounded historical values. [C]

## Facts — A5: Dowsing

A use costs **3 W** and allows **two guesses** among **six tufts**. A first miss gives a hint. [Nintendo, pp. 37–38][N]

| Hint | Meaning |
| --- | --- |
| Near | Item is immediately left or right of the first selection |
| Far | Item is at least two positions away |

Source for both hints: [Serebii][S]. Finding another item when the three-item carrying space is full prompts replacement; it does not enlarge capacity. [S] Storage and gifts are detailed in [mechanics.md](mechanics.md).

Route data contains ten item slots with ordered step/chance checks. [Dmitry Grinberg][D] The more detailed public description checks stored order, skips step-ineligible entries, and uses a fresh random draw for each item. The first passing item wins; the final entry has zero required steps and weight 100. Preserve stored order: Treehouse is an exception to descending step thresholds. A slot's weight is therefore not its unconditional appearance percentage. [Altissimo][A] See [routes-encounters.md](routes-encounters.md) for the data contract.

**UNVERIFIED:** the exact moment the original firmware chooses item identity relative to the player's guesses. Do not infer this timing from the ordered selection algorithm.

## Recommendations — B4: Discord flows

### v1 radar: two component presses

**Proposed:** `/walker` opens the oldest queued encounter; two button presses follow the command. Its species, route and shiny outcome are already fixed at enqueue, as specified in [adaptation.md](adaptation.md).

1. **Reveal:** press the marked grass button to show the Pokémon. Other grass is decorative or disabled. Keep the recognizable radar presentation without a timed guessing test.
2. **Throw or Run:** Throw resolves capture using the displayed ball and cost; Run explicitly abandons this encounter. Display the outcome automatically. On a successful catch, commit storage and catch-resource rewards together. Either final outcome removes this encounter from the pending queue.

Both presses edit one ephemeral panel. Do not add a separate reward-claim confirmation. Use the separate inventory design for ball availability, spending and effects; never auto-select a Master Ball. Preparation is a **later** optional third press: choose one meaningful allowed item or Skip, showing its cost and effect before commitment. Original HP-based battle remains optional later work.

**Open balance contract:** the bot's capture probability, ball effects, available preparation and flee policy require explicit settings. Do not silently reuse the historical table, Pokémon GO coefficients, or main-series species catch rates. A probability shown to users must come from the same versioned policy used to resolve their throw.

### Dowsing: two or three component presses

**Proposed later feature:** a walking reward ticket opens **Start search**, followed by one or two spot selections. Number six buttons `1`–`6`; present two rows if useful, but define hints by numeric distance, with no wraparound.

- Freeze the reward ticket, hidden location and reward selection when Start is accepted. Apply item eligibility rules from the separate inventory design.
- A first hit ends the game. A first miss disables that location and displays **Adjacent number** or **At least two numbers away**, followed by one final selection.
- A final hit grants the saved reward once; a final miss consumes the ticket. Reopening keeps the same hidden location and guesses. Do not charge watts or additional steps on each press.

Choose the hidden location uniformly as a **proposed** rule. Hint accuracy and adjacency must be deterministic. Rare-item capacity checks belong in the final grant transaction; if capacity changed during play, preserve a pending claim or apply the separately documented overflow policy without rerolling rewards.

### Shared reliability and later battle

**Proposed:** only the encounter owner may act. Persist state, selected preparation, used guesses and terminal outcome; accept each transition once. Duplicate presses and stale panels return current state. A closed panel, connection failure or expired interaction is not a gameplay loss: `/walker` renders the saved state again. See [adaptation.md](adaptation.md) for Discord timing and queue rules.

A later battle mode could allow **at most two tactical turns**, then require Throw: Reveal → tactic → optional tactic → Throw is four presses. This proposed cap changes the original rules but bounds chat friction. Keep any display HP local to the minigame; CP remains the separate power system. Publish changed catch/flee rules before enabling this mode.

## Sources

- [N] Nintendo, *Pokémon HeartGold instruction booklet*, printed pp. 37–38; checked 2026-11-04.
- [B] Bulbapedia, *Pokéwalker*, Poké Radar section; checked 2026-11-04.
- [C] The Cave of Dragonflies, *Pokéwalker Battle Mechanics*, Basics and Throwing a Ball; checked 2026-11-04.
- [S] Serebii, *PokéWalker*, PokéRadar and Dowsing; checked 2026-11-04.
- [D] Dmitry Grinberg, *Pokéwalker*, route-data explanation; checked 2026-11-04.
- [A] Altissimo, *Pokéwalker Information*, Items; checked 2026-11-04.

[N]: https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/DS_Pokemon_HeartGold
[B]: https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9walker#Pok%C3%A9_Radar
[C]: https://www.dragonflycave.com/pokewalker/
[S]: https://www.serebii.net/heartgoldsoulsilver/pokewalker.shtml
[D]: https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker
[A]: https://altissimo1.github.io/Main-Series/HGSS/pokewalker.html
