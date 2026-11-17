# EXR-14 — retention disclosure: privacy text, C3 M8.4, retention coverage

**Tier:** seam (persisted player state: a retention promise changes)

**Read:** PLAN D2, D10; SYNTHESIS R10, §7 (Retention); EXR-3, EXR-4; `docs/features/pokewalker-bot/privacy.md:11`; `bot/account.py:15-24`, `bot/client.py:149` (the text is loaded once at startup from `POKEWALKER_PRIVACY_PATH`); `0015_raids.sql:18-25` (participation has no profile FK); C3 "M8.4 raid expiry sweep and retention"; `tests/test_raids.py:1053, :1252` (precedent tests).

**Goal.** The repository privacy text and C3 say what a 24-hour EX-Raid does to the raid participation record. No code changes: participation already lives until its spawn expires. C3 first. The deployed file is not this row: G-V (owner).

- **`privacy.md:11`** becomes, keeping the file's CRLF line endings: `**Raids.** A raid announcement does not say who started it. When you join a raid, the bot records the server, your user ID and that raid. This record is kept after `delete-data` until that raid leaves: at most 60 minutes for a World Legendary, at most 24 hours for an EX-Raid.` No other paragraph changes.
- **C3:** amend "M8.4 raid expiry sweep and retention": the server/user/spawn record kept after delete-data, opt-out or reset lasts until that spawn's own `expires_at`, at most 60 minutes for a World Legendary and at most 24 hours for an EX-Raid; `ex_raids` holds aggregate counts and the sending owner's ID, never a participant's; the repository text above is the disclosure, and the configured runtime file is checked at delivery (G-V).

**Files.** Production: `docs/features/pokewalker-bot/privacy.md`. Tests: `tests/test_account.py`, `tests/test_ex_raid.py`. Contract: `contracts/persisted-state.md`.

**Accept.** RED first, in `tests/test_account.py`:
- `test_repository_privacy_text_discloses_raid_retention`: the committed file contains `at most 60 minutes for a World Legendary, at most 24 hours for an EX-Raid` and no longer ends the Raids paragraph with `at most 60 minutes.`

Coverage of existing behavior, in `tests/test_ex_raid.py` (expected to pass on first run; a failure is a finding, stop):
- `test_delete_data_opt_out_and_reset_during_24_h_ex_raid_keep_participation` (each path; the record survives until expiry)
- `test_reenrolled_player_cannot_join_the_same_ex_raid_again`
- `test_participation_removed_when_the_ex_raid_expires`
- `test_ex_raids_row_unchanged_by_joins_and_holds_no_participant_id`

`tests/test_units.py:91` (the env example path) and `tests/test_deploy_script.py:228-230` (its own fixture text) stay. No command or button is added: no manifest, subcommand-set or schema pin moves.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `account`, `ex_raid`, `raids`, `deletion`, `units`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A coverage test fails (participation is lost early, or a deleted player can join again); `services/deletion.py` or `services/raids.py` needs an edit; another privacy paragraph must change; the file would lose its CRLF endings.

**Do not touch.** `pokewalker/**`; `deploy/**` (`runtime.env.example:9` already points at the repository copy); other `docs/features/pokewalker-bot/` files; the host's privacy file (owner, G-V).
