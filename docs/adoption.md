# Adopting the template

The canonical repository is a framework source, not an application repository.

Preferred local path:

```sh
git clone https://github.com/Farkoal2128/template-repo.git template-source
python template-source/scripts/new_project.py my-project --repository OWNER/my-project
```

The helper refuses to overwrite an existing destination, excludes source Git history,
switches `.template.json` to project mode, initializes a new `main` branch, and creates
a new `origin` URL for the target repository identity.

After copying:
1. define product requirements and architecture context;
2. configure real project checks in `.project/commands.json`;
3. adjust `.codex/config.toml` model identifiers if your runtime differs;
4. run `python scripts/guard.py`;
5. run framework and project verification;
6. commit the new project as its own history.

Do not retain the canonical template as a development upstream that agents can accidentally push to.
