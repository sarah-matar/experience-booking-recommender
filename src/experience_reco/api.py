"""FastAPI factory: the API never trains models or loads unsafe model pickles."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .database import get_engine
from .serving import RecommendationStore


def create_app(engine: Engine | None = None) -> FastAPI:
    owned_engine = engine is None
    engine = engine or get_engine()
    store = RecommendationStore(engine)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned_engine:
            engine.dispose()

    app = FastAPI(
        title="Experience Booking Recommender",
        version="1.0.0",
        description="Synthetic portfolio demo. Batch LightFM + category-safe session personalization.",
        lifespan=lifespan,
    )

    def resolve_category(code: str):
        category = store.category(code)
        if not category:
            raise HTTPException(404, "Unknown category")
        return category

    @app.get("/health")
    def health():
        try:
            state = store.health()
        except SQLAlchemyError:
            raise HTTPException(503, "Database not initialized; run the batch first") from None
        if state["status"] != "ok":
            raise HTTPException(503, state)
        return state

    @app.get("/recommendations/{user_id}")
    def recommendations(
        user_id: int,
        category: str = Query(..., max_length=50),
        recent_listing_ids: str = Query("", max_length=250),
        city: str | None = Query(None, max_length=100),
        limit: int = Query(10, ge=1, le=50),
    ):
        if user_id < 0:
            raise HTTPException(422, "user_id must be nonnegative; 0 means guest")
        try:
            recent = [int(v.strip()) for v in recent_listing_ids.split(",") if v.strip()]
        except ValueError:
            raise HTTPException(
                422, "recent_listing_ids must be comma-separated positive integers"
            ) from None
        if len(recent) > 10 or any(v <= 0 for v in recent):
            raise HTTPException(422, "Provide at most 10 positive recent listing IDs, oldest first")
        recent = list(dict.fromkeys(reversed(recent)))[::-1]
        return store.recommend(user_id, resolve_category(category), recent, city, limit)

    @app.get("/similar/{listing_id}")
    def similar(listing_id: int, limit: int = Query(10, ge=1, le=30)):
        result = store.similar(listing_id, limit)
        if result is None:
            raise HTTPException(404, "Unknown or inactive listing")
        return result

    @app.get("/popular")
    def popular(
        category: str = Query(..., max_length=50),
        city: str | None = Query(None, max_length=100),
        limit: int = Query(10, ge=1, le=50),
    ):
        return store.popular(resolve_category(category), city, limit)

    return app
