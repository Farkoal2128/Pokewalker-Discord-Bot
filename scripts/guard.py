#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
meta = json.loads((ROOT / ".template.json").read_text())
canonical = meta.get("canonical_repository", "")

if meta.get("mode") == "template":
    print("REFUSED: canonical template is copy-only; create a project copy before development.", file=sys.stderr)
    raise SystemExit(2)

try:
    remotes = subprocess.check_output(["git", "remote", "-v"], cwd=ROOT, text=True)
except Exception:
    remotes = ""

if canonical and canonical.lower() in remotes.lower():
    print("REFUSED: project copy still references canonical template remote.", file=sys.stderr)
    raise SystemExit(3)

print("Guard OK: project mode and remotes are safe for development.")
