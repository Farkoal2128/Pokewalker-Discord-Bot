What this change does: The amendment adds research sending from catch results, replaces full-storage refusal with a forced Send/Upgrade choice, removes Home’s Claim button, and adds bulk channel configuration. I reviewed the five individual tickets against pinned HEAD `11d40a79e62563334da19607c6f620c61fefcc49`, assuming one database writer with multiple valid Discord sessions.

**Must fix:**

1. **The fallback can send the wrong Pokémon** ([M6.8k.md:24](<scratchpad>/amend2/tickets/M6.8k.md:24)).
   - **What this is:** `overflow()` selects the oldest unacknowledged owned catch whenever storage exceeds its limit.
   - **Problem:** Catch A can bring storage to its limit and remain unacknowledged; another valid raid session can then catch B over the limit. The query selects A, so B receives the ordinary result and fallback later sends A. Existing `/raid` entry permits this independently of recovery (`pokewalker/bot/raid.py:25–59`).
   - **Fix:** Persist which catch actually crossed the limit, or establish and test an invariant that uniquely identifies it. Add the A-at-limit/B-over-limit case before settling on “no migration.”
   - **If we skip it:** Automatic research can permanently remove a Pokémon other than the one the owner authorized.

2. **The lock leaves routes that bypass the choice and defeat fallback** ([M6.8l.md:26](<scratchpad>/amend2/tickets/M6.8l.md:26)).
   - **What this is:** Only recovery, acknowledgment and Throw enforce the lock.
   - **Problem:** An existing Home session can still open Storage, select the newly caught Pokémon and favorite it or set it as companion (`walker.py:138–143`; `storage.py:202–239`). Research then refuses that Pokémon, including fallback (`services/research.py:61–64`); with Upgrade unavailable, neither choice works. `open_encounter` also lacks the promised redirect.
   - **Fix:** Enforce the pending-choice restriction across valid sessions before unrelated handlers run, with an explicit allowlist for resolving that catch. Test old Home/Storage sessions and encounter reopening.
   - **If we skip it:** Players can leave the forced flow, and the fallback can remain pending indefinitely.

3. **An expired preview opens research for other Pokémon** ([M6.8j.md:22](<scratchpad>/amend2/tickets/M6.8j.md:22)).
   - **What this is:** Catch research reuses the existing single-send flow and its refusal screens.
   - **Problem:** After the 120-second preview expires, `confirm` offers **New review**, which invokes the bulk picker (`bot/research.py:38–39, 140–144, 157`). The player can select another Pokémon; sending it can lower storage to the limit and release the overflow lock while retaining the original catch.
   - **Fix:** When `resume` identifies a catch, New review must rebuild the single review for that exact Pokémon. Add an expired-preview → New review → confirm test.
   - **If we skip it:** Q18’s “only that Pokémon” and Q19’s two-choice rule are bypassed through ordinary buttons.

4. **Fresh `/walker` recovery does not specify saving the choice selection** ([M6.8l.md:26](<scratchpad>/amend2/tickets/M6.8l.md:26)).
   - **What this is:** The new early recovery branch assigns the pending encounter and immediately returns its choice screen.
   - **Problem:** `/walker` initially inserts selection `{}` and calls `home` outside the component dispatcher; it does not subsequently save the detached selection (`walker.py:81–88, 107`). Current recovery explicitly updates `sessions.selection` at lines 215–217. An early return that only assigns the dictionary bypasses that write.
   - **Fix:** Explicitly retain the database update before returning the choice. Test clicking both choices after a fresh `/walker` reopen, not just inspecting the rendered screen.
   - **If we skip it:** The displayed buttons reload an empty selection and refuse instead of resolving the catch.

5. **The storage warning runs before terminal, stale and expired-raid handling** ([M6.8k.md:17](<scratchpad>/amend2/tickets/M6.8k.md:17)).
   - **What this is:** The warning is inserted before the existing Master Ball/service path.
   - **Problem:** Its stated predicate checks only count and confirmation revision. A competing screen after a catch reaches capacity therefore gets another throw warning instead of its saved terminal result; an expired raid at capacity also gets Confirm throw before expiry is checked. Current terminal/stale handling is in `services/catching.py:67–71` and `walker.py:422–428`.
   - **Fix:** Resolve terminal/stale/expired cases before creating the warning, and warn only for a current, throw-eligible encounter. Name regression tests for those cases and storage-confirm Back on raids with and without an ordinary queue.
   - **If we skip it:** The amendment changes replay behavior and violates its own promise that raid expiry takes precedence.

