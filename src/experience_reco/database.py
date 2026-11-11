"""Portable SQLAlchemy tables; SQLite flattens the dbo/reco namespaces."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData,
    String, Table, create_engine, event,
)
from sqlalchemy.engine import Engine

metadata = MetaData()
users = Table("Users", metadata,
    Column("UserId", Integer, primary_key=True), Column("City", String, nullable=False),
    Column("CreatedAt", DateTime, nullable=False), schema="dbo")
categories = Table("Categories", metadata,
    Column("CategoryId", Integer, primary_key=True),
    Column("Code", String, unique=True, nullable=False), Column("Vertical", String), schema="dbo")
vendors = Table("Vendors", metadata,
    Column("VendorId", Integer, primary_key=True), Column("Name", String),
    Column("City", String), schema="dbo")
listings = Table("Listings", metadata,
    Column("ListingId", Integer, primary_key=True),
    Column("CategoryId", ForeignKey("dbo.Categories.CategoryId"), nullable=False),
    Column("VendorId", ForeignKey("dbo.Vendors.VendorId"), nullable=False),
    Column("Title", String, nullable=False), Column("City", String, nullable=False),
    Column("BasePrice", Float, nullable=False), Column("Currency", String, nullable=False),
    Column("PriceBucket", String, nullable=False), Column("IsActive", Boolean, nullable=False),
    Column("CreatedAt", DateTime, nullable=False), schema="dbo")
tags = Table("Tags", metadata,
    Column("TagId", Integer, primary_key=True), Column("Name", String, unique=True), schema="dbo")
listing_tags = Table("ListingTags", metadata,
    Column("ListingId", ForeignKey("dbo.Listings.ListingId"), primary_key=True),
    Column("TagId", ForeignKey("dbo.Tags.TagId"), primary_key=True), schema="dbo")
interactions = Table("Interactions", metadata,
    Column("InteractionId", Integer, primary_key=True),
    Column("UserId", ForeignKey("dbo.Users.UserId"), nullable=False),
    Column("ListingId", ForeignKey("dbo.Listings.ListingId"), nullable=False),
    Column("Signal", String, nullable=False), Column("Weight", Float, nullable=False),
    Column("Rating", Integer), Column("CreatedAt", DateTime, nullable=False), schema="dbo")
searches = Table("Searches", metadata,
    Column("SearchId", Integer, primary_key=True),
    Column("UserId", ForeignKey("dbo.Users.UserId")),
    Column("CategoryId", ForeignKey("dbo.Categories.CategoryId")), Column("City", String),
    Column("QueryText", String), Column("CreatedAt", DateTime, nullable=False), schema="dbo")
user_recommendations = Table("UserRecommendations", metadata,
    Column("UserId", Integer, primary_key=True), Column("CategoryId", Integer, primary_key=True),
    Column("Rank", Integer, primary_key=True), Column("ListingId", Integer, nullable=False),
    Column("Score", Float, nullable=False), Column("Reason", String),
    Column("ModelVersion", String), Column("GeneratedAt", DateTime), schema="reco")
similar_listings = Table("SimilarListings", metadata,
    Column("ListingId", Integer, primary_key=True), Column("Rank", Integer, primary_key=True),
    Column("SimilarListingId", Integer, nullable=False), Column("Score", Float),
    Column("ModelVersion", String), schema="reco")
popular_listings = Table("PopularListings", metadata,
    Column("CategoryId", Integer, primary_key=True), Column("City", String, primary_key=True),
    Column("Rank", Integer, primary_key=True), Column("ListingId", Integer, nullable=False),
    Column("Score", Float), Column("GeneratedAt", DateTime), schema="reco")
model_runs = Table("ModelRuns", metadata,
    Column("RunId", Integer, primary_key=True, autoincrement=True), Column("ModelVersion", String),
    Column("CategoryId", Integer), Column("Algorithm", String),
    Column("PrecisionAt10", Float), Column("RecallAt10", Float), Column("NdcgAt10", Float),
    Column("EvaluatedUsers", Integer), Column("SplitAt", DateTime),
    Column("TrainedAt", DateTime), schema="reco")


def get_engine(url: str | None = None) -> Engine:
    url = url or os.getenv("RECO_DATABASE_URL", "sqlite:///data/experience.db")
    if url.startswith("sqlite"):
        if url.startswith("sqlite:///") and not url.endswith(":memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False},
                               execution_options={"schema_translate_map": {"dbo": None, "reco": None}})

        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()
        return engine
    return create_engine(url, pool_pre_ping=True)
