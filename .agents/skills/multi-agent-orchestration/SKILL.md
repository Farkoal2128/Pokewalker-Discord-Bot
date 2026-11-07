---
name: multi-agent-orchestration
description: Coordinate complex project work across the default five-agent team using bounded work orders, non-overlapping writers, contract-first TDD, verification, and evidence-based integration.
---

# Multi-agent orchestration

Read `AGENTS.md`, `.agents/team/README.md`, and applicable nested instructions before delegating.
The root agent is the Lead Developer and owns scope, sequencing, shared contracts, integration, and the final report.
Subagents are bounded workers, not substitute decision-makers.

Use `docs/templates/agent-work-order.md` for each delegated assignment and
`docs/templates/team-run.md` for a multi-agent execution record.

## Decide whether to delegate

Delegate only when independent workstreams can proceed with separate context and materially improve speed,
coverage, or verification quality.

Good candidates:
- two implementation slices with disjoint files after contracts are stable;
- implementation plus independent later verification;
- separate evidence/repository exploration;
- documentation reconciliation after technical evidence is available.

Keep work with the Lead when it is short, tightly sequential, or centered on the same mutable files.
Do not create agents just to make the process appear more rigorous.

## Default five-agent topology

- **Lead Developer:** root coordinator.
- **Developer A:** implementation writer.
- **Developer B:** second implementation writer.
- **Testing Agent:** verification specialist.
- **Documentation Agent:** documentation/evidence reconciler.

The default Codex configuration allows four subagent threads. The Lead is the root thread.

## Work-order contract

Every delegated work order must record:
- work-order ID and parent objective;
- authorization type: research/read-only, implementation, verification, or documentation;
- baseline revision/working-tree assumptions;
- bounded task and deliverable;
- governing requirement, contract, and feature task;
- exact allowed and forbidden files/actions;
- exclusive write ownership;
- dependencies and parallel-safe yes/no;
- expected RED behavior for an implementation slice;
- required evidence/commands;
- completion criteria;
- returned files changed, commands, results, uncertainties, and unapproved scope.

When actual agent/model/reasoning metadata is exposed, record it. Otherwise write `not exposed`.

## Contract and TDD ordering

Parallelism begins only after the Lead resolves enough requirement/contract ambiguity for each writer
to know the expected observable behavior.

Each implementation writer independently follows:
1. requirement/contract context;
2. focused failing test (**RED**);
3. minimum implementation;
4. focused pass (**GREEN**);
5. refactor while green;
6. focused handoff evidence.

One writer must own any shared contract/schema/migration/lockfile touched by both slices.
Do not let separate agents race to define the same boundary.

## Concurrency and writes

Default maximum: four subagent threads.

- Parallelize read-only work freely when scopes are independent.
- Developer A and Developer B may write concurrently only with disjoint intentional write sets.
- Do not run concurrent writers against the same file or tightly coupled shared files.
- Tester intentionally avoids source edits; if a fix is needed, the Lead reassigns it.
- Documentation edits should normally follow implementation/verification so docs describe evidence rather than expectation.

If the environment supports separate worktrees/branches, one writer per worktree is preferred for substantial slices.
If all agents share one workspace, exclusive path ownership is mandatory.

## Recommended execution sequence

1. **Lead:** understand objective, requirements, contracts, task graph, and risks.
2. **Lead:** write work orders and ownership matrix.
3. **Developers A/B:** execute independent TDD slices when safe.
4. **Lead:** integrate/reconcile developer output.
5. **Testing Agent:** verify the integrated state; report defects without silent fixes.
6. **Lead/Developers:** repair verified defects through a new RED/GREEN slice when needed.
7. **Documentation Agent:** reconcile requirements/plans/ADRs/progress/evidence.
8. **Lead:** run or inspect final required verification, resolve contradictions, and issue final status.

A checkpoint records evidence; it is not automatically a reason to stop.

## Review integrity

Same-session agents can challenge assumptions and independently reproduce checks, but they are still internal engineering review.

Never:
- label same-session output as external independent approval;
- close a human/compliance/security/owner approval gate from subagent output;
- expand a scoped review into release/publication approval;
- treat an agent assertion as evidence when the underlying artifact or command is material and inspectable.

Use `scoped-review-handoff` for true independent-review gates.

## Conflict resolution

The Lead reconciles disagreements against requirements, contracts, executable tests, and direct evidence.
Do not take a majority vote.

When requirement, contract, test, and implementation disagree, surface the conflict and deliberately choose which
source must change before continuing.

## Stop conditions

Stop when the authorized scope is verified, the user pauses/cancels, an explicit execution limit is reached,
or no in-scope task can advance after all independent work is checked.

Do not promise unattended/background continuation.

## Final handoff

Report:
- work orders actually delegated;
- roles and actual model/effort metadata when exposed;
- exclusive ownership used;
- exact files changed;
- RED/GREEN evidence per implementation slice;
- tester commands/results;
- documentation reconciliation;
- conflicts or failed assignments;
- remaining external/human gates;
- next eligible task.
