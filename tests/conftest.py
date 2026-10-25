from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.db as database
from app.db import Base, get_session
from app.main import create_app
from app.seed import DEMO_PASSWORD, seed_demo


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Generator[Session, None, None]:
    engine = database.configure_database(f"sqlite:///{(tmp_path / 'api-test.db').as_posix()}")
    Base.metadata.create_all(engine)
    assert database.SessionLocal is not None
    with database.SessionLocal() as db:
        seed_demo(db)
        yield db


@pytest.fixture()
def client(seeded_db: Session) -> Generator[TestClient, None, None]:
    app = create_app(auto_seed=False)

    def override_session():
        assert database.SessionLocal is not None
        with database.SessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def login() -> Callable[[TestClient, str], dict]:
    def do_login(client: TestClient, username: str = "admin") -> dict:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": DEMO_PASSWORD})
        assert response.status_code == 200, response.text
        return response.json()["user"]

    return do_login
