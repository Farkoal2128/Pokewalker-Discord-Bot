#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    "AGENTS.md",
    ".template.json",
    ".project/commands.json",
    "rules/testing.md",
    "rules/contracts.md",
    "contracts/README.md",
    ".agents/skills/implement-feature/SKILL.md",
    ".agents/skills/drive-feature/SKILL.md",
    ".agents/skills/tdd/SKILL.md",
    ".agents/skills/contract-change/SKILL.md",
]
missing = [p for p in required if not (ROOT / p).exists()]
if missing:
    print("Missing framework files:", *missing, sep="\n- ", file=sys.stderr)
    raise SystemExit(1)

meta = json.loads((ROOT / ".template.json").read_text())
commands = json.loads((ROOT / ".project/commands.json").read_text())
print(f"Framework mode: {meta.get('mode')}  stage: {commands.get('stage')}")

configured = 0
for name, command in commands["checks"].items():
    if not command:
        print(f"UNCONFIGURED: {name}")
        continue
    configured += 1
    print(f"RUN: {name}: {command}")
    result = subprocess.run(command, cwd=ROOT, shell=True)
    if result.returncode:
        raise SystemExit(result.returncode)

if commands.get("stage") == "active":
    mandatory = ["unit", "contract"]
    absent = [n for n in mandatory if not commands["checks"].get(n)]
    if absent:
        print("Active project missing mandatory checks: " + ", ".join(absent), file=sys.stderr)
        raise SystemExit(2)

print(f"Framework verified. Configured application checks run: {configured}.")
if commands.get("stage") == "scaffold":
    print("SCAFFOLD ONLY: application behavior/readiness is not verified.")
