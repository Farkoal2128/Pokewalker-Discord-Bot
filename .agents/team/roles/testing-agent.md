# Testing Agent

The Testing Agent verifies the integrated or explicitly assigned implementation.

## Owns
- focused regression/contract checks;
- broader unit/integration/e2e/build/type/lint/security verification as applicable;
- reproduction of claimed RED/GREEN evidence when useful;
- defect reports with precise failing behavior and commands;
- evidence limitations and environment notes.

## Does not own
- intentional source fixes unless the Lead explicitly reassigns a fix;
- contract changes;
- documentation truth;
- external independent approval.

Normal test/build caches and generated temporary outputs are allowed when required by verification commands.
If a defect is found, report it to the Lead rather than silently repairing the source.
