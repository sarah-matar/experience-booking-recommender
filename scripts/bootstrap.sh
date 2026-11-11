#!/usr/bin/env sh
set -eu
# Python 3.11 and a C compiler are required. uv can provision Python portably.
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-bootstrap.txt 'pip==24.0'
# LightFM 1.17 has a legacy setup.py incompatible with uv's isolated PEP 517 path.
.venv/bin/python -m pip install --no-build-isolation --no-use-pep517 'lightfm==1.17'
uv pip install --python .venv/bin/python --no-build-isolation -r requirements.lock -e '.[dev]'
