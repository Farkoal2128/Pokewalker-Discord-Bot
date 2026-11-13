"""C2 contract: approved D33 filtering/order and D20 fixed-point credit."""

import importlib
import unittest

from content.balance import load_table


class History:
    digest_key = b"test-only-key-for-step-contract!!"

    def __init__(self, events=(), digests=()):
        self.events = list(events)
        self.digests = dict(digests)

    @property
    def last_credit_at(self):
        return self.events[-1][0] if self.events else None

    def accepted_words_since(self, since):
        return sum(words for at, words in self.events if at > since)

    def seen_digest(self, digest, since):
        return self.digests.get(digest, float("-inf")) > since


class StepTests(unittest.TestCase):
    def setUp(self):
        try:
            self.steps = importlib.import_module("pokewalker.domain.steps")
        except ModuleNotFoundError:
            self.fail("M0.5 step provider absent: D33/D20 credit unavailable")
        self.rules = load_table("step_rules")["rules"]

    def decide(self, text="alpha bravo charlie delta", at=100, history=None):
        return self.steps.accept_message(self.steps.eligible_words(text), at,
                                         history or History(), self.rules)

    def test_d33_example_hello_x4_rejected(self):
        result = self.decide("hello hello hello hello")
        self.assertEqual((result.accepted_words, result.awarded_c, result.reason),
                         (0, 0, "minimum"))

    def test_min_four_words(self):
        self.assertEqual(self.decide("one two three").accepted_words, 0)
        self.assertEqual(self.decide().accepted_words, 4)

    def test_cap_20_words(self):
        result = self.decide(" ".join(f"word{i}" for i in range(25)))
        self.assertEqual((result.accepted_words, result.discarded_words), (20, 5))

    def test_repeat_cap_case_insensitive(self):
        result = self.decide("HELLO hello Hello hELLo world")
        self.assertEqual((result.accepted_words, result.discarded_words), (4, 1))

    def test_filters_url_mention_emoji_code_quote(self):
        text = ("alpha https://example.com/extra words <@123> <@!456> <#789> "
                "<@&123> <:dance:123> <a:wave:456> \U0001f469\u200d\U0001f4bb "
                "\U0001f1fa\U0001f1f8 1\ufe0f\u20e3\n"
                "> quoted words\n  > more quoted words\n"
                "```python\nignored code words\n```\nbravo charlie")
        self.assertEqual(self.steps.eligible_words(text),
                         ["alpha", "words", "bravo", "charlie"])

    def test_scheme_qualified_urls_never_award_steps(self):
        for url in ("ftp://example.com/alpha/bravo", "WSS://example.com/alpha/bravo",
                    "git+ssh://example.com/alpha/bravo", "mailto:alice@example.com",
                    "data:text/plain,alpha/bravo"):
            with self.subTest(url=url):
                result = self.decide(url)
                self.assertEqual((result.accepted_words, result.awarded_c), (0, 0))
                self.assertEqual(self.steps.eligible_words(f"alpha<{url}>bravo"),
                                 ["alpha", "bravo"])

    def test_word_colon_word_prose_is_not_a_url(self):
        # Audit fix: only "scheme://", mailto: and data: are links; "Update:the" is ordinary text.
        self.assertEqual(self.steps.eligible_words("Update:the server is back"),
                         ["Update:the", "server", "is", "back"])
        self.assertEqual(self.steps.eligible_words("note:remember ftp://x.org/a mailto:a@b.c"), ["note:remember"])

    def test_two_char_minimum(self):
        self.assertEqual(self.steps.eligible_words("a I 1 ab 12 a2 \u00e9\u00e9"),
                         ["ab", "12", "a2", "\u00e9\u00e9"])

    def test_cjk_single_ideograph_rejected(self):
        self.assertEqual(self.steps.eligible_words("\u4e2d\u6587\u6d4b\u8bd5"), [])

    def test_cooldown_15s(self):
        history = History([(100, 4)])
        self.assertEqual(self.decide(at=114.999, history=history).reason, "cooldown")
        self.assertEqual(self.decide(at=115, history=history).accepted_words, 4)

    def test_minute_cap_30_rolling(self):
        history = History([(40, 20), (60, 8)])
        self.assertEqual(self.decide(at=99, history=history).accepted_words, 2)
        self.assertEqual(self.decide(at=100, history=history).accepted_words, 4)
        self.assertEqual(self.decide(at=100, history=History([(60, 30)])).reason,
                         "minute_cap")

    def test_duplicate_within_30min_rejected(self):
        first = self.decide()
        history = History([(100, 4)], [(first.digest, 100)])
        result = self.decide("  ALPHA  bravo charlie delta ", 1899, history)
        self.assertEqual(result.reason, "duplicate")
        self.assertEqual(self.decide(at=1900, history=history).accepted_words, 4)
        self.assertNotEqual(first.digest,
                            self.decide("alpha bravo charlie delta extra").digest)

    def test_d20_split_at_300(self):
        result = self.decide(history=History([(0, 299)]))
        self.assertEqual((result.accepted_words, result.awarded_c), (4, 175))

    def test_threshold_counts_accepted_not_awarded(self):
        self.assertEqual(self.decide(history=History([(0, 400)])).awarded_c, 100)
        self.assertEqual(self.decide(at=3600, history=History([(0, 400)])).awarded_c,
                         400)

    def test_decision_does_not_mutate_history(self):
        history = History([(0, 4)])
        self.decide(history=history)
        self.assertEqual(history.events, [(0, 4)])
        self.assertEqual(history.digests, {})


if __name__ == "__main__":
    unittest.main()
