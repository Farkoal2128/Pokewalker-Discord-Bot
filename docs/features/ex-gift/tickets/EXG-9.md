# EXG-9 — EX-Gift screen with Claim

**Tier:** seam (interaction responses; persisted state)

**Read:** PLAN D6, D7, D8; SYNTHESIS EX-1, EX-3..EX-5, EX-18, R4; EXG-3, EXG-8; `bot/milestones.py` `handlers` (:187-219, screen form); `bot/walker.py:72-89` (registry), `:171-179` (refusals, revision bump); `tests/test_arena_screens.py` `ArenaRouterTests` (:1399, router harness).

**Goal.** The `/walker` EX-Gift screen pages new gifts and lists the EX inventory, and Claim takes every gift. The home button comes in EXG-10, Use buttons in EXG-11..EXG-17. C5 first.

- **`render(state)`** (new `bot/ex_gift.py`, no I/O), title `EX-Gift`:
  - `New gifts: <total> · page <p>/<pages>`, then one line per gift on the page `<YYYY-MM-DD UTC>: <labels joined by ", ">` (`ex_gift.label`); `No new gifts.` at 0;
  - `EX items:` then `<name> ×<n>` per held kind, or `No EX items yet.`;
  - the notice, if any.
  - Row 0: `Claim` (`ex_claim`, disabled at 0 gifts), `Prev` (`ex_gift_prev`), `Next` (`ex_gift_next`), each disabled at its end, and `Back` (`home`).
- **Handlers:** `ex_gift` sets `session['selection']` to `{"phase": "ex_gift", "offset": 0}` and renders `ex_gift.unclaimed(…, offset)` and `held`. Prev and Next move the offset by 10 within the total (R4); an offset past the end falls back to the last page. `ex_claim` calls `ex_gift.claim`; `excluded` → `EXCLUDED`, `stale` → `REOPEN`; else re-render from offset 0 with the notice `Claimed <g> gifts: <i> items went to your Inbox.` plus `EX items added: Shiny Patch ×1, …` when any, or `No new gifts to claim.` when `gifts` is 0. Action names match `[a-z_]+` (`bot/walker.py:28`).
- **`bot/walker.py`:** import the module and `self.handlers.update(ex_gift.handlers(self))` after `arena`.
- Paused members may claim (D8); the router already refuses excluded and opted-out members.
- **C5:** append "EX-Gift screen": lines, buttons, notices.

**Files.** Production: `pokewalker/bot/ex_gift.py` (new), `pokewalker/bot/walker.py`. Tests: `tests/test_ex_gift_screens.py` (new). Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_ex_gift_screens.py` pass, RED first:
- `test_gift_list_pages_ten_with_prev_and_next` (11 gifts: the 11th is visible on page 2 before Claim)
- `test_offset_past_end_falls_back_after_claim_elsewhere`
- `test_claim_disabled_without_gifts_ex_items_still_listed`
- `test_claim_notice_counts_inbox_items_and_ex_items`
- `test_claimed_ordinary_items_and_tickets_appear_in_inbox` (open `inbox` after Claim)
- `test_claim_twice_through_router_claims_once` (the second press carries the old revision)
- `test_paused_member_may_claim_excluded_member_refused`
- `test_description_fits_4096_with_ten_full_gifts`
- `test_action_names_match_router_pattern`

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_gift_screens`, `ex_gift`, `walker_router`, `milestones`, `screens`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A service change is needed; another `bot/` module needs a change; over 300 production lines.

**Do not touch.** `services/**`; `bot/screens.py` (EXG-10); other `bot/` modules.
