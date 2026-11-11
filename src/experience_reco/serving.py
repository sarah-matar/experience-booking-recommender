"""Read-only online ranking: batch candidates + bounded, category-safe session signal."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine

from . import database as db


class RecommendationStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def category(self, code: str) -> dict | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(select(db.categories).where(db.categories.c.Code == code))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def health(self) -> dict:
        with self.engine.connect() as conn:
            conn.execute(select(1))
            run = (
                conn.execute(select(db.model_runs).order_by(db.model_runs.c.RunId.desc()))
                .mappings()
                .first()
            )
        age = (
            (datetime.now(timezone.utc).replace(tzinfo=None) - run["TrainedAt"]).total_seconds()
            if run
            else None
        )
        return {
            "status": "ok" if run else "not_ready",
            "model_version": run["ModelVersion"] if run else None,
            "snapshot_age_hours": round(age / 3600, 2) if age is not None else None,
            "stale": age > 36 * 3600 if age is not None else True,
        }

    def catalog(self, conn, cid: int, city: str | None = None) -> dict:
        query = select(db.listings).where(
            db.listings.c.CategoryId == cid, db.listings.c.IsActive.is_(True)
        )
        if city:
            query = query.where(db.listings.c.City == city)
        return {r["ListingId"]: dict(r) for r in conn.execute(query).mappings()}

    def pack(self, item: dict, score: float, reason: str) -> dict:
        return {
            "listing_id": item["ListingId"],
            "title": item["Title"],
            "city": item["City"],
            "price": item["BasePrice"],
            "currency": item["Currency"],
            "score": round(float(score), 6),
            "reason": reason,
        }

    def popular(self, category: dict, city: str | None, limit: int = 10) -> dict:
        with self.engine.connect() as conn:
            pool = self.catalog(conn, category["CategoryId"], city)
            rows = conn.execute(
                select(db.popular_listings)
                .where(
                    db.popular_listings.c.CategoryId == category["CategoryId"],
                    db.popular_listings.c.City == (city or ""),
                )
                .order_by(db.popular_listings.c.Rank)
            ).mappings()
            items = [
                self.pack(pool[r["ListingId"]], r["Score"], "popular_near_you")
                for r in rows
                if r["ListingId"] in pool
            ][:limit]
        return {"category": category["Code"], "city": city, "source": "popularity", "items": items}

    def similar(self, listing_id: int, limit: int = 10) -> dict | None:
        with self.engine.connect() as conn:
            original = (
                conn.execute(
                    select(db.listings).where(
                        db.listings.c.ListingId == listing_id, db.listings.c.IsActive.is_(True)
                    )
                )
                .mappings()
                .first()
            )
            if not original:
                return None
            pool = self.catalog(conn, original["CategoryId"])
            rows = conn.execute(
                select(db.similar_listings)
                .where(db.similar_listings.c.ListingId == listing_id)
                .order_by(db.similar_listings.c.Rank)
            ).mappings()
            items = [
                self.pack(pool[r["SimilarListingId"]], r["Score"], "similar_experience")
                for r in rows
                if r["SimilarListingId"] in pool and r["SimilarListingId"] != listing_id
            ][:limit]
        return {"listing_id": listing_id, "items": items}

    def recommend(
        self, user_id: int, category: dict, recent: list[int], city: str | None, limit: int
    ) -> dict:
        with self.engine.connect() as conn:
            cid = category["CategoryId"]
            user = (
                conn.execute(select(db.users).where(db.users.c.UserId == user_id))
                .mappings()
                .first()
            )
            preferred_city = city or (user["City"] if user else None)
            pool = self.catalog(conn, cid, city)
            # Guests use user_id=0 (or any unknown id); cold category users have no batch rows.
            batch = list(
                conn.execute(
                    select(db.user_recommendations)
                    .where(
                        db.user_recommendations.c.UserId == user_id,
                        db.user_recommendations.c.CategoryId == cid,
                    )
                    .order_by(db.user_recommendations.c.Rank)
                ).mappings()
            )
            source = "hybrid" if batch else "popularity"
            # Exclude fresh daytime interactions as well as the overnight history.
            seen = set(
                conn.execute(
                    select(db.interactions.c.ListingId).where(db.interactions.c.UserId == user_id)
                ).scalars()
            )
            excluded = seen | set(recent)
            base = {
                r["ListingId"]: 1 / (1 + 0.05 * (r["Rank"] - 1))
                for r in batch
                if r["ListingId"] in pool and r["ListingId"] not in excluded
            }
            reasons = {lid: "hybrid_personalized" for lid in base}
            fallback = list(
                conn.execute(
                    select(db.popular_listings).where(
                        db.popular_listings.c.CategoryId == cid,
                        db.popular_listings.c.City.in_([preferred_city or "", ""]),
                    )
                ).mappings()
            )
            # Local fallback first, then category-wide backfill; never leak across explicit city filter.
            fallback.sort(key=lambda r: (r["City"] != (preferred_city or ""), r["Rank"]))
            for r in fallback:
                lid = r["ListingId"]
                if lid in pool and lid not in excluded and lid not in base:
                    base[lid] = (1.0 if not batch else 0.15) / (1 + 0.05 * (r["Rank"] - 1))
                    reasons[lid] = "popular_near_you"
            session = {}
            # Last ID is most recent. Discard IDs from other categories or invalid IDs.
            valid_recent = [lid for lid in recent if lid in pool]
            for position, lid in enumerate(reversed(valid_recent)):
                decay = 0.8**position
                rows = conn.execute(
                    select(db.similar_listings).where(db.similar_listings.c.ListingId == lid)
                ).mappings()
                for r in rows:
                    other = r["SimilarListingId"]
                    if other in pool and other not in excluded:
                        session[other] = max(session.get(other, 0), max(0, r["Score"]) * decay)
            final = {}
            for lid in set(base) | set(session):
                final[lid] = base.get(lid, 0) + 0.55 * session.get(lid, 0)
                if session.get(lid, 0) > 0:
                    reasons[lid] = "similar_to_recent_view"
            ordered = sorted(final, key=lambda lid: (-final[lid], lid))[:limit]
            version = conn.execute(
                select(db.model_runs.c.ModelVersion).order_by(db.model_runs.c.RunId.desc()).limit(1)
            ).scalar()
            items = [self.pack(pool[lid], final[lid], reasons[lid]) for lid in ordered]
        return {
            "user_id": user_id,
            "category": category["Code"],
            "source": source,
            "session_boost_applied": bool(session),
            "model_version": version,
            "items": items,
        }
