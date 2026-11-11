"""Leakage-safe metadata + training-only user profiles for LightFM."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
from lightfm.data import Dataset
from scipy.sparse import coo_matrix


@dataclass
class Matrices:
    dataset: Dataset
    user_features: object
    item_features: object
    interactions: coo_matrix
    weights: coo_matrix
    user_ids: list[int]
    item_ids: list[int]
    seen: dict[int, set[int]]
    disliked: dict[int, set[int]]
    strengths: dict[tuple[int, int], float]


def aggregate(events: list[dict]) -> tuple[dict, dict, dict]:
    strengths = defaultdict(float)
    seen, disliked = defaultdict(set), defaultdict(set)
    for e in events:
        pair = (e["UserId"], e["ListingId"])
        strengths[pair] += e["Weight"]
        seen[pair[0]].add(pair[1])
        if e["Signal"] == "review" and e["Weight"] < 0:
            disliked[pair[0]].add(pair[1])
    return dict(strengths), seen, disliked


def build_matrices(users: list[dict], items: list[dict], events: list[dict],
                   tags: dict[int, list[str]], category: str) -> Matrices:
    # Per-category vocabularies include all catalog metadata, never test behaviour.
    uids = sorted(u["UserId"] for u in users)
    iids = sorted(i["ListingId"] for i in items)
    by_item = {i["ListingId"]: i for i in items}
    strengths, seen, disliked = aggregate(events)
    item_features = {}
    for i in items:
        lid = i["ListingId"]
        item_features[lid] = {**{f"tag:{t}": 2.0 for t in tags[lid]},
            f"city:{i['City']}": 1.0, f"price:{i['PriceBucket']}": 1.0,
            f"category:{category}": .2}
    profiles = defaultdict(Counter)
    for (uid, lid), strength in strengths.items():
        if strength > 0 and lid not in disliked[uid]:
            i = by_item[lid]
            confidence = min(strength, 8.0)
            profiles[uid].update({f"tag:{t}": confidence for t in tags[lid]})
            profiles[uid][f"price:{i['PriceBucket']}"] += confidence
    user_features = {}
    for u in users:
        uid = u["UserId"]
        profile = profiles[uid]
        total = sum(profile.values()) or 1
        user_features[uid] = {f"city:{u['City']}": 1.0,
            f"category:{category}": .2,
            **{f: 5.0 * w / total for f, w in profile.items()}}
    dataset = Dataset(user_identity_features=True, item_identity_features=False)
    dataset.fit(uids, iids,
        user_features=sorted({f for fs in user_features.values() for f in fs}),
        item_features=sorted({f for fs in item_features.values() for f in fs}))
    positives = [(uid, lid, min(weight, 10.0)) for (uid, lid), weight in sorted(strengths.items())
                 if weight > 0 and lid not in disliked[uid]]
    interactions, weights = dataset.build_interactions(positives)
    # build_interactions returns +1 labels; signed event weights aggregate BEFORE this step.
    return Matrices(dataset, dataset.build_user_features(sorted(user_features.items())),
                    dataset.build_item_features(sorted(item_features.items())),
                    interactions.astype(np.float32), weights.astype(np.float32),
                    uids, iids, seen, disliked, strengths)
