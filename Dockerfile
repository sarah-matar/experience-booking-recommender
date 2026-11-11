FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-bootstrap.txt ./
RUN python -m pip install --no-cache-dir -r requirements-bootstrap.txt pip==24.0
RUN python -m pip wheel --no-cache-dir --no-use-pep517 --no-build-isolation \
    --wheel-dir /wheels lightfm==1.17
COPY requirements.lock ./
RUN python -m pip wheel --no-cache-dir --no-build-isolation --find-links=/wheels --only-binary=lightfm --wheel-dir /wheels -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels experience-reco \
    && rm -rf /wheels
RUN mkdir -p data artifacts && chown -R app:app /app
USER app
ENV RECO_DATABASE_URL=sqlite:////app/data/experience.db \
    MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "experience_reco.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
