# GitHub setup

For the canonical framework source:

- keep it private unless intentionally distributing it;
- mark it as a GitHub template repository when that UI capability is desired;
- archive it when you want normal repository writes disabled;
- treat owner-level unarchive/admin actions as a separate explicit maintenance operation.

For project copies:

- create a new repository identity;
- protect the default branch according to project risk;
- require appropriate CI/status checks;
- require review for high-impact projects;
- use least-privilege workflow permissions;
- keep secrets in GitHub/hosting secret stores, never repository files.

Files in this template describe intended policy; they cannot enforce owner-level GitHub administration by themselves.
