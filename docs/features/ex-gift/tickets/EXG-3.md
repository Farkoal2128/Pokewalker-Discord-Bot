# EXG-3 — reward inbox: Arena Ticket rows and EX-Gift labels

**Tier:** seam (persisted player state; interaction responses)

**Read:** PLAN D4, D6; SYNTHESIS EX-3, EX-17, R8; EXG-2; `services/milestones.py` `claim` (:131-178), `waiting` (:111); `bot/milestones.py` `_reward_name` (:75), `_gym_labels` (:84), `render` (:144-150), `handlers` (:187); `services/arena.py:183-186` (ticket upsert form); `contracts/persisted-state.md` "M2.6 milestone inbox".

**Goal.** An `arena_ticket` inbox row (EXG-2) claims into `arena_tickets`, and the inbox shows ticket and EX-Gift rows by name. Nothing writes such rows yet; EXG-8 does. C3 and C5 first.

- **Claim** (`services/milestones.claim`): a new `arena_ticket` branch before the `else` (candy) one: `INSERT INTO arena_tickets VALUES (?,?,?) ON CONFLICT(profile_id,tier) DO UPDATE SET quantity=quantity+excluded.quantity` with `resource_id` as the tier and the full amount (no cap, so ticket rows never wait). `moved` starts with `'arena_ticket': 0`; the ledger line is `arena_ticket / <tier> / +n / milestone_claim`. Item, Stardust and candy branches, the receipt key and the lossless retention do not change.
- **Names** (`bot/milestones.py`): `_reward_name` of an `arena_ticket` row → `Bronze Arena Ticket` (title-cased tier). `_gym_labels` labels a key starting `ex_gift:` as `EX-Gift`, never showing the gift ID.
- **Lines** (`render`): an `Arena tickets: moved <m> / waiting <w>` line follows the candy line only when either count is above 0, so every existing inbox pin stays. The "Items wait for bag space" line and the bag shortcuts ignore ticket rows.
- **C3:** amend M2.6: `resource` may be `arena_ticket`; Claim credits `arena_tickets` in full. **C5:** inbox names and the `EX-Gift` label.

**Files.** Production: `pokewalker/services/milestones.py`, `pokewalker/bot/milestones.py`. Tests: `tests/test_milestones.py`. Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_milestones.py` pass, RED first (seed rows with SQL):
- `test_claim_credits_arena_ticket_rows_with_ledger_lines`
- `test_ticket_rows_move_with_full_bag_and_occupied_pockets`
- `test_mixed_ex_gift_rows_claim_items_and_tickets_once` (5 Poké Ball rows and 1 Bronze row under one `ex_gift:` key; the bag full of units except 2: 2 balls and the ticket move, 3 balls wait)
- `test_inbox_names_ticket_rows_and_ex_gift_label_without_id`
- `test_ticket_line_only_when_tickets_moved_or_waiting`
- `test_same_claim_press_credits_tickets_once`
- `test_pending_count_counts_one_ex_gift_key_once`

Existing `tests/test_milestones.py`, `tests/test_capacity.py` and `tests/test_arena.py` inbox tests pass unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `milestones`, `capacity`, `conversion`, `arena`, `arena_screens`, `walker_router`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** An existing inbox pin must change; the claim receipt key or its retention must change; over 300 production lines.

**Do not touch.** Migrations; `services/items.py`, `services/arena.py`, `services/gyms.py`; other `bot/` modules.
