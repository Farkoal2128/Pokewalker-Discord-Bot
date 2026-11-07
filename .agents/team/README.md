# Default multi-agent team

This directory defines the reusable five-agent topology for complex development work.

```text
Human objective
      |
Lead Developer (root coordinator)
      |
      +-------------------+-------------------+
      |                   |                   |
Developer A          Developer B        early read-only analysis
      |                   |
      +--------- integration by Lead ---------+
                          |
                    Testing Agent
                          |
                 Documentation Agent
                          |
                  Lead final integration
```

The diagram is an execution pattern, not a mandatory waterfall. Read-only discovery may happen earlier,
and Documentation may inspect context early, but source/document writers must still respect ownership.

## Why the Lead is the root agent

The Lead owns the parent objective and must preserve the complete context:
requirements, contracts, work-order dependency graph, authorization, shared-file ownership,
conflict resolution, integration, and final report. Making the Lead another peer subagent would
create ambiguity over who can resolve contradictions.

Therefore `.codex/config.toml` defines four subagents. Root + four subagents = five agents.

## Team members

- [Lead Developer](roles/lead-developer.md)
- [Developer A](roles/developer-a.md)
- [Developer B](roles/developer-b.md)
- [Testing Agent](roles/testing-agent.md)
- [Documentation Agent](roles/documentation-agent.md)

## Ownership rule

A file has one intentional writer at a time.

Before parallel work, the Lead writes an ownership matrix in the team run/work orders.
If a developer discovers it must touch another agent's file, it reports the dependency
instead of editing across the boundary.

Serialize writes to contracts/public schemas, migrations/persistence definitions,
dependency manifests/lockfiles, shared configuration, generated artifacts, and canonical status documents.

## State vocabulary

`Planned → Assigned → RED → Implementing → GREEN → Verifying → Documenting → Integrated → Verified`

Use `Blocked` or `In review` when appropriate. Do not advance status without evidence.

## Internal review is not external approval

The Testing Agent and same-session reviewers may challenge implementation,
but cannot satisfy a gate explicitly requiring a human, external reviewer,
compliance sign-off, production owner, or other independent authority.
