# Plan: paged-readme — private paged `/readme` with an admin setup page

**Status:** approved (G-A ✅ 2026-11-12); implementing
**Review:** none yet. This plan was split from pokemon-trading on 2026-11-12 (that plan's round-3 SHOULD 1). Its content was reviewed there as T8 in rounds 1–2; see the git history of `docs/features/pokemon-trading/PLAN.md`.
**Home:** none assigned. Proposed: `feature/paged-readme · none`, cut from pokemon-trading's accepted candidate (or from `main` once that candidate is integrated), only after pokemon-trading reaches G-F (owner decision at G-A).
**Inputs:** owner decision OD1 (2026-11-12, relayed by the coordinator) · [pokemon-trading plan](../pokemon-trading/PLAN.md) (`trade-channels`, `/trade`) · C5 discord-commands.md:32-38 (readme amendment), :122 (component IDs) · [PIPELINE.md](../../../PIPELINE.md)

## 0. Owner decision (2026-11-12)

**OD1** (relayed as OD10 in the trading brief): rework `/readme` into private pages the reader flips through.
- Each page stays within the 4,096 limit.
- The final page is for admin/moderator setup commands.
- Correct the `/checkin` text (exact wording in R1).
- Add a short trading section on a player page, and the trade-channels commands on the admin page.
- Keep it working for unenrolled and excluded members, and in the one-time post-starter send.

## 1. Outcome and scope

**Outcome:** `/readme` and the post-starter message show page 1 of N, with Prev/Next buttons. The pages need no profile or session. The last page lists every `/walker-admin` and `/walker-mod` command.

**Non-goals:**
- New gameplay.
- Changing `/readme` command options.
- Documenting `/admin`, which is owner-only and registered only in the admin guild (admin.py:154-161).
- Publication and deployment.

## 2. Requirements

- **R1:** OD1.
- **R2:** page 1 is the current opening (help.md:1-14) verbatim.
- **R3:** the admin page names every subcommand under the `walker-admin` and `walker-mod` roots, including the trading plan's `trade-channels`.

## 3. Verified code map — verified at 8face5b

**Grep evidence.** `git grep -n help_text 8face5b -- tests pokewalker` returns:
- client.py:55, :123
- walker.py:186
- test_account.py:41
- test_readme.py:46
- test_walker_router.py:34, :135, :152

These are the fallout sites.

| Anchor | Fact |
|---|---|
| client.py:35-57, :123, :134, :297-299 | `HELP_PATH`, `load_help` (≤ 4,096 UTF-16; errors mention "help"), `/readme` sends one embed; `help_text`; dynamic-item registration; check-config calls `load_help` |
| walker.py:185-187 @8face5b | the post-starter follow-up sends `help_text` |
| content/help.md:1-49; tests/test_readme.py:17-20, :58-75 | one approved text, hash `7ceb3f82…` (`git show 8face5b:content/help.md \| sha256sum`); 3,845 UTF-16 units (`python3`, 2026-11-12) |
| items.py:20-43, :106-146; content/balance/checkin_table.json; bot/checkin.py:25-46 | check-in behaviour: 3,600 s cooldown; 1 Poké Ball plus one roll (Great Ball 35, Razz Berry 30, 2 Poké Balls 20, Pinap 15); an item that doesn't fit becomes 10 Stardust; an encounter if the queue is under 3, else "Queue is full"; paused refusal |
| admin_channels.py:84-334; mod.py:19, :87-213 | every admin and mod command and its permission |

**Do-not-touch:** everything except the two production files, `content/help.md`, the named tests and C5.

## 4. Decisions

### 4.1 Planner decisions

- **P1 Pages.**
  - `content/help.md` holds pages separated by a line containing exactly `<!-- page -->`, each ≤ 4,096 units.
  - Stateless `pw:readme:v1:<page>` buttons use a `ReadmeItem` DynamicItem. They do no DB, session or restriction lookup, so they work for unenrolled and excluded members.
  - `bot.help_page(i)` serves both `/readme` and the post-starter send.
- **P2 Page map.**
  - Page 1: help.md:1-14, verbatim.
  - Page 2: :16-31, with the corrected check-in text.
  - Page 3: gyms, raids, trading and privacy.
  - Final page: the admin sentences of :35, :41 and :43, plus the full command list.
- **P3 Order.** This row starts only after pokemon-trading reaches G-F, so its admin page can be tested against the final command tree, including `trade-channels`.

### 4.2 Contracts

| Contract | Change | Row |
|---|---|---|
| C5 discord-commands.md | Revise :32-38 (pages, admin page, stateless buttons) and :122 (add the `pw:readme:v1:<page>` grammar; `pw:v1` is unchanged). This is a compatible revision. | R1 |

### 4.3 Verification decision (Decide before dispatch)

- **Row:** focused coverage, using the ticket's named tests plus `git diff --check`.
- **Final checkpoint (G-F):** independent integration GO plus one exact-tree full `test_cmd` PASS (PIPELINE.md:10).
- **Live Discord:** owner smoke only.

### 4.4 Row bounds

R1 is `seam`: ≤ 2 production files (client.py, walker.py) and ≤ 300 production lines.

### 4.5 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15) |
| Candidate | the final accepted candidate on the G-A Home |
| Action scope and targets | **Unresolved; proposed local-only.** Repo `Farkoal2128/Pokewalker-Discord-Bot`, remote `origin`, main branch `main`. `/readme` keeps its manifest entry, so no command sync is needed. |
| Predicates and workflow | integration GO; exact-tree full `test_cmd` PASS; owner-approved help wording |
| Owner authority | none yet |

**G-P.** The allowlist is `docs/features/paged-readme/PLAN.md` and `tickets/R1.md`. A push to `main` or a PR runs verify.yml (PIPELINE.md:26). The proposed default is no publication, which makes G-P inapplicable if the owner confirms local-only.

### 4.6 Gate record

| Gate | Decision maker | Evidence |
|---|---|---|
| G-A | owner: plan, Home, scope | an owner message naming G-A |
| G-F | coordinator: technical; owner: wording, smoke, delivery | an owner message naming G-F |

## 5. Step table

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A plan approval, Home, scope; starts after pokemon-trading G-F | 🚦 | — | — | ✅ owner 2026-11-12 ("implement the plan"); Home `feature/paged-readme` cut from trading candidate 5b9d6f0 (tree 74bcfafb… test_cmd PASS, integration GO; trading command set final, owner-only G-F items pending); local-only |
| 2 | [R1](tickets/R1.md) paged `/readme`, admin page, corrected check-in text; C5 | impl | seam | M | pending |
| 3 | G-F final: independent GO, exact-tree full `test_cmd`, owner wording approval and smoke, delivery per G-A | 🚦 | — | — | pending |

## 6. Gate briefs

**G-A (owner).**
- **Predicate:** pokemon-trading's G-F row is ✅, and its accepted candidate is an ancestor of the Home (`git merge-base --is-ancestor <trading accepted sha> <home>`).
- **Accept:** that owner message.
- **Re-anchor:** re-verify the §3 and R1 line anchors at the trading candidate (trading T2/T6/T7 edit client.py and walker.py); where lines moved, use the symbols `load_help`, `self.help_text`, `add_dynamic_items` and the `onboard_confirm` follow-up.
- **Stop if:** pokemon-trading changes its command set after G-F. In that case, re-brief R1's command list.

**G-F (coordinator + owner).**
- **Coordinator:** integration GO plus `Tests: tree <sha> <test_cmd> PASS`.
- **Owner:** approve the help wording, then smoke-test:
  - `/readme` flips pages, including for an unenrolled and an excluded member.
  - The post-starter message shows page 1 with buttons.
  - The last page lists the admin and mod commands.

## 7. Risks and rollback

- **Old buttons:** a button whose page number is out of range after a help edit refuses privately.
- **Rollback:** revert to a single page.
- **Data:** no persisted state changes.
