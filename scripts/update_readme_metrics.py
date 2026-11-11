"""Render the README table from the actual, checked-in experiment output."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
report = json.loads((root / "docs/metrics.json").read_text())
lines = [
    f"Seed-{report['seed']} run: **{report['dataset']['users']:,} users · "
    f"{report['dataset']['listings']:,} listings · {report['dataset']['interactions']:,} interactions**. "
    "All figures below are actual out-of-time measurements.",
    "",
    "| Model (category macro-average) | Precision@10 | Recall@10 | NDCG@10 |",
    "|---|---:|---:|---:|",
]
for algorithm, label in (("popularity", "City/category popularity"), ("lightfm", "LightFM hybrid")):
    m = report["macro"][algorithm]
    lines.append(
        f"| {label} | {m['precision@10']:.4f} | {m['recall@10']:.4f} | {m['ndcg@10']:.4f} |"
    )
lift = report["macro"]["lightfm"]["ndcg@10"] / report["macro"]["popularity"]["ndcg@10"] - 1
lines += [
    "",
    f"**Relative NDCG@10 improvement: {lift:.1%}.** This is synthetic offline lift, not online impact.",
    "",
    "| Category | Evaluated users | Hybrid NDCG@10 | Popularity NDCG@10 |",
    "|---|---:|---:|---:|",
]
for c in report["categories"]:
    lines.append(
        f"| {c['category']} | {c['evaluated_users']} | {c['lightfm']['ndcg@10']:.4f} | {c['popularity']['ndcg@10']:.4f} |"
    )
lines += [
    "",
    "Full precision/recall/NDCG by category and run parameters: [`docs/metrics.json`](docs/metrics.json).",
]
p = root / "README.md"
text = p.read_text()
start = "<!-- METRICS:START -->"
end = "<!-- METRICS:END -->"
p.write_text(
    text.split(start)[0] + start + "\n" + "\n".join(lines) + "\n" + end + text.split(end)[1]
)
