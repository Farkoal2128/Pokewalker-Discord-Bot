# Multi-agent development workflow

This framework supports a default five-agent software team while preserving contract-first TDD and clear accountability.

## Team topology

The coordinating/root agent is the **Lead Developer**. It may delegate to four configured Codex subagents:
Developer A, Developer B, Testing Agent, and Documentation Agent.

This produces five active team roles without creating a second coordinator.

## Core design principles

### One parent owner
The Lead owns the parent objective, architecture, requirement/contract interpretation, work graph,
shared-file ownership, integration order, and final completion claim. Subagents own assignments, not the project.

### One writer per mutable file
Parallel work is safe only when write sets are disjoint.

The Lead must serialize changes to contracts, shared schemas, migrations, lockfiles, global configuration,
generated artifacts, and canonical feature status documents unless a work order explicitly assigns one sole writer.

### Parallelism follows contracts
A developer may not implement a guess while another agent is still deciding the governing contract.
Resolve enough of the boundary first, then create RED tests against that expected behavior.

### Evidence beats role authority
No agent is right merely because of role or model. Material conclusions should be grounded in requirements,
contracts, diffs, tests, hashes, runtime observations, or other inspectable evidence.

## Lifecycle

### Phase 0 — Lead framing
The Lead confirms authorization and scope, identifies requirements and affected contracts,
maps dependencies/shared files, decides whether delegation has real value, and creates work orders.

### Phase 1 — Contract/test decomposition
Before writers start, the Lead identifies stable expected behavior, shared contract ownership,
the smallest meaningful RED test for each behavior change, and dependencies between developer slices.

If both slices need the same contract or fixture file, assign that shared work to one owner or do it sequentially.

### Phase 2 — Developer A / Developer B
Both developers may work concurrently only when their work orders say `Parallel-safe: yes`
and intentional write sets do not overlap.

Each returns RED evidence, files changed, GREEN evidence, focused checks, and newly discovered dependencies.

### Phase 3 — Lead integration
The Lead inspects both handoffs against the current tree and sources of truth, resolves collisions,
handles shared-file edits, and decides whether an integration-level RED is needed.

### Phase 4 — Testing Agent
The Testing Agent reproduces applicable evidence and broadens coverage according to risk:
focused tests, contracts, unit/regression, integration, type, lint/format, build, security,
browser/e2e/render/target-platform checks as relevant.

The Testing Agent reports defects precisely and does not intentionally repair source unless reassigned.

### Phase 5 — Defect loop
A tester-found defect becomes a new bounded implementation slice:
Lead assigns ownership → developer demonstrates RED → minimal fix → GREEN → tester re-verifies.

### Phase 6 — Documentation Agent
Once implementation facts and verification results exist, Documentation reconciles requirements,
feature tasks/progress, ADRs/architecture, verification records, and unresolved human/external approvals.

Planned, implemented, verified, and approved states remain distinct.

### Phase 7 — Lead closure
The Lead checks consistency and reports objective, contract decisions, work orders, ownership,
RED/GREEN evidence, tester evidence, documentation updates, unrun checks, remaining gates, and final state.

## Suggested allocation

| Work order | Role | Example ownership |
| --- | --- | --- |
| WO-A | Developer A | backend/domain slice + focused tests |
| WO-B | Developer B | frontend/client slice + focused tests |
| WO-T | Testing Agent | integrated verification |
| WO-D | Documentation Agent | requirements/feature/ADR/evidence docs |
| Root | Lead Developer | contracts, shared schemas, integration, final verification |

Slice by dependency and write ownership, not by fashionable frontend/backend labels.

## Git/worktree strategy

If the runtime supports worktrees or isolated branches, one writer per worktree/branch is preferred for substantial slices.
Branch from the same recorded baseline, integrate in dependency order, and rerun relevant checks after reconciliation.

If agents share one workspace, use explicit exclusive paths and pause/reassign when overlap becomes necessary.

## Model routing

The included `.codex/config.toml` mirrors the practical pattern used in `myAutoclip`:
stronger implementation routing for Developer A/B and lighter high-effort routing for verification/documentation.

Model availability changes over time. Configuration is preference, not evidence.
If actual role/model/reasoning metadata is not exposed, record `not exposed`.

## Independent approval boundary

Testing Agent results are independent within the engineering workflow but not organizationally or legally independent.
Same-session agent review does not satisfy a gate requiring a human owner, security/compliance reviewer,
external auditor, release authority, or customer acceptance.

Use `.agents/skills/scoped-review-handoff/SKILL.md` for those gates.
