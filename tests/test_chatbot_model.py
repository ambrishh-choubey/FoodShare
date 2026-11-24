"""Tests for the on-device intent model (chatbot/ml_intent.py).

These need no database, network or Flask app: the model is plain Python.
They check behaviour (paraphrases, typos, off-topic refusal) and guard against
the classic mistake of testing on sentences the model was trained on.
"""
import re
import unittest

from chatbot import ml_intent, training_data, intent_handler

# Regression checks, NOT an accuracy measure: wordings that are not in
# training_data.EXAMPLES and that the model currently gets right. Real accuracy
# on unseen wordings is lower (see the patch guide).
PARAPHRASES = [
    ("how do i regster", "register"),
    ("withdrw my donaton", "withdraw"),
    ("what do i do to sign in", "login"),
    ("has the admin said yes to my ngo", "my_approval"),
]
OFF_TOPIC = ["is it going to snow this weekend", "asdf qwer zxcv", "do you know any good riddles"]


def _words(s):
    return set(re.findall(r"[a-z]+", s.lower()))


class ModelBehaviour(unittest.TestCase):
    def test_paraphrases_and_typos(self):
        for text, expected in PARAPHRASES:
            with self.subTest(text=text):
                self.assertEqual(ml_intent.classify(text), expected)

    def test_off_topic_is_refused(self):
        for text in OFF_TOPIC:
            with self.subTest(text=text):
                self.assertIsNone(ml_intent.classify(text))

    def test_empty_and_long_input_are_safe(self):
        self.assertIsNone(ml_intent.classify(""))
        self.assertIsNone(ml_intent.classify("   "))
        ml_intent.classify("register " * 300)  # must not raise

    def test_only_known_intents_are_returned(self):
        known = set(training_data.EXAMPLES)
        for text, _ in PARAPHRASES:
            self.assertIn(ml_intent.classify(text), known | {None})
        self.assertNotIn("offtopic", {ml_intent.classify(t) for t in OFF_TOPIC})


class TrainingHygiene(unittest.TestCase):
    def test_test_sentences_are_not_in_training_data(self):
        trained = [_words(s) for v in training_data.EXAMPLES.values() for s in v]
        for text, _ in PARAPHRASES + [(t, None) for t in OFF_TOPIC]:
            w = _words(text)
            for t in trained:
                overlap = len(w & t) / max(len(w), 1)
                self.assertLess(overlap, 0.8, f"{text!r} leaks into training data")

    def test_every_intent_has_examples(self):
        for intent, examples in training_data.EXAMPLES.items():
            self.assertGreaterEqual(len(examples), 3, intent)


class RulesStillWin(unittest.TestCase):
    def test_strong_rule_beats_model(self):
        intent, score = intent_handler.detect_scored("how can i create an account")
        self.assertEqual(intent, "register")
        self.assertGreaterEqual(score, 3)


if __name__ == "__main__":
    unittest.main()
