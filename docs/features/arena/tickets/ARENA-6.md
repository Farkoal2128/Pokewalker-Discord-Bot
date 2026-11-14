# ARENA-6 — research send refuses live Arena team members

**Tier:** seam (persisted player state; interaction responses)

**Read:** PLAN D3, D10; REQUIREMENTS AR-7a; ARENA-4; `services/research.py` `protected_reason`, `candidates`, `send`; `bot/research.py` `page`, `review`, `single`.

**Goal.** A team member cannot be sent to research, in bulk or singly, and never reaches the Shiny/Legendary unlock prompt. C3 and C5 first. Fixtures insert `arena_runs` rows directly.

- **`research.protected_reason(identity, pokemon, profile, arena_team=frozenset())`** (:10): new first entry `("in_arena", pokemon["pokemon_uid"] in arena_team)`, ahead of `deployed`. The default keeps every existing caller working. Call sites (`git grep -n "protected_reason" -- pokewalker`): `services/research.py:32,70`, `services/trading.py:27`, `bot/research.py:73,120,147`, `bot/storage.py:184`.
- **`services/research.py`:**
  - `candidates(conn, profile_id, content, offset, now)` gains `now`, loads `profiles.arena_team` once and passes it (:21-33). Its only caller is `bot/research.py:61`.
  - `send` (:59) loads the team with its `now` and passes it at :70. Because `in_arena` comes first, the unlock exception at :71-72 can never apply to a team member: the send returns `changed` and writes nothing.
  - `send_pending`, `send_pending_reviewed` and `auto_send` are untouched: a pending catch is not an owned Pokémon and cannot be on a team.
- **`bot/research.py`:** pass the team (loaded with `walker.clock()`) at :61, :73, :120 and :147.
  - Bulk list (:86): the reason reads `on your Arena team`; the row's toggle stays disabled, as for any reason (:88-89).
  - `single` (:147-151): `in_arena` joins the hard refusals with "This Pokémon is on your Arena team. It can't be sent until the run ends." It must not reach the unlock screen (:156-158).
- **`bot/storage.py:184` stays as it is** (D10): the detail screen's Send press is refused by `single`, the way favorites and companions are refused today.
- **C3:** append `in_arena` to the research protection order. **C5:** append the two texts.

**Files.** Production: `pokewalker/services/research.py`, `pokewalker/bot/research.py`. Tests: `tests/test_research.py` (extend its protection tests). Contracts: `contracts/persisted-state.md`, `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_research.py` pass, RED first:
- `test_protected_reason_in_arena_precedes_every_other_reason`
- `test_candidates_mark_live_team_member_in_arena`
- `test_bulk_send_with_team_member_returns_changed_nothing_sent`
- `test_single_send_of_team_member_hard_refused_with_arena_text`
- `test_unlocked_legendary_team_member_still_refused_no_unlock_prompt`
- `test_team_member_sendable_after_hour_18_and_after_run_end`
- `test_bulk_list_shows_arena_text_and_disabled_toggle`

Existing research, storage and trading tests pass unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_research.py"`, `-p "test_storage.py"`, `-p "test_trading.py"`, `git diff --check`.

**Stop if.** `candidates` has a caller other than `bot/research.py:61` (grep first); an existing protection test needs a changed assertion; a third production file is needed.

**Do not touch.** `services/trading.py` (ARENA-7), `bot/storage.py`.
