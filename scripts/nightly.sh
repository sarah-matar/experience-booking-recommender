#!/usr/bin/env sh
set -eu
# Run from the repository root. Only reads the synthetic ledger; never regenerates it.
exec .venv/bin/experience-reco batch --report-dir "${RECO_REPORT_DIR:-artifacts/reports}"
