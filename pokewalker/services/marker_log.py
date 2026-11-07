"""Synchronous D28 write-ahead intents, cancellation and restore folding."""

from dataclasses import dataclass, field
import json
import logging
import math
import os
from pathlib import Path
from uuid import UUID, uuid4


log = logging.getLogger(__name__)
KINDS = {"delete", "opt_out", "opt_in", "reset"}
MARKER_FIELDS = {"marker_id", "kind", "guild_id", "user_id", "profile_id",
                 "at", "actor_id", "reason"}


@dataclass
class State:
    delete_ids: set[str] = field(default_factory=set)
    opted_out: bool | None = None
    resets: list[dict] = field(default_factory=list)


def _validate(record):
    try:
        if not isinstance(record, dict):
            raise ValueError("expected a record object")
        if type(record.get("at")) not in (int, float) or not math.isfinite(record["at"]):
            raise ValueError("expected finite epoch seconds")
        if set(record) == {"void", "at"}:
            marker_id = record["void"]
        elif set(record) == MARKER_FIELDS and record["kind"] in KINDS:
            marker_id = record["marker_id"]
            for key in ("guild_id", "user_id", "actor_id"):
                value = record[key]
                if key == "actor_id" and value is None:
                    continue
                if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
                    raise ValueError(f"expected decimal text for {key}")
            for key in ("profile_id", "reason"):
                if record[key] is not None and not isinstance(record[key], str):
                    raise ValueError(f"expected optional text for {key}")
        else:
            raise ValueError("unknown record shape or kind")
        if not isinstance(marker_id, str) or UUID(marker_id).version != 4:
            raise ValueError("expected UUID4 marker ID")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid marker log record: {exc}") from exc


def create_empty(path):
    """Create once; callers decide whether a missing log is safe to initialize."""
    path = Path(path)
    with path.open("xb") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _append(path, record):
    _validate(record)
    payload = (json.dumps(record, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    with open(path, "r+b") as stream:
        end = stream.seek(0, os.SEEK_END)
        if end:
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                stream.seek(0)
                boundary = stream.read().rfind(b"\n") + 1
                stream.truncate(boundary)
                stream.flush()
                os.fsync(stream.fileno())
                log.warning("Repaired marker log torn tail: dropped %d bytes", end - boundary)
        stream.seek(0, os.SEEK_END)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def append_marker(path, kind, guild_id, user_id, now, *, profile_id=None,
                  actor_id=None, reason=None, marker_id=None):
    marker = dict(marker_id=str(uuid4()) if marker_id is None else marker_id, kind=kind, guild_id=guild_id,
                  user_id=user_id, profile_id=profile_id, at=now,
                  actor_id=actor_id, reason=reason)
    _append(path, marker)
    return marker


def append_void(path, marker_id, now):
    _append(path, {"void": marker_id, "at": now})


def fold(path):
    """Replay final member state, independent of database receipts."""
    lines = Path(path).read_bytes().splitlines(keepends=True)
    markers, voided = [], set()
    for number, line in enumerate(lines, 1):
        if number == len(lines) and not line.endswith(b"\n"):
            log.warning("Skipping uncommitted marker log final tail")
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if number == len(lines):
                log.warning("Skipping unparseable marker log final line %d", number)
                continue
            raise ValueError(f"corrupt marker log at line {number}") from exc
        try:
            _validate(record)
        except ValueError as exc:
            raise ValueError(f"corrupt marker log at line {number}: {exc}") from exc
        if "void" in record:
            voided.add(record["void"])
        else:
            markers.append(record)
    states = {}
    for marker in markers:
        if marker["marker_id"] in voided:
            continue
        state = states.setdefault((marker["guild_id"], marker["user_id"]), State())
        if marker["kind"] in {"delete", "reset", "opt_out"} and marker["profile_id"] is not None:
            state.delete_ids.add(marker["profile_id"])
        if marker["kind"] in {"opt_out", "opt_in"}:
            state.opted_out = marker["kind"] == "opt_out"
        if marker["kind"] == "reset":
            state.resets.append({key: marker[key] for key in
                                 ("marker_id", "profile_id", "actor_id", "reason", "at")})
    return states
