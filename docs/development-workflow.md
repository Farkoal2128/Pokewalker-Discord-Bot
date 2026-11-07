# Development Workflow

## Feature lifecycle

Requirement → contract impact → plan → RED → minimal implementation → GREEN → refactor → broad verification → review → merge/release.

## Feature folder

Create `docs/features/<slug>/` containing:
- `README.md`: outcome, scope, non-goals, dependencies, acceptance;
- `plan.md`: task IDs, dependency gates, rollback;
- `progress.md`: actual state and evidence;
- `validation.md`: checks and environments.

The plan is scope authority; progress is a resumability record, not a second roadmap.
