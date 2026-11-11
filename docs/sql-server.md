# SQLite demonstration → SQL Server production reference

`schema.sql` is an independently designed SQL Server reference for a marketplace
catalog, raw transactions, behaviour, and `reco` output tables. It is not applied
to the local SQLite store and must not be treated as a migration for an existing
production database. SQL Server was not available in the verification environment.

## Storage mapping

| Demonstration table | Proposed production source |
|---|---|
| `Users`, `Categories`, `Vendors`, `Listings` | Corresponding `dbo` catalog tables |
| `Tags`, `ListingTags` | `dbo.Tags`, `dbo.ListingTags` |
| `Interactions` append-only ledger | Extract from `reco.vInteractions` |
| `Searches` | `dbo.Searches`; retained but unused by the current model |
| `UserRecommendations`, `SimilarListings`, `PopularListings`, `ModelRuns` | Matching `reco` output tables |

SQLAlchemy's `schema_translate_map` flattens `dbo`/`reco` into SQLite's main namespace.
For a real SQL Server target, omit that translation and use `mssql+pyodbc` with an
approved read-only source identity and a separate scoped output-writer identity.
Do **not** run the synthetic generator or `metadata.create_all()` on production.

The schemas are intentionally not drop-in identical:

- SQLite's local `PriceBucket` is an explicit synthetic column; derive it from
  category-specific price thresholds or percentiles in a production projection.
- All generated prices are illustrative USD values. A mixed-currency catalog needs
  normalization before price-feature bucketing; never compare raw KWD and AED amounts.
- The reference view has `Signal`, `Weight`, `CreatedAt`; the demo ledger additionally
  stores an ID and optional rating. Training relies on signed review `Weight`, not
  the auxiliary rating column.
- Add `EvaluatedUsers` and `SplitAt` to the proposed `reco.ModelRuns` table in a reviewed
  migration, or change the output adapter to write these to a separate audit table.
- The reference recommendation schema's reason/version columns are bounded. Current
  values fit, but verify limits in any adapter and write through explicit projections.

The reference interaction view is a **current-state convenience**, not a historical
event store. For retrospective evaluation, reconstruct favourite removals and
transaction status changes as of the cutoff; current status must not leak future
cancellations or removals into historical training. The demo append-only ledger
does not have this mutable-state problem.

## Adapter outline (not implemented)

1. Read a consistent catalog/interactions snapshot through a read-only replica or
   export. Select `UserId, ListingId, Signal, Weight, CreatedAt` from the reference
   `reco.vInteractions`; restrict to confirmed/completed bookings and orders.
2. Join category codes and tags, normalize timestamps to UTC, and compute price
   buckets without using future-period behaviour or future price statistics.
3. Materialize the local ledger for offline training, **or** replace `snapshot()`
   with a SQL Server extractor preserving the same Python dictionaries.
4. Replace the output writer with staging tables and a reviewed transactional swap
   of `reco` rankings. For cross-process/cloud schedules, use an external scheduler
   and a database advisory/application lock rather than the host-local file lock.
5. Validate foreign keys, catalog eligibility, indices, row counts, batch retention,
   isolation, error rollback, and permissions before any deployment.

## Connecting with SQLAlchemy and pyodbc

Install the optional `sqlserver` dependency and Microsoft ODBC Driver 18 on the
runtime host. This **illustrative** integrated-authentication URL contains no secret:

```python
from sqlalchemy import URL, create_engine

url = URL.create(
    "mssql+pyodbc",
    host="sqlserver.example.invalid",
    database="ExperienceCatalog",
    query={
        "driver": "ODBC Driver 18 for SQL Server",
        "Trusted_Connection": "yes",
        "Encrypt": "yes",
        "TrustServerCertificate": "no",
    },
)
engine = create_engine(url, pool_pre_ping=True)
```

Choose the organization's supported identity method (integrated identity or a
managed identity where supported). Keep credentials in a secret manager, not in
source control or example connection strings. A connection string alone does not
implement the extraction and output mappings above.

The SQL reference includes a proposal for demographic fields; this prototype neither
populates them nor trains on them. Remove unnecessary personal fields from a real
system and review retention/consent, deletion, and model-rebuild requirements.
