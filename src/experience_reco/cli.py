"""Small command surface; a process lock prevents overlapping nightly publications."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile

from .database import get_engine
from .synthetic import generate
from .training import train_and_publish


def main():
    parser = argparse.ArgumentParser(prog="experience-reco")
    parser.add_argument(
        "--database-url", default=None, help="Defaults to RECO_DATABASE_URL or local SQLite"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate", help="Create an empty synthetic dataset")
    generate_parser.add_argument("--users", type=int, default=360)
    generate_parser.add_argument("--items-per-category", type=int, default=100)
    generate_parser.add_argument("--seed", type=int, default=42)
    batch_parser = sub.add_parser("batch", help="Evaluate, refit, and atomically publish")
    batch_parser.add_argument("--epochs", type=int, default=45)
    batch_parser.add_argument("--seed", type=int, default=42)
    batch_parser.add_argument("--report-dir", default="docs")
    args = parser.parse_args()
    engine = get_engine(args.database_url)
    if args.command == "generate":
        print(
            json.dumps(
                generate(
                    engine,
                    n_users=args.users,
                    items_per_category=args.items_per_category,
                    seed=args.seed,
                ),
                indent=2,
            )
        )
    else:
        if args.epochs < 1:
            parser.error("--epochs must be positive")
        key = hashlib.sha256(str(engine.url).encode()).hexdigest()[:16]
        with (Path(tempfile.gettempdir()) / f"experience-reco-{key}.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.exit(
                    2, "Another batch owns this database; exiting without modifying outputs.\n"
                )
            report = train_and_publish(
                engine, epochs=args.epochs, seed=args.seed, report_dir=args.report_dir
            )
            print(json.dumps(report["macro"], indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
