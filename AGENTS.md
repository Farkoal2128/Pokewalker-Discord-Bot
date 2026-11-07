# AGENTS.md

This repository is a reusable engineering framework, not an application.

## Non-negotiable source-of-truth order

1. Requirements define intended behavior.
2. Contracts define observable boundaries and invariants.
3. Tests execute requirements and contracts.
4. Implementation satisfies the above and must not silently redefine them.

## Mandatory behavior-change workflow

For every feature, bug fix, or intentional behavior revision:

1. Read the applicable requirement and feature plan.
2. Identify affected public/domain contracts.
3. Update requirements/contracts deliberately when behavior must change.
4. Write the smallest meaningful behavioral test.
5. Run it before production implementation and record expected failure (**RED**).
6. Make the minimum reasonable production change.
7. Re-run the focused test and record success (**GREEN**).
8. Refactor without changing observable behavior.
9. Run applicable contract, integration, regression, type, lint, build, security, and e2e checks.
10. Record evidence and remaining gaps truthfully.

Production implementation must not normally precede RED.

## Test integrity

Never delete, skip, weaken, or rewrite a valid failing test merely to make CI pass.
If a test appears wrong, resolve the requirement/contract/test conflict explicitly first.

## Contract integrity

Never change a contract merely because implementation disagrees. For a genuine contract change:
identify producers/consumers, classify compatibility, update the requirement, change the contract intentionally,
add contract tests first, update implementation, and verify compatibility.

## Agentic execution

Use `.agents/skills/implement-feature/SKILL.md` for one bounded task.
Use `.agents/skills/drive-feature/SKILL.md` for sustained execution across eligible tasks.
Use `.agents/skills/tdd/SKILL.md` for RED → GREEN → REFACTOR → VERIFY.
Use `.agents/skills/contract-change/SKILL.md` whenever a public/domain boundary may change.

Agents must preserve unrelated work, report uncertainty, distinguish evidence from assumptions,
and never self-approve a review gate that explicitly requires independent review.

## Multi-agent orchestration

For complex work with genuinely independent workstreams, read
`.agents/skills/multi-agent-orchestration/SKILL.md`,
`docs/multi-agent-workflow.md`, and use
`docs/templates/agent-work-order.md` for each delegated assignment.

The default team is five agents total:

1. **Lead Developer** — the root/coordinating agent. Owns requirements, architecture,
   contract decisions, task decomposition, integration, conflict resolution, and final status.
2. **Developer A** — bounded implementation writer with explicit exclusive file ownership.
3. **Developer B** — second bounded implementation writer with a disjoint write scope.
4. **Testing Agent** — verification specialist; does not intentionally change source unless reassigned.
5. **Documentation Agent** — reconciles requirements, plans, ADRs, progress, and evidence after implementation facts exist.

The Lead is deliberately not configured as a Codex subagent. `.codex/config.toml`
allows at most four subagent threads, so the root Lead plus four subagents forms the five-agent team.

Do not force all five roles onto short or sequential work. Delegate only when separate context or parallelism
materially improves speed, coverage, or verification quality.

### Concurrency and ownership

- Every write assignment requires an explicit work order and file/directory ownership.
- Developers A and B may write concurrently only when their scopes are disjoint.
- Shared contracts, schemas, migrations, lockfiles, root configuration, and canonical status files have one writer at a time.
- The Testing Agent may run commands that create normal caches/build outputs but must not intentionally edit source.
- The Documentation Agent must not rewrite technical facts that have not been demonstrated by implementation or verification evidence.
- If an unexpected overlap appears, stop the overlapping writer and return ownership to the Lead before continuing.

Parallel work never bypasses contract-first TDD. Requirements and contract decisions must be stable enough
for each writer to know the expected behavior before its RED test.

### Review integrity

Same-session agents provide internal engineering review only. Their output is not external independent approval.
A gate that explicitly requires a human or independent reviewer must remain open until that reviewer acts.
Use `.agents/skills/scoped-review-handoff/SKILL.md` for such gates.

The Lead reconciles conflicting results against requirements, contracts, tests, and direct evidence.
Do not resolve disagreements by majority vote.

## Copy-only rule

When `.template.json` says `"mode": "template"`, do not develop product behavior in this repository.
Create a new project copy first. This file-level rule is a guardrail, not a substitute for GitHub permissions.

## Definition of Done

A task is complete only when applicable requirements, contracts, tests, implementation, docs, and verification agree.
For multi-agent work, the Lead must also confirm work-order completion, ownership reconciliation,
tester evidence, documentation reconciliation, and unresolved review gates.

Report exact commands/checks, actual results, contract impact, RED evidence, changed files, and unresolved blockers.
