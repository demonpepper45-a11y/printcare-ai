"""A small BM25 implementation used for keyword retrieval."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence


class BM25Index:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(
        self,
        documents: Sequence[Sequence[str]],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.document_count = len(documents)
        self.document_lengths = [len(document) for document in documents]
        self.average_length = (
            sum(self.document_lengths) / self.document_count if self.document_count else 0.0
        )
        self.term_frequencies: list[Counter[str]] = [Counter(document) for document in documents]
        self.document_frequencies: Counter[str] = Counter()
        for frequencies in self.term_frequencies:
            self.document_frequencies.update(frequencies.keys())

    def scores(self, query_tokens: Sequence[str]) -> list[float]:
        scores = [0.0] * self.document_count
        if not query_tokens or not self.document_count:
            return scores

        query_terms: Counter[str] = Counter(query_tokens)
        for term, query_frequency in query_terms.items():
            document_frequency = self.document_frequencies.get(term, 0)
            if document_frequency == 0:
                continue
            idf = math.log(
                1.0 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for index, frequencies in enumerate(self.term_frequencies):
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                length_ratio = self.document_lengths[index] / (self.average_length or 1.0)
                denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)
                scores[index] += (
                    query_frequency * idf * (term_frequency * (self.k1 + 1.0)) / denominator
                )
        return scores
