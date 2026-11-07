#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser(description="Create an independent project copy of the framework.")
parser.add_argument("destination")
parser.add_argument("--repository", required=True, help="New repository identity, owner/name")
args = parser.parse_args()

dst = Path(args.destination).resolve()
if dst.exists():
    raise SystemExit(f"Refusing to overwrite existing destination: {dst}")

ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")
shutil.copytree(ROOT, dst, ignore=ignore)

meta_path = dst / ".template.json"
meta = json.loads(meta_path.read_text())
meta["mode"] = "project"
meta["stage"] = "scaffold"
meta["repository"] = args.repository
meta_path.write_text(json.dumps(meta, indent=2) + "\n")

subprocess.run(["git", "init", "-b", "main"], cwd=dst, check=True)
subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{args.repository}.git"], cwd=dst, check=True)

print(f"Created independent project copy at {dst}")
print("Next: define requirements, configure .project/commands.json, run python scripts/guard.py and python scripts/verify.py")
