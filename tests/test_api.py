from fastapi.testclient import TestClient
from sqlalchemy import select, update

from experience_reco import database as db
from experience_reco.api import create_app


def test_health_and_openapi(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["model_version"]
    assert response.json()["stale"] is False
    assert client.get("/openapi.json").status_code == 200


def test_uninitialized_database_is_unhealthy(tmp_path):
    engine = db.get_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with TestClient(create_app(engine)) as client:
        assert client.get("/health").status_code == 503
    engine.dispose()


def test_personalized_scoped_results(client):
    response = client.get("/recommendations/1?category=chalet")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "hybrid"
    assert len(payload["items"]) > 0
    assert all(1 <= item["listing_id"] <= 40 for item in payload["items"])


def test_unknown_and_cold_users_fall_back(client):
    for uid in (0, 30, 999999):
        response = client.get(f"/recommendations/{uid}?category=farm")
        assert response.status_code == 200
        assert response.json()["source"] == "popularity"
        assert response.json()["items"]


def test_popular_city_is_strict_filter(client):
    payload = client.get("/popular", params={"category": "scuba", "city": "Doha"}).json()
    assert payload["items"]
    assert all(item["city"] == "Doha" for item in payload["items"])
    assert client.get("/popular?category=scuba&city=Unknown").json()["items"] == []


def test_similar_never_returns_self_or_other_category(client):
    payload = client.get("/similar/4").json()
    assert payload["items"]
    assert all(
        1 <= item["listing_id"] <= 40 and item["listing_id"] != 4 for item in payload["items"]
    )


def test_session_excludes_recent_and_changes_ranking(client):
    original = client.get("/recommendations/0?category=chalet").json()
    changed = client.get("/recommendations/0?category=chalet&recent_listing_ids=1,2").json()
    assert changed["session_boost_applied"]
    assert all(item["listing_id"] not in (1, 2) for item in changed["items"])
    assert [i["listing_id"] for i in changed["items"]] != [
        i["listing_id"] for i in original["items"]
    ]
    assert any(i["reason"] == "similar_to_recent_view" for i in changed["items"])


def test_foreign_category_session_cannot_contaminate_results(client):
    original = client.get("/recommendations/0?category=chalet").json()
    changed = client.get("/recommendations/0?category=chalet&recent_listing_ids=41,999999").json()
    assert changed["items"] == original["items"]
    assert changed["session_boost_applied"] is False


def test_explicit_city_applies_to_personalization_and_session(client):
    payload = client.get(
        "/recommendations/1",
        params={"category": "chalet", "city": "Dubai", "recent_listing_ids": "2"},
    ).json()
    assert all(item["city"] == "Dubai" for item in payload["items"])


def test_daytime_interactions_are_filtered_immediately(client, trained):
    engine = trained[0]
    first = client.get("/recommendations/0?category=chalet").json()["items"][0]["listing_id"]
    # An inactive catalog item is filtered without retraining.
    with engine.begin() as conn:
        conn.execute(
            update(db.listings).where(db.listings.c.ListingId == first).values(IsActive=False)
        )
    try:
        assert client.get(f"/similar/{first}").status_code == 404
        items = client.get("/recommendations/0?category=chalet").json()["items"]
        assert first not in [item["listing_id"] for item in items]
    finally:
        with engine.begin() as conn:
            conn.execute(
                update(db.listings).where(db.listings.c.ListingId == first).values(IsActive=True)
            )


def test_seen_items_never_serve(client, trained):
    with trained[0].connect() as conn:
        seen = set(
            conn.execute(
                select(db.interactions.c.ListingId).where(db.interactions.c.UserId == 1)
            ).scalars()
        )
    items = client.get("/recommendations/1?category=chalet&recent_listing_ids=1").json()["items"]
    assert not seen.intersection(item["listing_id"] for item in items)


def test_errors_and_limits(client):
    for route in (
        "/recommendations/1?category=missing",
        "/popular?category=missing",
        "/similar/99999",
    ):
        assert client.get(route).status_code == 404
    for query in (
        "recent_listing_ids=abc",
        "recent_listing_ids=-1",
        "limit=0",
        "limit=51",
        "recent_listing_ids=1,2,3,4,5,6,7,8,9,10,11",
    ):
        assert client.get(f"/recommendations/1?category=chalet&{query}").status_code == 422
    assert client.get("/recommendations/-1?category=chalet").status_code == 422
    assert client.get("/recommendations/1").status_code == 422
