What this change does: The plan defines the v1 walking loop, with content import and economy measurement before application work. I reviewed all 15 linked tickets against the requirements and referenced local research, assuming one process serving a few hobby servers.

**MUST FIX**

1. **Onboarding has no session the router can authorize** — [M1.6.md:13](<docs/features/pokewalker-bot/tickets/M1.6.md:13>)

   **Problem:** Sessions are created only when a profile exists, and the router authenticates through that profile. A new player has neither, so their starter-selection and confirmation buttons cannot follow the specified routing path.
   
   **Suggested fix:** Create onboarding sessions with `guild_id`, `user_id` and an optional profile ID. Authenticate against those IDs, then attach the newly enrolled profile. Test onboarding through the actual router.

2. **Revealed encounters cannot be reopened** — [M1.7.md:12](<docs/features/pokewalker-bot/tickets/M1.7.md:12>)

   **Problem:** `open_encounter` selects only `queued` encounters, but Later preserves `state='revealed'`. After Later, dismissal or restart, that encounter is skipped permanently. This also breaks M1.8’s promised recovery after a failed Discord edit.
   
   **Suggested fix:** Select the oldest unresolved encounter across `queued` and `revealed`. Define queue occupancy using that same set. Test reveal → Later → reopen and reveal → restart → reopen without rerolling.

3. **Exclusion does not block the interaction paths** — [M1.6.md:17](<docs/features/pokewalker-bot/tickets/M1.6.md:17>), [M1.8.md:14](<docs/features/pokewalker-bot/tickets/M1.8.md:14>)

   **Problem:** The router checks ownership, expiry and revision, while Throw checks encounter ownership and state. Neither requires an exclusion check; the home screen merely displays an excluded notice. An excluded member can therefore continue using an existing catch screen, contrary to D31.
   
   **Suggested fix:** Require restriction checks on command entry and inside mutation transactions. Excluded members may use only privacy and delete-data. Test exclusion between opening a screen and pressing Throw, plus exclusion followed by deletion and attempted re-enrollment.

4. **The restriction result cannot represent simultaneous restrictions** — [M1.4.md:13](<docs/features/pokewalker-bot/tickets/M1.4.md:13>)

   **Problem:** `none | paused | excluded | share_banned` makes these states mutually exclusive. A member can be both paused and share-banned; returning either state loses information needed by the other handler.
   
   **Suggested fix:** Return independent restriction fields, including pause expiry. Test pause plus share-ban, then resume: earning should resume while sharing remains blocked.

5. **Run can overwrite a completed catch** — [M1.7.md:21](<docs/features/pokewalker-bot/tickets/M1.7.md:21>)

   **Problem:** Run unconditionally writes `state='ran'` under its own receipt. If screen A catches the encounter before screen B runs it, B’s session revision can still be valid and no Run receipt exists. The encounter becomes “ran” despite already awarding a Pokémon and resources.
   
   **Suggested fix:** Check encounter ownership, unresolved state and expected encounter revision inside Run’s transaction. Return the persisted terminal result when another action won. Add Catch/Run tests in both execution orders.

6. **Reaction cleanup happens too late and can race with addition** — [M1.7.md:12](<docs/features/pokewalker-bot/tickets/M1.7.md:12>), [M1.5.md:18](<docs/features/pokewalker-bot/tickets/M1.5.md:18>)

   **Problem:** D3 removes ❗ when `/walker` opens, but the ticket waits until `open_encounter`. Separately, a delayed reaction addition can complete after cleanup and leave an obsolete ❗.
   
   **Suggested fix:** Acknowledge the indicator when `/walker` opens. Persist its desired state and reconcile any addition already in flight. Test opening only the home screen, and opening while reaction addition is delayed.

7. **The milestone table omits required rewards** — [M0.3.md:26](<docs/features/pokewalker-bot/tickets/M0.3.md:26>)

   **Problem:** The enumerated contents omit “all 27 starters” and the nine region-completion milestones. They also specify four extra-bundle evolution lines, while D59’s table contains five, including Poipole. Building this list literally leaves earned rewards unavailable.
   
   **Suggested fix:** Include every D59 milestone category and all five extra-bundle lines. Add completeness assertions, including the required 340 qualifying families and exclusion of Phione/Manaphy.

**SHOULD FIX**

8. **The simulation’s top-pace scenario is constrained by hourly queue clearing** — [M0.6.md:14](<docs/features/pokewalker-bot/tickets/M0.6.md:14>), [M0.7.md:14](<docs/features/pokewalker-bot/tickets/M0.7.md:14>)

   **Problem:** Resolving the queue only once per hour limits generated encounters to three per hour, even when accepted steps could generate more. Using this result to assess D47’s top-pace ball shortfall understates demand and can mislead G-2.
   
   **Suggested fix:** Model frequent queue clearing for the top-pace scenario. Keep hourly checking as a separately labelled play style. Test that sufficient steps can produce more than three encounters per hour when slots are regularly freed.

9. **Companion progress is advanced without checking for a companion** — [M1.5.md:34](<docs/features/pokewalker-bot/tickets/M1.5.md:34>)

   **Problem:** The ticket unconditionally advances the companion meter for later consumption. D30 says companion Candy pauses when there is no companion. Banking those steps would let a subsequently selected companion receive credit for that interval.
   
   **Suggested fix:** Advance this meter only while a companion exists, preserving earlier partial progress. Add a no-companion interval test and a swap test that verifies which family receives the next Candy.

10. **The threshold test conflicts with the minimum message size** — [M0.5.md:41](<docs/features/pokewalker-bot/tickets/M0.5.md:41>)

   **Problem:** The specified `299 prior + 2 words → 125` case fails D33’s four-word minimum unless an earlier rate-cap truncation is explicitly part of the fixture. As written, correct rejection would fail the planned acceptance test.
   
   **Suggested fix:** Use 299 prior words plus four distinct eligible words, expecting 175 hundredths. Alternatively, explicitly construct the minute-cap case that accepts only two words from a valid message.

11. **The simulation dependency acceptance contradicts its required reuse** — [M0.6.md:11](<docs/features/pokewalker-bot/tickets/M0.6.md:11>), [M0.6.md:34](<docs/features/pokewalker-bot/tickets/M0.6.md:34>)

   **Problem:** The model must reuse `pokewalker.domain.steps`, which M0.5 builds with `regex`, but acceptance requires importing the model without any third-party import. This encourages unnecessary lazy imports or duplicated step logic just to satisfy the check.
   
   **Suggested fix:** Require an offline import/run with the approved locked dependencies installed. Retain the shared step implementation.

Verdict: Fix 1–7 before implementation.

Not checked: runtime behavior, live Discord or external dependency APIs; no files changed. These are plan defects, not observed application failures.
MUST=7 SHOULD=4 NIT=0