# Verification record

## Executed locally

- Python 3.11.18 with **LightFM 1.17**, NumPy 1.26.4, SciPy 1.13.1.
- FastAPI 0.162.4 and Matplotlib 3.11.2. Exact environment: `requirements.lock`.
- Default generator: **360 users, 800 listings, 85,445 interactions, 2,784 searches**.
- Two complete default 45-epoch evaluation/refit runs produced identical ranking
  metrics. The second run appended audit history rather than duplicating ranking keys.
- **30 pytest tests passed**. This includes negative-review handling, full-catalog
  metrics, time-cutoff isolation, cold users/items, category isolation, city routing,
  inactive/seen exclusions, session changes, and rollback after a simulated failure
  in the middle of publishing output tables.
- Ruff check and Ruff format check passed for source, tests, and the metrics renderer.
- A separate clean source copy was bootstrapped using `scripts/bootstrap.sh`; its
  independent pytest run also reported **30 passed**.
- A real Uvicorn HTTP server returned 200 for readiness, personalized recommendation,
  guest/city fallback, session-boosted recommendation, similarity, popularity, and
  OpenAPI requests. See `http-smoke.json` and `example-response.json`.
- SQLAlchemy/SQLite output row counts after two successful runs:

| Table | Rows |
|---|---:|
| UserRecommendations | 139,200 |
| SimilarListings | 24,000 |
| PopularListings | 1,600 |
| ModelRuns | 32 |

`ModelRuns` has 2 algorithms × 8 categories × 2 successful runs. Ranking tables
contain only the latest published snapshot. This is a small demo, not a load test.

## Compatibility note

The test suite emits one upstream Starlette deprecation warning about the legacy
`httpx` transport. It does not affect test results; adopting the newer transport is
a future dependency-maintenance task. Warnings are not suppressed.

LightFM initially failed under uv's PEP 517 path; pinned Python/build dependencies
and pip's legacy build resolved it. There was **no model replacement**.

## Not executed / not claimed

- Docker image build and Compose startup: no Docker executable or daemon was present.
  Container CI configuration is included but no remote workflow was launched.
- C# example compilation: no .NET SDK was present. The example targets .NET 8+ / C# 12.
- SQL Server reference DDL and pyodbc adapter: no SQL Server/ODBC environment was used;
  the extraction/production writer adapter is explicitly a documented next step.
- Makefile aliases: `make` was absent; equivalent documented commands were executed.
- No public repository, image registry, live hosting, or recurring scheduler was created.
- No real customers, vendors, private datasets, or third-party business assets were used.

The local Git repository has logical commits and no remote. Its author email uses
the reserved placeholder `portfolio@example.invalid`, not an invented personal
address. Configure an appropriate verified author email for future public commits.
The source ZIP excludes Git internals, virtual environments, and the generated DB;
recreate the synthetic database with the documented generator.

## Supporting references

- LightFM model/feature semantics: https://making.lyst.com/lightfm/docs/lightfm.html
- LightFM dataset construction: https://making.lyst.com/lightfm/docs/lightfm.data.html
- FastAPI container guidance: https://fastapi.tiangolo.com/deployment/docker/
- Docker CI build guidance: https://docs.docker.com/build/ci/github-actions/
