# Contributing

This framework uses contract-first, test-driven development.

Before implementation, create or update the relevant requirement/feature plan and identify affected contracts.
Behavior changes require meaningful RED evidence before production code, followed by GREEN and broader verification.

Keep pull requests bounded. Do not mix unrelated refactors with behavior changes.
Use Conventional Commit-style messages where practical: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.

A pull request should explain:
- requirement and scope;
- contract impact and compatibility;
- RED/GREEN evidence;
- tests/checks run;
- security/privacy implications;
- rollback or migration concerns;
- remaining risks.

Never commit secrets, customer data, generated credentials, or local environment files.
