"""Build/check the committed C1 snapshot; network use is opt-in with a warm cache."""

import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError

from .emit import ROOT, build_content, write_artifacts
from .fetch import CACHE_DIR, fetch_csvs


def main(argv=None, *, output_root=ROOT, balance_directory=ROOT / "content/balance"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--audit-sprites", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not (args.cache / "manifest.json").exists():
            fetch_csvs(args.cache)
        artifact, manifest = build_content(args.cache, balance_directory, audit_sprites=args.audit_sprites)
        if manifest["pending"]:
            print(json.dumps({"pending": manifest["pending"]}), file=sys.stderr)
            return 1
        if not write_artifacts(artifact, manifest, output_root, check=args.check):
            print("content artifact or manifest differs from rebuild", file=sys.stderr)
            return 1
        print(json.dumps({"counts": manifest["counts"], "sprite_audit": manifest["sprite_audit"]}, sort_keys=True))
        return 0
    except (ValueError, KeyError, OSError, URLError) as error:
        print(f"content build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
