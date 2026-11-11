"""Full-catalog top-k metrics, with identical candidates for model and baseline."""

from __future__ import annotations

import numpy as np


def ranking_metrics(ranking: list[int], relevant: set[int], k: int = 10) -> dict:
    if not relevant:
        raise ValueError("Metrics require at least one relevant item")
    hits = np.asarray([int(i in relevant) for i in ranking[:k]], dtype=float)
    dcg = float(np.sum(hits / np.log2(np.arange(len(hits)) + 2)))
    idcg = float(np.sum(1 / np.log2(np.arange(min(len(relevant), k)) + 2)))
    return {
        "precision@10": float(hits.sum() / k),
        "recall@10": float(hits.sum() / len(relevant)),
        "ndcg@10": dcg / idcg,
    }


def mean_metrics(rows: list[dict]) -> dict:
    return {
        key: float(np.mean([r[key] for r in rows])) if rows else 0.0
        for key in ("precision@10", "recall@10", "ndcg@10")
    }
