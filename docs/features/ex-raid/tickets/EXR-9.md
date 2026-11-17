# EXR-9 — `/admin ex-raid`: options, autocomplete, validation

**Tier:** seam (slash commands; abuse controls)

**Read:** PLAN D8, D9; SYNTHESIS XR-1..4, -9, -11, R1-R3, XR-2 readings; `bot/admin.py:41-104, :223-230`; `config.py:22-25`; C5 "M4.5a owner administration", "EX-Gift manager".

**Goal.** The admin-guild command exists, its Pokémon option autocompletes over all 1,094 identities, and a valid submit replies with a private text preview. Nothing is written or sent yet (draft: EXR-10; Confirm: EXR-11). C5 first. This is the repo's first autocomplete (PLAN section 2).

- **Command** (`bot/admin.py`): `ex-raid` with `pokemon: str` (required, autocomplete) and optional, in this order: `server_id: str`, `shiny: bool`, `level: Range[int, 1, 40]`, `iv_attack`, `iv_defense`, `iv_stamina: Range[int, 0, 15]`, `duration: Range[int, 1, 24]` (hours). After `authorize` it calls `admin_ex_raid.open(...)`. The autocomplete callback is a method bound with `@ex_raid.autocomplete('pokemon')`.
- **`suggest(content, text)`** (new `bot/admin_ex_raid.py`, pure): up to 25 `(label, identity_id)`, ranked: exact Dex number (`26`: Raichu, Alolan Raichu), name prefix, substring, then `difflib.get_close_matches`; case-folded, accents stripped (`unicodedata` NFKD); no duplicates. Empty text: the first 25 in catalog order. Label `#006 Charizard`; value the string `identity_id`.
- **Autocomplete check:** admin guild and configured owner ID, in memory; else `[]`. No defer, writer job or bucket token; exclusion is not read (R1).
- **`open`**, after `authorize` (5/min, exclusion): `pokemon` must be a known `identity_id`, else "Pick a Pokémon from the list."; level, IVs and duration are re-checked, else "Level must be 1-40, each IV 0-15 and the duration 1-24 hours."; `server_id` through `config.snowflake`, else "Server ID must be a Discord ID." A valid submit shows the boss (`#<dex> <name>`, sprite embed), each lock or "rolled per player", the duration (1 hour when omitted) and the target (server ID or "none chosen").
- **C5:** add "EX-Raid manager" under M4.5a: command shape, picker ranking, autocomplete trust boundary, refusals.

**Files.** Production: `pokewalker/bot/admin.py`, `pokewalker/bot/admin_ex_raid.py` (new). Tests: `tests/test_admin_ex_raid.py` (new), `tests/test_client_lifecycle.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_ex_raid.py` pass, RED first:
- `test_suggest_dex_number_lists_the_species_identities`
- `test_suggest_ranks_prefix_then_substring_then_close_spelling`
- `test_suggest_ignores_case_and_accents_and_finds_forms`
- `test_suggest_returns_at_most_25_labelled_dex_and_name`
- `test_autocomplete_empty_outside_admin_guild_and_for_non_owner`
- `test_autocomplete_no_defer_writer_or_bucket_serves_excluded_owner`
- `test_excluded_owner_refused_at_the_command`
- `test_known_identity_previews_locks_or_rolled_per_player`
- `test_free_text_and_unknown_identity_refused_nothing_written`
- `test_out_of_range_level_iv_and_duration_refused` (duration 0 and 25)
- `test_duration_omitted_is_one_hour`, `test_invalid_server_id_refused`
- `test_serialized_command_only_pokemon_required_with_ranges`
- `test_ex_raid_registered_only_in_the_admin_guild`

Pins moved:
- `tests/test_client_lifecycle.py:678-680`: the exact `/admin` subcommand set gains `ex-raid`.
- Admin-guild manifest hash: changes; no test holds a literal (PLAN section 2, pins); the `{'admin'}` scope pins (`:717`, `:767`) stay.

Not moved: the global manifest, schema versions.

**Verify.** Focused (staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_ex_raid`, `admin`, `admin_gift`, `cooldown_reset`, `client_lifecycle`, `deploy_script`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** The autocomplete method cannot bind on the group; a suggestion needs a database read; `bot/client.py` or a service needs an edit; over 300 production lines.

**Do not touch.** `services/**`, `bot/client.py`, `bot/admin_gift.py`, `content/**`.
