"""D33 eligible words and D20 fixed-point step credit; see contracts/step-rules.md."""

import hashlib
import hmac
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import regex


_EXCLUDED = regex.compile(
    r"```[\s\S]*?(?:```|\Z)|~~~[\s\S]*?(?:~~~|\Z)"
    r"|^[\t ]*>[^\n]*"
    r"|[a-z][a-z0-9+.-]*://[^\s<>]+|(?:mailto|data):[^\s<>]+|www\.[^\s<>]+"
    r"|<[@#][!&]?\d+>|<a?:[A-Za-z0-9_]+:\d+>"
    r"|[0-9#*]\ufe0f?\u20e3|\p{Regional_Indicator}+"
    r"|[\p{Extended_Pictographic}\p{Emoji_Modifier}\u200d\ufe0f]",
    regex.MULTILINE | regex.IGNORECASE,
)


class History(Protocol):
    """Player-scoped, chronological history; lower query boundaries are exclusive."""

    digest_key: bytes
    last_credit_at: float | None

    def accepted_words_since(self, since: float) -> int: ...

    def seen_digest(self, digest: str, since: float) -> bool: ...


@dataclass(frozen=True)
class Decision:
    accepted_words: int
    awarded_c: int
    discarded_words: int
    reason: str
    digest: str


def eligible_words(text: str) -> list[str]:
    filtered = _EXCLUDED.sub(" ", text)
    return [segment for segment in regex.split(r"\b", filtered, flags=regex.WORD)
            if len(regex.findall(r"[\p{L}\p{Nd}]", segment)) >= 2]


def accept_message(words: list[str], at: float, history: History,
                   rules: Mapping[str, int]) -> Decision:
    if not math.isfinite(at):
        raise ValueError("message time must be finite")
    if len(history.digest_key) < 32:
        raise ValueError("duplicate digest key must contain at least 32 bytes")
    digest = hmac.new(history.digest_key, " ".join(w.casefold() for w in words).encode(),
                      hashlib.sha256).hexdigest()
    repetitions = Counter(w.casefold() for w in words)
    count = sum(min(n, rules["repeat_word_cap"]) for n in repetitions.values())
    reason = "credited"
    if count < rules["min_message_words"]:
        count, reason = 0, "minimum"
    else:
        count = min(count, rules["max_message_words"])
        if (history.last_credit_at is not None
                and at - history.last_credit_at < rules["cooldown_seconds"]):
            count, reason = 0, "cooldown"
        else:
            remaining = rules["accepted_words_per_rolling_minute"] - history.accepted_words_since(at - 60)
            count = min(count, max(0, remaining))
            if not count:
                reason = "minute_cap"
            elif history.seen_digest(digest, at - rules["duplicate_window_seconds"]):
                count, reason = 0, "duplicate"
    prior = history.accepted_words_since(at - 3600) if count else 0
    full = min(count, max(0, rules["full_words_per_rolling_hour"] - prior))
    awarded = full * rules["full_step_hundredths"] + (count - full) * rules["later_step_hundredths"]
    return Decision(count, awarded, len(words) - count, reason, digest)
