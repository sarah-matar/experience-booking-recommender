import math

import pytest

from experience_reco.evaluation import mean_metrics, ranking_metrics
from experience_reco.features import aggregate
from experience_reco.training import ranked


def test_perfect_ranking():
    m = ranking_metrics([3, 5], {3, 5})
    assert m == {"precision@10": 0.2, "recall@10": 1.0, "ndcg@10": 1.0}


def test_nontrivial_ndcg():
    m = ranking_metrics([9, 3, 5], {3, 5})
    assert m["ndcg@10"] == pytest.approx((1 / math.log2(3) + 0.5) / (1 + 1 / math.log2(3)))


def test_empty_hits():
    assert ranking_metrics([7], {1}) == dict.fromkeys(("precision@10", "recall@10", "ndcg@10"), 0.0)


def test_empty_relevance_is_invalid():
    with pytest.raises(ValueError):
        ranking_metrics([], set())


def test_empty_macro_defined():
    assert mean_metrics([])["ndcg@10"] == 0


def test_rank_ties_are_stable_and_excluded():
    assert ranked([3, 1, 2], [1.0, 1.0, 1.0], {2}) == [1, 3]


def test_review_weight_subtracts_and_vetoes():
    rows = [
        dict(UserId=1, ListingId=2, Weight=0.5, Signal="view"),
        dict(UserId=1, ListingId=2, Weight=-2.0, Signal="review"),
    ]
    strength, seen, disliked = aggregate(rows)
    assert strength[(1, 2)] == -1.5
    assert seen[1] == {2}
    assert disliked[1] == {2}
