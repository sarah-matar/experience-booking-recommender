from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from experience_reco.api import create_app
from experience_reco.database import get_engine
from experience_reco.synthetic import generate
from experience_reco.training import train_and_publish


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    directory = tmp_path_factory.mktemp("marketplace")
    engine = get_engine(f"sqlite:///{directory / 'test.db'}")
    generated = generate(engine, seed=17, n_users=32, items_per_category=40)
    report = train_and_publish(engine, epochs=3, seed=17, report_dir=directory / "reports")
    yield engine, generated, report
    engine.dispose()


@pytest.fixture
def client(trained):
    with TestClient(create_app(trained[0])) as client:
        yield client
