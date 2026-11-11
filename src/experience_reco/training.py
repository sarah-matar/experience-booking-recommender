"""Evaluate out-of-time, refit on all observations, atomically publish four output tables."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from lightfm import LightFM
import numpy as np
from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from . import database as db
from .evaluation import mean_metrics, ranking_metrics
from .features import aggregate, build_matrices


def snapshot(engine: Engine) -> dict:
    with engine.connect() as conn:
        result = {
            name: [dict(r) for r in conn.execute(select(table)).mappings()]
            for name, table in (
                ("users", db.users),
                ("items", db.listings),
                ("categories", db.categories),
                ("events", db.interactions),
            )
        }
        tag_rows = conn.execute(
            select(db.listing_tags.c.ListingId, db.tags.c.Name).join(db.tags)
        ).all()
    tags = defaultdict(list)
    for lid, tag in tag_rows:
        tags[lid].append(tag)
    result["tags"] = tags
    return result


def fit(matrices, *, epochs: int, seed: int):
    if matrices.interactions.nnz == 0:
        return None
    model = LightFM(
        no_components=32,
        loss="warp",
        learning_rate=0.035,
        item_alpha=1e-6,
        user_alpha=1e-6,
        random_state=seed,
    )
    model.fit(
        matrices.interactions,
        sample_weight=matrices.weights,
        user_features=matrices.user_features,
        item_features=matrices.item_features,
        epochs=epochs,
        num_threads=1,
    )
    return model


def score(model, matrices, uid: int) -> np.ndarray:
    uidx = matrices.dataset.mapping()[0][uid]
    return model.predict(
        uidx,
        np.arange(len(matrices.item_ids), dtype=np.int32),
        user_features=matrices.user_features,
        item_features=matrices.item_features,
        num_threads=1,
    )


def ranked(ids, scores, excluded=frozenset()) -> list[int]:
    return [
        int(ids[j])
        for j in np.lexsort((np.asarray(ids), -np.asarray(scores)))
        if ids[j] not in excluded
    ]


def popularity(items: list[dict], events: list[dict]) -> dict[int, float]:
    strengths, _, disliked = aggregate(events)
    counts = {i["ListingId"]: 0.0 for i in items}
    # Count each user-item once, with bounded confidence: repeated clicks cannot dominate.
    for (uid, lid), weight in strengths.items():
        if weight > 0 and lid not in disliked[uid]:
            counts[lid] += min(weight, 10.0)
    return counts


def city_popularity(items, counts, city):
    # Same-city boost, then category-wide backfill. USD prices are bucketed per category.
    peak = max(counts.values(), default=0) + 1
    return np.asarray([counts[i["ListingId"]] + peak * (i["City"] == city) for i in items])


def evaluate(users, items, events, tags, code, cutoff, *, epochs, seed):
    items = sorted([i for i in items if i["CreatedAt"] <= cutoff], key=lambda x: x["ListingId"])
    item_ids = {i["ListingId"] for i in items}
    train = [e for e in events if e["CreatedAt"] <= cutoff and e["ListingId"] in item_ids]
    test = [e for e in events if e["CreatedAt"] > cutoff and e["ListingId"] in item_ids]
    matrices = build_matrices(users, items, train, tags, code)
    model = fit(matrices, epochs=epochs, seed=seed)
    strengths, _, disliked = aggregate(test)
    relevant = defaultdict(set)
    for (uid, lid), weight in strengths.items():
        if weight > 0 and lid not in matrices.seen[uid] and lid not in disliked[uid]:
            relevant[uid].add(lid)
    counts = popularity(items, train)
    hybrid_rows, baseline_rows = [], []
    warm_users = {uid for (uid, _), w in matrices.strengths.items() if w > 0}
    for u in users:
        uid = u["UserId"]
        if not relevant[uid] or uid not in warm_users or model is None:
            continue
        excluded = matrices.seen[uid]
        predictions = ranked(matrices.item_ids, score(model, matrices, uid), excluded)
        baseline = ranked(matrices.item_ids, city_popularity(items, counts, u["City"]), excluded)
        hybrid_rows.append(ranking_metrics(predictions, relevant[uid]))
        baseline_rows.append(ranking_metrics(baseline, relevant[uid]))
    return {
        "category": code,
        "catalog_size": len(items),
        "train_events": len(train),
        "test_events": len(test),
        "evaluated_users": len(hybrid_rows),
        "lightfm": mean_metrics(hybrid_rows),
        "popularity": mean_metrics(baseline_rows),
    }


def train_and_publish(
    engine: Engine, *, epochs: int = 45, seed: int = 42, report_dir: str | Path = "docs"
) -> dict:
    data = snapshot(engine)
    if not data["events"]:
        raise ValueError("No interactions: run the synthetic generator first")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    version = f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    cutoff = max(e["CreatedAt"] for e in data["events"]) - timedelta(days=30)
    report = {
        "model_version": version,
        "seed": seed,
        "epochs": epochs,
        "algorithm": "LightFM 1.17 WARP hybrid",
        "k": 10,
        "split_at_utc": cutoff.isoformat(),
        "evaluation": "global last-30-days holdout; unseen full-catalog ranking; warm users",
        "dataset": {
            "users": len(data["users"]),
            "listings": len(data["items"]),
            "interactions": len(data["events"]),
        },
        "categories": [],
    }
    user_rows, similar_rows, popular_rows, run_rows = [], [], [], []
    for category in data["categories"]:
        cid, code = category["CategoryId"], category["Code"]
        items = sorted(
            [i for i in data["items"] if i["CategoryId"] == cid and i["IsActive"]],
            key=lambda x: x["ListingId"],
        )
        if not items:
            continue
        iids = {i["ListingId"] for i in items}
        events = [e for e in data["events"] if e["ListingId"] in iids]
        metrics = evaluate(
            data["users"], items, events, data["tags"], code, cutoff, epochs=epochs, seed=seed
        )
        report["categories"].append(metrics)
        print(
            f"{code:16s} NDCG@10 hybrid={metrics['lightfm']['ndcg@10']:.4f} "
            f"baseline={metrics['popularity']['ndcg@10']:.4f}",
            flush=True,
        )
        # Refit serving model on ALL events only after the untouched holdout is evaluated.
        matrices = build_matrices(data["users"], items, events, data["tags"], code)
        model = fit(matrices, epochs=epochs, seed=seed)
        warm_users = {
            uid
            for (uid, lid), weight in matrices.strengths.items()
            if weight > 0 and lid not in matrices.disliked[uid]
        }
        if model is not None:
            for uid in matrices.user_ids:
                if uid not in warm_users:
                    continue
                scores = score(model, matrices, uid)
                by_score = dict(zip(matrices.item_ids, scores))
                for rank, lid in enumerate(
                    ranked(matrices.item_ids, scores, matrices.seen[uid])[:50], 1
                ):
                    user_rows.append(
                        dict(
                            UserId=uid,
                            CategoryId=cid,
                            Rank=rank,
                            ListingId=lid,
                            Score=float(by_score[lid]),
                            Reason="hybrid_personalized",
                            ModelVersion=version,
                            GeneratedAt=now,
                        )
                    )
            # Shared item-feature embeddings support listings with zero training interactions.
            _, embeddings = model.get_item_representations(matrices.item_features)
            norm = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / np.maximum(norm, 1e-8)
            cosine = embeddings @ embeddings.T
            for j, lid in enumerate(matrices.item_ids):
                similarities = dict(zip(matrices.item_ids, cosine[j]))
                for rank, other in enumerate(ranked(matrices.item_ids, cosine[j], {lid})[:30], 1):
                    similar_rows.append(
                        dict(
                            ListingId=lid,
                            SimilarListingId=other,
                            Rank=rank,
                            Score=float(similarities[other]),
                            ModelVersion=version,
                        )
                    )
        counts = popularity(items, events)
        for city in [""] + sorted({i["City"] for i in items}):
            pool = [i for i in items if not city or i["City"] == city]
            ids = [i["ListingId"] for i in pool]
            for rank, lid in enumerate(ranked(ids, [counts[lid] for lid in ids]), 1):
                popular_rows.append(
                    dict(
                        CategoryId=cid,
                        City=city,
                        Rank=rank,
                        ListingId=lid,
                        Score=counts[lid],
                        GeneratedAt=now,
                    )
                )
        for algorithm in ("lightfm", "popularity"):
            m = metrics[algorithm]
            run_rows.append(
                dict(
                    ModelVersion=version,
                    CategoryId=cid,
                    Algorithm=algorithm,
                    PrecisionAt10=m["precision@10"],
                    RecallAt10=m["recall@10"],
                    NdcgAt10=m["ndcg@10"],
                    EvaluatedUsers=metrics["evaluated_users"],
                    SplitAt=cutoff,
                    TrainedAt=now,
                )
            )
    report["macro"] = {
        algorithm: mean_metrics([c[algorithm] for c in report["categories"]])
        for algorithm in ("lightfm", "popularity")
    }
    if not report["categories"]:
        raise ValueError("No active categories; existing published outputs were left intact")
    # Readers see the previous complete snapshot OR the next complete snapshot, not partial categories.
    with engine.begin() as conn:
        for table, rows in (
            (db.user_recommendations, user_rows),
            (db.similar_listings, similar_rows),
            (db.popular_listings, popular_rows),
        ):
            conn.execute(delete(table))
            if rows:
                conn.execute(insert(table), rows)
        conn.execute(insert(db.model_runs), run_rows)
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    plot_report(report, directory)
    return report


def plot_report(report, directory: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    colors = ("#137C8B", "#AFBAC8")
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), constrained_layout=True)
    names = ("Precision@10", "Recall@10", "NDCG@10")
    for ax, key, label in zip(axes, ("precision@10", "recall@10", "ndcg@10"), names):
        vals = [report["macro"][a][key] for a in ("lightfm", "popularity")]
        bars = ax.bar(["LightFM hybrid", "City popularity"], vals, color=colors, width=0.6)
        ax.bar_label(bars, fmt="%.3f", padding=4)
        ax.set_title(label, fontweight="bold")
        ax.set_ylim(0, min(1.0, max(vals) * 1.3 + 0.01))
        ax.grid(axis="y", alpha=0.16)
        ax.set_axisbelow(True)
    fig.suptitle(
        "Out-of-time ranking quality · synthetic marketplace", fontsize=16, fontweight="bold"
    )
    fig.savefig(directory / "evaluation-overview.png", dpi=180, facecolor="white")
    plt.close(fig)
    rows = report["categories"]
    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    x = np.arange(len(rows))
    for delta, algorithm, label, color in (
        (-0.19, "lightfm", "LightFM hybrid", colors[0]),
        (0.19, "popularity", "City popularity", colors[1]),
    ):
        ax.barh(
            x + delta,
            [c[algorithm]["ndcg@10"] for c in rows],
            height=0.34,
            label=label,
            color=color,
        )
    ax.set_yticks(x, [c["category"].replace("_", " ").title() for c in rows])
    ax.invert_yaxis()
    ax.set_xlabel("NDCG@10 · full-catalog candidates")
    ax.set_title("Personalization within each category", fontsize=16, fontweight="bold", pad=16)
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.16)
    ax.set_axisbelow(True)
    fig.savefig(directory / "evaluation-by-category.png", dpi=180, facecolor="white")
    plt.close(fig)
