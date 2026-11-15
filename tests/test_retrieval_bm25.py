import unittest

from printcare.retrieval.bm25 import BM25Index


class BM25Test(unittest.TestCase):
    def test_more_matches_rank_higher(self):
        index = BM25Index([["热床", "热床", "热床"], ["热床", "线缆"], ["电源"]])

        scores = index.scores(["热床"])

        self.assertGreater(scores[0], scores[1])
        self.assertEqual(scores[2], 0.0)

    def test_rare_terms_score_higher_than_common_terms(self):
        index = BM25Index([["热床", "线缆"], ["热床", "传感器"], ["热床", "电源"]])

        common = index.scores(["热床"])[0]
        rare = index.scores(["传感器"])[1]

        self.assertGreater(rare, common)

    def test_empty_query_scores_zero(self):
        index = BM25Index([["热床"]])

        self.assertEqual(index.scores([]), [0.0])

    def test_empty_corpus_is_safe(self):
        index = BM25Index([])

        self.assertEqual(index.scores(["热床"]), [])

    def test_unknown_term_scores_zero(self):
        index = BM25Index([["热床"]])

        self.assertEqual(index.scores(["不存在的词"]), [0.0])


if __name__ == "__main__":
    unittest.main()
