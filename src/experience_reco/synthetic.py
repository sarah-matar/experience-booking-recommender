"""Repeatable synthetic marketplace. Latent tastes are NEVER persisted as model features."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import insert
from sqlalchemy.engine import Engine

from . import database as db

CITIES = ("Kuwait City", "Dubai", "Doha", "Riyadh", "Muscat")
CATEGORIES = (
    ("chalet", "stay", ("pool", "sea_view", "family", "quiet", "luxury", "bbq")),
    ("farm", "stay", ("animals", "garden", "family", "quiet", "eco", "bbq")),
    ("desert_tent", "stay", ("stargazing", "adventure", "family", "quiet", "luxury", "bbq")),
    ("atv", "activity", ("adventure", "guided", "family", "sunset", "private", "beginner")),
    ("skydiving", "activity", ("adventure", "guided", "coastal", "sunset", "private", "beginner")),
    ("scuba", "activity", ("adventure", "guided", "coastal", "eco", "private", "beginner")),
    ("restaurant", "food", ("seafood", "vegan", "family", "quiet", "luxury", "outdoor")),
    ("market_product", "product", ("artisan", "eco", "family", "local", "luxury", "gift")),
)
WEIGHTS = {"booking": 5.0, "order": 4.0, "favourite": 3.0,
           "add_to_cart": 2.0, "click": 1.0, "view": 0.5}
BUCKETS = ("budget", "mid", "premium")
# Single currency avoids comparing raw amounts across currencies.
BASE_USD = {"chalet": 180, "farm": 130, "desert_tent": 90, "atv": 45,
            "skydiving": 400, "scuba": 100, "restaurant": 25, "market_product": 18}


def generate(engine: Engine, *, seed: int = 42, n_users: int = 360,
             items_per_category: int = 100) -> dict:
    """Initialize only an empty database; never silently replace a user's dataset."""
    if n_users < 4 or items_per_category < 25:
        raise ValueError("Use at least 4 users and 25 items per category")
    from sqlalchemy import inspect
    if inspect(engine).has_table("Users", schema=None if engine.dialect.name == "sqlite" else "dbo"):
        raise ValueError("Database already initialized. Use a new RECO_DATABASE_URL; no data was deleted.")
    db.metadata.create_all(engine)
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1)
    cat_rows, vendor_rows, item_rows, tag_links = [], [], [], []
    all_tags = sorted({t for _, _, ts in CATEGORIES for t in ts})
    tag_ids = {t: i + 1 for i, t in enumerate(all_tags)}
    item_meta = {}
    for cid, (code, vertical, choices) in enumerate(CATEGORIES, 1):
        cat_rows.append(dict(CategoryId=cid, Code=code, Vertical=vertical))
        for j in range(items_per_category):
            lid = (cid - 1) * items_per_category + j + 1
            city = CITIES[j % len(CITIES)]
            bucket = BUCKETS[int(rng.integers(3))]
            its_tags = sorted(rng.choice(choices, size=2, replace=False).tolist())
            vendor_rows.append(dict(VendorId=lid, Name=f"Demo Host {lid:04d}", City=city))
            item_rows.append(dict(ListingId=lid, CategoryId=cid, VendorId=lid,
                Title=f"{city} {code.replace('_', ' ').title()} {j + 1:03d}", City=city,
                BasePrice=round(BASE_USD[code] * {"budget": .65, "mid": 1., "premium": 1.8}[bucket], 2),
                Currency="USD", PriceBucket=bucket, IsActive=True, CreatedAt=start))
            tag_links.extend(dict(ListingId=lid, TagId=tag_ids[t]) for t in its_tags)
            item_meta[lid] = (city, bucket, its_tags)
    user_rows, event_rows, search_rows = [], [], []
    for uid in range(1, n_users + 1):
        home = CITIES[int(rng.integers(len(CITIES)))]
        budget = BUCKETS[int(rng.integers(3))]
        user_rows.append(dict(UserId=uid, City=home, CreatedAt=start))
        # Whole cold users have no interactions; serving must fall back.
        if uid % 30 == 0:
            continue
        for cid, (code, vertical, choices) in enumerate(CATEGORIES, 1):
            taste = set(rng.choice(choices, size=2, replace=False).tolist())
            ids = np.arange((cid - 1) * items_per_category + 1, cid * items_per_category + 1)
            utilities = []
            for lid in ids:
                city, bucket, its_tags = item_meta[int(lid)]
                utilities.append(2.0 * len(taste.intersection(its_tags)) +
                                 1.6 * (city == home) + 1.0 * (bucket == budget))
            utility = np.asarray(utilities)
            probabilities = np.exp((utility - utility.max()) / 1.15)
            probabilities /= probabilities.sum()
            # Fixed sparse observation counts; no future rows inform the feature builder.
            count = min(items_per_category - 5, int(rng.integers(23, 33)))
            chosen = rng.choice(ids, size=count, replace=False, p=probabilities)
            for lid in chosen:
                # Uniform timestamps make a single global time cutoff meaningful.
                when = start + timedelta(days=int(rng.integers(1, 120)),
                                         seconds=int(rng.integers(86400)))
                signal = str(rng.choice(["view", "click", "add_to_cart", "favourite", "purchase"],
                                       p=[.30, .24, .13, .18, .15]))
                if signal == "purchase":
                    signal = "booking" if vertical in ("stay", "activity") else "order"
                event_rows.append(dict(UserId=uid, ListingId=int(lid), Signal=signal,
                                       Weight=WEIGHTS[signal], Rating=None, CreatedAt=when))
                if signal in ("booking", "order") and rng.random() < .65:
                    rating = int(rng.choice([1, 2, 3, 4, 5], p=[.025, .035, .12, .40, .42]))
                    event_rows.append(dict(UserId=uid, ListingId=int(lid), Signal="review",
                        Weight=float(rating - 3), Rating=rating,
                        CreatedAt=when + timedelta(days=int(rng.integers(1, 4)))))
            # Low-rated exploration items can veto a weak prior positive signal.
            if rng.random() < .5:
                lid = int(rng.choice(ids))
                when = start + timedelta(days=int(rng.integers(1, 115)))
                event_rows.append(dict(UserId=uid, ListingId=lid, Signal="review", Weight=-2.,
                                       Rating=1, CreatedAt=when))
            search_rows.append(dict(UserId=uid, CategoryId=cid, City=home,
                QueryText=f"{sorted(taste)[0]} {code}",
                CreatedAt=start + timedelta(days=int(rng.integers(1, 120)))))
    with engine.begin() as conn:
        conn.execute(insert(db.categories), cat_rows)
        conn.execute(insert(db.users), user_rows)
        conn.execute(insert(db.vendors), vendor_rows)
        conn.execute(insert(db.tags), [dict(TagId=v, Name=k) for k, v in tag_ids.items()])
        conn.execute(insert(db.listings), item_rows)
        conn.execute(insert(db.listing_tags), tag_links)
        conn.execute(insert(db.interactions), event_rows)
        conn.execute(insert(db.searches), search_rows)
    return {"seed": seed, "users": n_users, "listings": len(item_rows),
            "interactions": len(event_rows), "searches": len(search_rows)}
