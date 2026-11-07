What this change does: The combined plan adds v1.1 progression, then v2 gyms and catch-only raids. I reviewed all 37 tickets against the requirements, research, and built v1 at `648bb378`, assuming one process serving a few hobby servers.

The fixes for all 32 findings from rounds 1–3 are present. None remains **REPEAT**.

1. **SHOULD FIX — Deploy confirmation does not explicitly reject a removed gym.** [M7.4a.md:29](<docs/features/pokewalker-v1.1-v2/tickets/M7.4a.md:29>), [M7.5a.md:24](<docs/features/pokewalker-v1.1-v2/tickets/M7.5a.md:24>)

   **Problem:** Removal retains the gym row with `retired_at`. A player can preview deployment into an empty gym, an administrator can remove it, and the player can then confirm. The specified deployment guards check ownership, revision, eligibility and occupancy, but never require `retired_at IS NULL`. The built [router](<pokewalker/bot/walker.py:126>) checks session ownership and revision; another user’s administrative action does not invalidate that session.

   **Fix:** Require an active, non-retired gym inside the deployment transaction. Add an acceptance case that removes the gym between preview and confirmation and verifies refusal without a deployment or Pokémon assignment.

   **If skipped:** Following the listed guards can let a stale panel deploy into a gym the administrator removed.

2. **NIT — New gym audit entries display the server as a user.** [M7.4c.md:22](<docs/features/pokewalker-v1.1-v2/tickets/M7.4c.md:22>)

   **Problem:** Gym creation/removal records use `target_kind='guild'`, but [mod.py:120](<pokewalker/bot/mod.py:120>) labels every non-channel target `user:<id>`. An in-memory probe using the actual renderer produced `target=user:123 gym_create` for guild `123`.

   **Fix:** Assign guild-specific target formatting and one display assertion to [M7.8](<docs/features/pokewalker-v1.1-v2/tickets/M7.8.md:19>), which already owns `mod.py`. No additional production file or row is needed.

   **If skipped:** Moderators see misleading target labels, although the stored audit data remains correct.

Verdict: address finding 1 before implementation. All tickets fit within 4 KiB; the largest is 4,078 bytes. Declared production scopes fit the two-file limit.

Not checked: full test suites or live Discord behavior; actual 300-line compliance requires implementation. No files were edited or committed.

MUST=0 SHOULD=1 NIT=1