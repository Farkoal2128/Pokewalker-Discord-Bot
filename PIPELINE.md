# Pokewalker-Discord-Bot pipeline

Repository facts for `feature-pipeline`. Run pipeline skills and the commands below
from this Git repository's root, `Pokewalker Discord Bot/`.

## Facts

- feature_root: docs/features
- completed_root: docs/completed
- test_cmd: python scripts/guard.py && python scripts/verify.py
- test_scope_hint: python -m unittest discover -s tests -p "test_<module>.py" for the affected application module (for example, test_content_integrity.py); for a specific case, append -k <test_name>
- lint_cmd: none
- seam_domains: Discord gateway events, slash commands and interaction responses; bot token and OAuth scopes/intents; step, watt and progression rules; route, encounter and item tables; persisted player state and migrations; trading or transfer between players; rate limits and abuse controls; verification command/configuration contracts
- branch_policy: feature-branch
- delivery_cadence: end
- rules.coding: rules/coding.md
- rules.testing: rules/testing.md
- rules.contracts: rules/contracts.md
- rules.security: rules/security.md
- rules.collaboration: rules/collaboration.md
- review_grounding.reuse: Read README.md and inspect the referenced scripts, tests, and .agents/skills before claiming reuse; no application implementation exists yet.
- review_grounding.architecture: Read docs/architecture.md and docs/decisions/0001-application-stack.md (proposed: Python 3.12+, discord.py, aiosqlite/SQLite WAL, single writer, systemd); no application code exists yet.
- deploy.check: none
- deploy.ship: none
- deploy.mode3_doc: none
- push_effect: The checked-in .github/workflows/verify.yml runs framework-verification on pushes to main and on pull requests; no deployment workflow is configured. Hosted workflow enablement and branch protection have not been verified.

## Current verification boundary

Python 3.11 or later is required. The full command uses `&&` to stop on the first
failure; use PowerShell 7, Git Bash or another shell supporting that operator. Run
every leg before recording PASS. The guard additionally checks project identity and
remotes.

The project adapter is `active`: `scripts/verify.py` runs the two configured checks
in `.project/commands.json`: the application unit suite (`unit`) and the offline
committed-artifact integrity suite (`contract`). Other checks remain unconfigured;
there is no separate lint command yet. `test_cmd` runs the unit suite once, through
the `verify.py` `unit` check (owner decision 2026-11-14: the separate unittest leg
duplicated it and doubled the run time).

Passing `test_cmd` proves application unit tests, the committed artifact's integrity,
and framework checks. It does not establish live Discord acceptance (G-3 smoke
evidence is recorded separately, PLAN row 23), host readiness (G-5), a raw-CSV
rebuild, or hosted CI success. `python -m content.build --check` is a separate
raw-CSV rebuild check and may fetch source CSVs without a warm cache; it is not part
of the configured offline contract check.

## Planning and execution

Follow `AGENTS.md` and the referenced repository rules. Behavior changes require
requirement and contract grounding, meaningful RED evidence, minimal implementation,
GREEN, and applicable verification. Pipeline orchestration does not replace these
requirements or grant delivery approval.

For features using `feature-pipeline`, keep the canonical plan and row status table
in `docs/features/<slug>/PLAN.md`. This is the pipeline spelling of the `plan.md`
described in `docs/development-workflow.md`; never create both, particularly on
Windows. Supporting README, validation, and progress documents may hold requirements
and evidence, but must reference the canonical table rather than duplicate row status.
Do not overwrite an existing plan. Archive closed features under `docs/completed/`
only during authorized closeout; create that directory when first needed.

Use a feature branch and a clean working tree for execution. Preserve unrelated work.
Apply the pipeline's role routing for pipeline workers while retaining repository
ownership and review rules. Same-session review does not satisfy a gate explicitly
requiring human or external independent approval.

Rewrite mechanics in our own words. Do not commit ROM dumps, extracted sprites/audio,
or copied game code (D8). Species, form, stat, type and evolution data comes only from the pinned PokéAPI source (D51).
Bot-owned balance tables (the CP multiplier table, prices, rates) are authored in the
repository with their source and check date recorded, as ADR 0001 describes,
and sprites are hotlinked or cached locally, never committed (D48–D49), as set in
`docs/features/pokewalker-bot/README.md`; record any content-source change in an ADR
before it lands.

Deployment harnesses and deployment-mode documentation are absent, so deployment
steps are explicitly disabled. Pushes, publication, live Discord access (bot tokens,
inviting the bot to servers, posting messages) and production changes require
matching owner scope; this file is not that authorization.
