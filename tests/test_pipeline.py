from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import func, select

from experience_reco import database as db
from experience_reco.features import build_matrices
from experience_reco.synthetic import WEIGHTS, generate
from experience_reco.training import snapshot


def test_expected_weight_contract():
    assert WEIGHTS == dict(
        booking=5.0, order=4.0, favourite=3.0, add_to_cart=2.0, click=1.0, view=0.5
    )


def test_outputs_and_run_audit_are_populated(trained):
    engine, generated, report = trained
    assert generated["listings"] == 320
    assert len(report["categories"]) == 8
    with engine.connect() as conn:
        for table in (db.user_recommendations, db.similar_listings, db.popular_listings):
            assert conn.scalar(select(func.count()).select_from(table)) > 0
        assert conn.scalar(select(func.count()).select_from(db.model_runs)) == 16
        assert len(set(conn.execute(select(db.user_recommendations.c.ModelVersion)).scalars())) == 1
    assert all(c["evaluated_users"] > 0 for c in report["categories"])
    for category in report["categories"]:
        for algorithm in ("lightfm", "popularity"):
            assert all(0 <= metric <= 1 for metric in category[algorithm].values())


def test_batch_ranking_excludes_all_seen_and_scopes_category(trained):
    engine, _, _ = trained
    data = snapshot(engine)
    seen = {(e["UserId"], e["ListingId"]) for e in data["events"]}
    category = {i["ListingId"]: i["CategoryId"] for i in data["items"]}
    with engine.connect() as conn:
        for row in conn.execute(select(db.user_recommendations)).mappings():
            assert (row["UserId"], row["ListingId"]) not in seen
            assert category[row["ListingId"]] == row["CategoryId"]
        for row in conn.execute(select(db.similar_listings)).mappings():
            assert row["ListingId"] != row["SimilarListingId"]
            assert category[row["ListingId"]] == category[row["SimilarListingId"]]


def test_temporal_cutoff_uses_only_train_events(trained):
    engine, _, report = trained
    data = snapshot(engine)
    cutoff = datetime.fromisoformat(report["split_at_utc"])
    for category in report["categories"]:
        cid = next(c["CategoryId"] for c in data["categories"] if c["Code"] == category["category"])
        ids = {i["ListingId"] for i in data["items"] if i["CategoryId"] == cid}
        train = [e for e in data["events"] if e["ListingId"] in ids and e["CreatedAt"] <= cutoff]
        assert len(train) == category["train_events"]
        assert all(e["CreatedAt"] <= cutoff for e in train)


def test_cold_item_uses_shared_content_features(trained):
    data = snapshot(trained[0])
    items = [i for i in data["items"] if i["CategoryId"] == 1]
    # No event for the last item. It must still have a meaningful content row.
    ids = {i["ListingId"] for i in items[:-1]}
    events = [e for e in data["events"] if e["ListingId"] in ids]
    m = build_matrices(data["users"], items, events, data["tags"], "chalet")
    assert m.item_features[-1].nnz >= 5
    assert m.item_features.shape[1] < len(items)  # item identity features disabled
    assert np.isfinite(m.item_features.data).all()
    assert (m.weights.data > 0).all()


def test_future_events_cannot_change_training_profiles(trained):
    data = snapshot(trained[0])
    cutoff = datetime.fromisoformat(trained[2]["split_at_utc"])
    items = [i for i in data["items"] if i["CategoryId"] == 1]
    ids = {i["ListingId"] for i in items}
    train = [e for e in data["events"] if e["ListingId"] in ids and e["CreatedAt"] <= cutoff]
    # Test-only timestamps are modified; training inputs remain exactly the same.
    a = build_matrices(data["users"], items, train, data["tags"], "chalet")
    for event in data["events"]:
        if event["CreatedAt"] > cutoff:
            event["Weight"] = 1000
    b = build_matrices(data["users"], items, train, data["tags"], "chalet")
    assert (a.user_features != b.user_features).nnz == 0
    assert (a.weights != b.weights).nnz == 0


def test_generator_is_repeatable_and_non_destructive(tmp_path):
    a = db.get_engine(f"sqlite:///{tmp_path / 'a.db'}")
    b = db.get_engine(f"sqlite:///{tmp_path / 'b.db'}")
    try:
        first = generate(a, seed=11, n_users=4, items_per_category=25)
        second = generate(b, seed=11, n_users=4, items_per_category=25)
        assert first == second
        assert snapshot(a)["events"] == snapshot(b)["events"]
        with pytest.raises(ValueError, match="already initialized"):
            generate(a, seed=11, n_users=4, items_per_category=25)
        assert len(snapshot(a)["events"]) == first["interactions"]
    finally:
        a.dispose()
        b.dispose()


def test_invalid_generator_size_has_no_side_effect(tmp_path):
    engine = db.get_engine(f"sqlite:///{tmp_path / 'invalid.db'}")
    with pytest.raises(ValueError):
        generate(engine, n_users=1)
    from sqlalchemy import inspect

    assert not inspect(engine).has_table("Users")
    engine.dispose()
