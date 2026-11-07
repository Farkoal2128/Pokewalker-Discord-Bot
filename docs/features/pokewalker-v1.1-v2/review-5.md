What this change does: The combined plan adds v1.1 progression, then v2 gyms and catch-only raids. I reviewed all 38 tickets against requirements, research, prior findings, and built v1, assuming one process serving a few hobby servers.

The binding owner decisions are consistently reflected. Prior fixes remain present. One additional finding:

1. **SHOULD FIX — Run can preserve an encounter after its raid expires.** [M8.3a.md:24](<docs/features/pokewalker-v1.1-v2/tickets/M8.3a.md:24>), [M8.4.md:22](<docs/features/pokewalker-v1.1-v2/tickets/M8.4.md:22>)

   **Problem:** The plan adds an expiry check only to Throw. Open a raid shortly before expiry, wait until it expires while cleanup is pending, then press Run or confirm shiny Run. The existing [Run handler](<pokewalker/bot/walker.py:363>) changes the encounter to `ran` without checking expiry. Cleanup deliberately preserves `ran` encounters, allowing [terminal recovery](<pokewalker/bot/walker.py:201>) to display it afterward. This conflicts with D60’s requirement that unfinished encounters disappear at expiry.

   **Evidence:** An in-memory probe using the actual Run handler, followed by the planned cleanup predicate, retained an unacknowledged `ran` encounter resolved after expiry.

   **Fix:** Assign a transactional expiry check to Run, including shiny confirmation, in M8.1c’s existing `walker.py` scope. Add acceptance cases proving both post-expiry paths refuse and cleanup removes the encounter.

   **If skipped:** Clicking Run during the cleanup delay turns an expired encounter into a retained result.

Verdict: fix 1 first. All tickets fit within 4 KiB; the largest is 4,078 bytes. Declared production scopes fit the two-file limit. The exact backfill SQL passed in-memory checks for all six threshold boundaries, free routes, server isolation, and repeat execution.

Not checked: full runtime suites or live Discord; actual 300-line compliance requires implementation. No files were edited or committed.

MUST=0 SHOULD=1 NIT=0