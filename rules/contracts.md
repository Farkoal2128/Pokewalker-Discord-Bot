# Contract Rules

A contract is an authoritative externally observable boundary or important domain invariant.

Before changing one:
- identify requirement;
- identify producers and consumers;
- classify compatible vs breaking;
- consider persisted data and older clients;
- define migration/rollback where needed;
- add or update contract tests before provider/consumer implementation.

A failing implementation is not justification for changing a contract.
Undocumented public interfaces are prohibited.
