# C7: deterministic gym battle engine

## Purpose and requirements

Implements D32/D35 and PLAN Q6 using the approved bot-owned templates in
`content/balance/battle.json` and `docs/research/gyms/battle-system.md` section 3.
Producer: `pokewalker/domain/battle.py`. Consumers: M7.6a gym service and M7.6b
screens. This is an additive boundary, with no persistence or existing callers.
Eligibility, legendary defender restrictions, ownership and rewards belong to the
service; this engine never mutates stored Pokemon or injected data.

## Inputs and outputs

- Frozen `Combatant(name, types, attack, defense, hp, fast_type, charged_type)`:
  nonempty single-line name, one or two distinct type names, finite positive combat
  Attack/Defense, positive integer canonical HP. Types are copied to a tuple.
- `combat_stats(base, ivs, level_x2, multipliers)` reuses CP validation and returns
  unrounded `(base_attack + iv_attack) * cpm`, similarly Defense, and canonical
  `max(10, floor((base_stamina + iv_stamina) * cpm))` HP.
- `defender_hp(canonical_hp, hours_held)` takes positive integer HP and integer full
  hours, clamps hours to 0..7 and computes `-(-hp * (20 - h) // 10)` exactly.
- `effectiveness(move_type, defender_types, chart)` multiplies injected chart
  factors in defending-type order. Neutral is 1; double weakness is 1.6 * 1.6.
- `damage(power, attack, defense, stab, eff)` uses Python binary64 operations in
  precisely this left-to-right order: `floor(0.5 * power * attack / defense *
  stab * eff) + 1`. No intermediate rounding. Inputs are finite and positive
  (power may be zero). Equal stats, STAB 1.2, neutral: fast 4, charged 37;
  five fast completions and one charge complete at tick 7 for total damage 57.
- `simulate(party, defender, defender_battle_hp, *, rules, chart)` accepts 1..3
  ordered Combatants and positive integer frozen defender battle HP. Rules and
  chart are trusted reviewed decoded payloads (not file paths). Unknown combatant
  types raise ValueError. Invalid public stat/party/HP inputs raise ValueError.
- Frozen `Result(outcome, reason, ticks, survivors, events, engine_version)`:
  outcome `win|loss|draw`; reason `defender_fainted|party_fainted|tick_limit`;
  survivors is a tuple of zero-based original party positions still healthy,
  including unused bench members; events is a tuple of at most 40 single-line
  strings. Result carries `engine_version == ENGINE_VERSION == "1"`.

## Tick and energy invariants

At tick 0 both active sides have zero energy and start ready actions together.
At each readiness point charge if affordable, otherwise fast. Pay charged energy
at start; gain fast energy at completion, capped at the injected energy cap (100).
Advance to the next completion; calculate both due hits against the state before
that tick, then apply simultaneously. STAB applies only when that move's own type
belongs to its user's types. No energy is gained from incoming damage.

Resolve KOs after all due hits. Cancel unfinished moves from fainted users; replace
a fainted attacker immediately, with no elapsed tick and zero energy. The defender
keeps HP, energy and any pending action. Hits target the opposing active slot at
completion, never a captured original target. With this two-side, single-action
model, a defender's KO-causing completion itself ends its pending action; the next
hit targets the replacement. No extra damage source is introduced to manufacture
an otherwise unreachable pending-defender-hit-across-substitution case.

A fainted defender and any healthy party member (even bench only) gives `win` /
`defender_fainted`. Both sides exhausted gives `draw` / `defender_fainted`.
Party exhausted while defender lives gives `loss` / `party_fainted`. Process all
completions through tick 120 inclusive; if still unresolved, return `draw` /
`tick_limit`, ticks 120. No completion beyond the injected limit is applied.

Events preserve the first 39 opening/completion/KO/substitution lines plus the final
outcome line; truncation affects narrative only. Simulation has no I/O, clock or
RNG calls, and repeated equal inputs produce equal results without modifying inputs.

## Compatibility, verification and change policy

Tests: `tests/test_battle.py` covers arithmetic, determinism, STAB/type products,
D32, simultaneous KO, cancellation, immediate substitution, slot targeting,
120-tick boundary, survivor eligibility, immutable inputs and bounded text events.
Changes to arithmetic order, timing, result meanings or deterministic outcomes
require a deliberate requirement/contract review and a new engine version. The
future service must persist ordered events and engine version with its snapshot;
this row introduces no stored format or migration and can be rolled back by
removing the unused provider, contract and tests together.