6. **Recovery results deliberately omit Q18’s action** ([PLAN-insert.md:18](<scratchpad>/amend2/PLAN-insert.md:18)).
   - **What this is:** `/walker` and `/raid` recovery remain Done-only.
   - **Problem:** The owner requested Send for research on **every catch result**. If the original Discord response fails after commit, recovery is the only catch result the player sees, and it lacks Send. Adding the button only inside `throw` also misses other terminal-render callers.
   - **Fix:** Cover recovered caught results and audit all `render_terminal` callers. Update `test_walker_ack.py:56,180` and `test_raids.py:1595` instead of requiring them unchanged.
   - **If we skip it:** A normal reconnect or failed response removes the requested action.

7. **The row order intentionally introduces broken controls and an unresolved-state gap** ([PLAN-insert.md:101](<scratchpad>/amend2/PLAN-insert.md:101)).
   - **What this is:** M6.8j removes handlers before M6.8k removes their buttons; M6.8k enables overflow before M6.8l enforces resolution.
   - **Problem:** After j, both advertised shortcuts return REOPEN. After k, recovery can acknowledge an overflow catch; l’s `acknowledged_at IS NULL` query then cannot recover that obligation. Removing tests does not make these intermediate behaviors correct.
   - **Fix:** Re-split so existing controls remain functional until their replacements land, and activate over-limit catching together with its durable resolution guard.
   - **If we skip it:** Intermediate commits regress working behavior and can create state the completed implementation cannot recognize.

8. **The adoption instructions leave contradictory rules and an impossible smoke check** ([PLAN-insert.md:7](<scratchpad>/amend2/PLAN-insert.md:7)).
   - **What this is:** The insert mostly appends Q18–Q21 and new rows.
   - **Problem:** Active PLAN Q4 still requires full-storage refusal (`PLAN.md:251–252`), Q16 retains the superseded shortcuts (`:340–344`), and G-F2 still requires returning from those shortcuts to the same encounter (`:511–512`). C3 also specifies `research:<preview UUID>` (`contracts/persisted-state.md:267`), while fallback introduces `research:overflow:<encounter_id>` without assigning that contract update.
   - **Fix:** Include exact replacements for the active rules, G-F2 smoke criteria and fallback receipt contract; preserve historical review records.
   - **If we skip it:** Implementers and reviewers receive conflicting requirements, and the final smoke gate tests behavior intentionally removed.

9. **The batch ticket omits its promised permission recheck** ([M6.8n.md:22](<scratchpad>/amend2/tickets/M6.8n.md:22)).
   - **What this is:** Q21 promises Manage Server plus exclusion checks inside the mutation job.
   - **Problem:** The ticket instructs the job to recheck only exclusion. Permission can change while the command waits for its writer job; the promised final authorization check is absent.
   - **Fix:** Reuse `WalkerAdmin.check_actor` (`admin_channels.py:117–121`) inside the batch transaction and test permission loss before mutation.
   - **If we skip it:** The batch can configure channels after the actor loses the required permission.

**Should fix:**

10. **The blanket test deletion removes still-valid coverage** ([M6.8j.md:36](<scratchpad>/amend2/tickets/M6.8j.md:36)).
   - **What this is:** The ticket says to remove every test that clicks a superseded action.
   - **Problem:** `test_expand_requires_preview_and_existing_access_guards` (`test_capacity.py:954–970`) mixes obsolete actions with valid expansion-preview, ownership and exclusion checks. It also lies outside the listed fallout ranges.
   - **Fix:** Remove obsolete action entries from mixed tests; delete only tests whose entire requirement was superseded. Preserve shared helpers used by retained tests.
   - **If we skip it:** Unchanged authorization and purchase behavior loses regression coverage.

The ticket sizes pass: **4,069 / 4,081 / 4,092 / 1,936 / 3,682 bytes**. Declared production scopes are **2 / 2 / 1 / 1 / 1 files**. The 300-production-line bound remains an implementation check. Writer rollback and synthetic research-selection compatibility are supported by the current code; the installed Discord library includes announcement channels in `guild.text_channels`.

**Verdict: fix 1–9 first.**

Not checked: tests, live Discord or implementation line counts; this was a paper-only review. Nothing changed.
MUST=9 SHOULD=1 NIT=0
