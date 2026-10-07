"""
Metric functions used by run_evaluation.py - plain Python, no sklearn, so
every formula is visible and can be quoted directly in the report.
"""

import math
from collections import Counter


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def accuracy(y_true: list, y_pred: list) -> float:
    return safe_div(sum(t == p for t, p in zip(y_true, y_pred)), len(y_true))


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion - with test sets this small,
    the interval matters as much as the point estimate."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def confusion_matrix(y_true: list, y_pred: list, labels: list) -> list[list[int]]:
    """Rows = true label, columns = predicted label, in `labels` order."""
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for t, p in zip(y_true, y_pred):
        if t in index and p in index:
            matrix[index[t]][index[p]] += 1
    return matrix


def classification_report(y_true: list, y_pred: list, labels: list) -> dict:
    """Per-class precision / recall / F1 plus macro averages."""
    tp, fp, fn = Counter(), Counter(), Counter()
    for t, p in zip(y_true, y_pred):
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    support = Counter(y_true)

    per_class = {}
    for label in labels:
        precision = safe_div(tp[label], tp[label] + fp[label])
        recall = safe_div(tp[label], tp[label] + fn[label])
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": safe_div(2 * precision * recall, precision + recall),
            "support": support[label],
        }

    present = [l for l in labels if support[l] > 0]
    macro = {
        key: safe_div(sum(per_class[l][key] for l in present), len(present))
        for key in ("precision", "recall", "f1")
    }
    return {"per_class": per_class, "macro": macro, "accuracy": accuracy(y_true, y_pred)}


def binary_metrics(y_true: list[bool], y_pred: list[bool]) -> dict:
    """For the injection filter: positive = attack, predicted positive = blocked."""
    tp = sum(t and p for t, p in zip(y_true, y_pred))
    fp = sum((not t) and p for t, p in zip(y_true, y_pred))
    tn = sum((not t) and (not p) for t, p in zip(y_true, y_pred))
    fn = sum(t and (not p) for t, p in zip(y_true, y_pred))
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision,
        "recall_block_rate": recall,
        "false_positive_rate": safe_div(fp, fp + tn),
        "f1": safe_div(2 * precision * recall, precision + recall),
        "accuracy": safe_div(tp + tn, len(y_true)),
    }


# --- Retrieval metrics (document-level relevance) ----------------------------

def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Share of the top-k retrieved chunks that come from a relevant document."""
    top = retrieved[:k]
    return safe_div(sum(doc in relevant for doc in top), len(top))


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Share of the relevant documents that appear at least once in the top-k."""
    return safe_div(len(set(retrieved[:k]) & relevant), len(relevant))


def hit_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, doc in enumerate(retrieved, start=1):
        if doc in relevant:
            return 1.0 / rank
    return 0.0
