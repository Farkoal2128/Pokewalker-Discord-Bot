# Agent work order

Use one copy per delegated assignment. Keep it narrow enough that the assigned agent can finish,
return evidence, and avoid owning the parent objective.

## Assignment

- **Work order ID:**
- **Parent objective:**
- **Authorization:** read-only / implementation / verification / documentation
- **Assigned role:** Developer A / Developer B / Testing Agent / Documentation Agent / other
- **Preferred model / reasoning:**
- **Baseline revision:**
- **Parallel-safe:** yes / no
- **Dependencies:**
- **Exclusive write ownership:**

### Bounded task
Describe the exact question, change, or proof this agent owns.

### Allowed scope
List files, directories, commands, tools, fixtures, or external sources the agent may inspect or modify.

### Forbidden scope
List files/actions/gates that must remain untouched.

### Governing sources
Link the requirement, contract, feature task, ADR, review scope, or other source of truth.

### TDD expectation
For implementation, state the observable behavior that should fail before production implementation
and the expected focused RED command/test location. Use `N/A` for read-only/documentation/verification work.

### Required evidence
List required paths, diffs, test commands/results, hashes, runtime observations, or identified missing inputs.

### Completion criteria
State the smallest evidence-backed condition that makes this delegated assignment complete.

## Returned evidence

- **Agent/role actually used:**
- **Model / reasoning actually used:** use `not exposed` when unavailable
- **Files inspected:**
- **Files changed:**
- **RED evidence:**
- **GREEN evidence:**
- **Other commands/checks:**
- **Result:**
- **Uncertainties / missing inputs:**
- **New dependencies discovered:**
- **Scope explicitly not approved:**

## Lead integration

- **Ownership collisions checked:**
- **Conflicts/reconciliation:**
- **Evidence independently inspected:**
- **Integrated revision/state:**
- **Next dependency/gate:**
