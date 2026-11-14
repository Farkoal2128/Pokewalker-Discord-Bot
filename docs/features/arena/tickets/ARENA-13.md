# ARENA-13 — tickets submenu, redemption screens, inbox labels

**Tier:** seam (interaction responses)

**Read:** PLAN D12, D13, D17; REQUIREMENTS AR-25..AR-29a, AR-35a; ARENA-10, ARENA-11; `bot/milestones.py` `_gym_labels` (:83-104), `_detail_lines` (:107); `bot/gyms.py` `render_recall` (confirm pattern).

**Goal.** Players see and redeem tickets from an Arena submenu, separate from the inbox, and `arena:` inbox rows read as words. C5 first.

- **`arena_tickets`:** one line per tier with the count held and what it gives, from `arena.json` (for example "Silver ×2: up to 2 encounters, 200 Stardust, 2 gym income rolls"). Buttons `arena_redeem_bronze`, `arena_redeem_silver`, `arena_redeem_gold`, `arena_redeem_platinum`, `arena_redeem_diamond` (each disabled at 0) and `Back` (`arena`). It works with the Arena off and during a live run (AR-35a). The ARENA-11 `Tickets (n)` button is enabled here.
- **Redeem press:** `service.redeem_quote`.
  - `free == 0` → the tickets screen with "Your encounter queue is full (3/3). Open an encounter first. Nothing was spent." (the numbers come from `limits()['encounter_queue']`).
  - Otherwise the confirm screen: the tier's contents and the quote line "2 of 3 slots free: +2 encounters". Selection `{'phase': 'arena_redeem', 'tier', 'free', 'add'}`. Buttons `Confirm` (`arena_redeem_confirm`) and `Back` (`arena_tickets`).
- **`arena_redeem_confirm`:** needs phase `arena_redeem`; calls `service.redeem(..., expected_free=selection['free'], expected_add=selection['add'], ...)`.
  - `redeemed` → the tickets screen with "Redeemed a <Tier> Ticket: +n encounters. Rewards are in your Inbox."
  - `quote_changed` → the confirm screen again with the new quote and "Your queue changed. Nothing was spent."
  - `queue_full` / `none` → the tickets screen with the matching notice.
- **Inbox labels** (`bot/milestones.py`): extend the label step that `inbox` and `claim` already use (:174, :194) so keys starting `arena:` read "Arena ticket: income roll", "Arena ticket: survivor reward" and "Arena ticket: Stardust". A malformed `arena:` key reads "Arena ticket reward". No lookup query and never the raw key. Gym labels are unchanged.
- D17: each roll is its own inbox key, as gym hours are, so one Diamond adds 28 to the home "Inbox (n)" count. That is accepted; do not change `pending_count`.

**Files.** Production: `pokewalker/bot/arena.py`, `pokewalker/bot/milestones.py`. Tests: `tests/test_arena_screens.py`, `tests/test_milestones.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_screens.py`:
- `test_tickets_screen_lists_five_tiers_with_counts_and_contents`
- `test_redeem_buttons_disabled_at_zero`
- `test_confirm_screen_quotes_free_slots_and_added_encounters`
- `test_queue_full_explains_and_spends_nothing`
- `test_quote_changed_between_confirm_and_press_shows_new_quote`
- `test_confirm_without_preview_refused`
- `test_redeemed_notice_and_count_drops_by_one`
- `test_tickets_redeemable_with_arena_off_and_during_live_run`

In `tests/test_milestones.py`:
- `test_inbox_and_claim_label_arena_rows_without_raw_keys`
- `test_malformed_arena_key_gets_generic_label`
- `test_gym_labels_unchanged`

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena_screens.py"`, `-p "test_milestones.py"`, `-p "test_gym_screens.py"`, `git diff --check`.

**Stop if.** The labels need a database query or a change to `services/milestones.py`; an existing inbox assertion must change; the row passes 300 production lines.

**Do not touch.** `services/milestones.py`, `services/arena.py`, `bot/screens.py`.
