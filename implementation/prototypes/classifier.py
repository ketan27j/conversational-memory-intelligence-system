"""P2 (ADR-001): "start with an AI model, then graduate... once there is
enough data, train a small classifier on those examples and switch over."
This is that small classifier — a multinomial Naive Bayes over bag-of-words
features, pure Python (no numpy/sklearn dependency added for a stretch
prototype; `requirements.txt` has neither today).

Deliberately not the thing that replaces `AnthropicWriteGateJudge` in this
milestone — ADR-001 frames this as an experiment that informs a future
graduation decision (`classifier_experiment.py`), not a production swap.
"""
import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class NaiveBayesWriteGateClassifier:
    def __init__(self) -> None:
        self._word_counts: dict[bool, Counter[str]] = {True: Counter(), False: Counter()}
        self._word_totals: dict[bool, int] = {True: 0, False: 0}
        self._doc_counts: dict[bool, int] = {True: 0, False: 0}
        self._vocab: set[str] = set()

    def train(self, examples: list[tuple[str, bool]]) -> None:
        for text, label in examples:
            self._doc_counts[label] += 1
            for word in _tokenize(text):
                self._vocab.add(word)
                self._word_counts[label][word] += 1
                self._word_totals[label] += 1

    def predict(self, text: str) -> bool:
        words = _tokenize(text)
        total_docs = self._doc_counts[True] + self._doc_counts[False]
        vocab_size = max(len(self._vocab), 1)

        best_label = True
        best_log_prob = float("-inf")
        for label in (True, False):
            doc_count = self._doc_counts[label]
            prior = doc_count / total_docs if total_docs and doc_count else 1e-9
            log_prob = math.log(prior)
            denom = self._word_totals[label] + vocab_size  # Laplace smoothing
            for word in words:
                count = self._word_counts[label][word]
                log_prob += math.log((count + 1) / denom)
            if log_prob > best_log_prob:
                best_log_prob = log_prob
                best_label = label
        return best_label
