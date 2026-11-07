"""Measure approved step rules offline; content never leaves process memory."""

import argparse
import json
import math
import secrets
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content.balance import load_table
from pokewalker.domain.steps import accept_message, eligible_words


SUMMARY_PATH = ROOT / "docs/features/pokewalker-bot/measurements/chat-rate-summary.md"


class MemoryHistory:
    """Timestamped buckets, not a replenishing token budget; no stored words."""

    def __init__(self):
        self.digest_key = secrets.token_bytes(32)
        self.events = deque()
        self.digests = {}
        self.last_credit_at = None

    def accepted_words_since(self, since):
        return sum(words for at, words in self.events if at > since)

    def seen_digest(self, digest, since):
        return self.digests.get(digest, float("-inf")) > since

    def prune(self, at):
        while self.events and self.events[0][0] <= at - 3600:
            self.events.popleft()
        self.digests = {d: t for d, t in self.digests.items() if t > at - 1800}

    def record(self, at, decision):
        if decision.accepted_words:
            self.events.append((at, decision.accepted_words))
            self.last_credit_at = at
            self.digests[decision.digest] = at


def _timestamp(value):
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("timestamp needs a timezone")
        value = parsed.timestamp()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("timestamp must be finite")
    return value


def measure(messages):
    histories, totals = {}, {}
    rules = load_table("step_rules")["rules"]
    previous = float("-inf")
    for line, message in enumerate(messages, 1):
        try:
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            for field in ("author_id", "channel_id"):
                if type(message[field]) not in (str, int) or not str(message[field]).strip():
                    raise ValueError("invalid identity")
            if type(message["is_bot"]) is not bool or not isinstance(message["content"], str):
                raise ValueError("invalid message fields")
            at = _timestamp(message["created_at"])
            hour = datetime.fromtimestamp(at, timezone.utc).replace(minute=0, second=0,
                                                                   microsecond=0).isoformat()
            if at < previous:
                raise ValueError("messages must be chronological")
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            raise ValueError(f"invalid message at line {line}") from None
        previous = at
        if message["is_bot"]:
            continue
        author = str(message["author_id"])
        if author not in histories:
            histories[author] = MemoryHistory()
        history = histories[author]
        history.prune(at)
        decision = accept_message(eligible_words(message["content"]), at, history, rules)
        history.record(at, decision)
        if decision.accepted_words:
            total = totals.setdefault((author, hour), {"author_id": author, "hour": hour,
                                                       "accepted_words": 0, "awarded_c": 0})
            total["accepted_words"] += decision.accepted_words
            total["awarded_c"] += decision.awarded_c
    return [totals[key] for key in sorted(totals)]


def render_summary(totals):
    def percentile(values, fraction):
        if not values:
            return 0
        values = sorted(values)
        position = (len(values) - 1) * fraction
        lower = math.floor(position)
        return values[lower] + (values[math.ceil(position)] - values[lower]) * (position - lower)

    lines = ["# Chat-rate summary", "", f"Active member-hours: {len(totals)}", "",
             "| Per active hour | p50 | p90 | p99 |", "|---|---:|---:|---:|"]
    for label, key, divisor in (("Accepted words", "accepted_words", 1),
                                 ("Awarded steps", "awarded_c", 100)):
        values = [total[key] / divisor for total in totals]
        cells = " | ".join(f"{percentile(values, p):.2f}" for p in (.5, .9, .99))
        lines.append(f"| {label} | {cells} |")
    return "\n".join(lines) + "\n"


def _read_jsonl(source):
    for line, text in enumerate(source, 1):
        try:
            yield json.loads(text)
        except (ValueError, UnicodeError):
            raise ValueError(f"invalid JSON at line {line}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="private totals JSON; never commit")
    parser.add_argument("--summary", action="store_true", help="write anonymised markdown summary")
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve() or (
            args.summary and (args.input.resolve() == SUMMARY_PATH.resolve()
                              or args.output.resolve() == SUMMARY_PATH.resolve())):
        parser.exit(2, "input, private output and summary must have different paths\n")
    try:
        with args.input.open("rb") as source:
            totals = measure(_read_jsonl(source))
        args.output.write_text(json.dumps(totals, indent=2) + "\n", encoding="utf-8")
        if args.summary:
            SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
            SUMMARY_PATH.write_text(render_summary(totals), encoding="utf-8")
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except (OSError, UnicodeError):
        parser.exit(2, "unable to read input or write measurement outputs\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
