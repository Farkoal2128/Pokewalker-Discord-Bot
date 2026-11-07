"""Select D28 expirations: newline snapshot IDs or NUL-delimited local file paths.

Local mode also expires uploaded snapshot pairs beyond the newest --keep (0 = age only)."""

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", type=float, required=True)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--local")
    parser.add_argument("--keep", type=int, default=0)
    args = parser.parse_args()
    try:
        if not math.isfinite(args.now) or args.days <= 0 or args.keep < 0:
            raise ValueError
        cutoff = args.now - args.days * 86_400
        if args.local is not None:
            if not args.local:
                raise ValueError
            with os.scandir(Path(args.local).resolve(strict=True)) as entries:
                files = [(entry, entry.stat(follow_symlinks=False).st_mtime)
                         for entry in entries if entry.is_file(follow_symlinks=False)]
            # Past the newest --keep snapshots, a pair expires only once its upload succeeded.
            uploaded = {entry.name.partition(".")[0] for entry, _ in files
                        if entry.name.endswith(".uploaded")}
            snapshots = sorted(((mtime, entry.name) for entry, mtime in files
                                if entry.name.endswith(".sqlite3")), reverse=True)
            surplus = {name.partition(".")[0] for _, name in snapshots[args.keep:]} & uploaded
            for entry, mtime in files:
                if mtime < cutoff or (args.keep and entry.name.partition(".")[0] in surplus):
                    sys.stdout.buffer.write(os.fsencode(Path(entry.path).as_posix()) + b"\0")
        else:
            snapshots = json.load(sys.stdin)
            if not isinstance(snapshots, list):
                raise ValueError
            selected = []
            for snapshot in snapshots:
                identifier = snapshot["id"]
                if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
                    raise ValueError
                timestamp = dt.datetime.fromisoformat(snapshot["time"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError
                if timestamp.timestamp() < cutoff:
                    selected.append(identifier)
            # Validate the whole listing before allowing any destructive remote operation.
            for identifier in selected:
                sys.stdout.buffer.write(identifier.encode("ascii") + b"\n")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        print("prune-select: invalid input", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
