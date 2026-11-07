"""Bot-owned v1 balance contract (D20–D61; PLAN P1/P3/P5/P6/P8).

Producer: the reviewed JSON tables here. Consumers: offline content build and
economy simulation; gameplay consumes the resulting artifact, not these files.
Every table has source, checked (ISO date), version and its named payload.
Weighted rows use item/quantity/weight; route types omitted from weights mean 0.
CPM keys are level_x2 strings; power-up upper bounds are exclusive.
Schema/rule changes require deliberate requirement review and a version change.
No persisted data or older consumers exist at this additive SI-0 boundary.
"""

import copy
import functools
import json
import re
from pathlib import Path


def load_table(name: str) -> dict:
    """Return a fresh copy of a table by bare snake_case name, without network or writes.

    Invalid names raise ValueError; missing tables raise FileNotFoundError;
    malformed JSON raises JSONDecodeError. Full rule validation is in the tests.
    """
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z_]*", name):
        raise ValueError("balance table name must be a bare snake_case name")
    # Tables are immutable within a release: parse once, hand each caller its own copy.
    return copy.deepcopy(_parsed(name))


def limits() -> dict:
    """The capacities limits: storage, bag_units, rare_pockets, encounter_queue, starter_kit."""
    return load_table("capacities")["limits"]


@functools.cache
def _parsed(name: str) -> dict:
    return json.loads(Path(__file__).with_name(f"{name}.json").read_text(encoding="utf-8"))


load_table.cache_clear = _parsed.cache_clear
