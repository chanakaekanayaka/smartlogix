"""Unit tests for evaluation/metrics.py - hand-computed expected values."""

import unittest

from evaluation.metrics import (
    binary_metrics, classification_report, confusion_matrix, hit_at_k,
    precision_at_k, recall_at_k, reciprocal_rank, wilson_interval,
)


class ClassificationTests(unittest.TestCase):
    def test_classification_report(self):
        y_true = ["a", "a", "b", "b"]
        y_pred = ["a", "b", "b", "b"]
        report = classification_report(y_true, y_pred, ["a", "b"])
        self.assertAlmostEqual(report["accuracy"], 0.75)
        self.assertAlmostEqual(report["per_class"]["a"]["precision"], 1.0)
        self.assertAlmostEqual(report["per_class"]["a"]["recall"], 0.5)
        self.assertAlmostEqual(report["per_class"]["b"]["precision"], 2 / 3)
        self.assertAlmostEqual(report["per_class"]["b"]["recall"], 1.0)

    def test_macro_average_ignores_absent_classes(self):
        report = classification_report(["a"], ["a"], ["a", "b"])
        self.assertAlmostEqual(report["macro"]["f1"], 1.0)

    def test_confusion_matrix(self):
        self.assertEqual(confusion_matrix(["a", "a", "b"], ["a", "b", "b"], ["a", "b"]),
                         [[1, 1], [0, 1]])

    def test_binary_metrics(self):
        m = binary_metrics([True, True, False, False], [True, False, True, False])
        self.assertEqual((m["tp"], m["fn"], m["fp"], m["tn"]), (1, 1, 1, 1))
        self.assertAlmostEqual(m["recall_block_rate"], 0.5)
        self.assertAlmostEqual(m["false_positive_rate"], 0.5)

    def test_wilson_interval_contains_point_estimate(self):
        low, high = wilson_interval(8, 10)
        self.assertLess(low, 0.8)
        self.assertGreater(high, 0.8)
        self.assertEqual(wilson_interval(0, 0), (0.0, 0.0))


class RetrievalTests(unittest.TestCase):
    retrieved = ["x.md", "a.md", "a.md", "b.md"]
    relevant = {"a.md", "b.md"}

    def test_precision_at_k(self):
        self.assertAlmostEqual(precision_at_k(self.retrieved, self.relevant, 3), 2 / 3)

    def test_recall_at_k_counts_unique_documents(self):
        self.assertAlmostEqual(recall_at_k(self.retrieved, self.relevant, 3), 0.5)
        self.assertAlmostEqual(recall_at_k(self.retrieved, self.relevant, 4), 1.0)

    def test_hit_and_reciprocal_rank(self):
        self.assertEqual(hit_at_k(self.retrieved, self.relevant, 1), 0.0)
        self.assertEqual(hit_at_k(self.retrieved, self.relevant, 2), 1.0)
        self.assertAlmostEqual(reciprocal_rank(self.retrieved, self.relevant), 0.5)


if __name__ == "__main__":
    unittest.main()
