import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.models import Base
from app.main import create_app
from app.db.engine import create_database_engine


@pytest.fixture
def client():
    url = os.getenv("TRAVELTRACE_TEST_DATABASE_URL")
    admin_engine = None
    database = None
    if url:
        # Generated database names only; never drop the configured application DB.
        parsed = make_url(url)
        if parsed.get_backend_name() != "mysql":
            pytest.fail("TRAVELTRACE_TEST_DATABASE_URL must point to MySQL")
        database = "tt_test_" + uuid4().hex
        config = Settings(database_url=parsed.set(database=None).render_as_string(hide_password=False), jwt_secret="test-only-secret-" + "x" * 48)
        admin_engine = create_database_engine(config)
        with admin_engine.begin() as connection:
            connection.execute(text(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4"))
        config = Settings(database_url=parsed.set(database=database).render_as_string(hide_password=False), jwt_secret="test-only-secret-" + "x" * 48)
        engine = create_database_engine(config)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    settings = Settings(database_url="sqlite://", jwt_secret="test-only-secret-" + "x" * 48)
    try:
        Base.metadata.create_all(engine)
        with TestClient(create_app(settings, engine)) as test_client:
            yield test_client
    finally:
        if admin_engine:
            engine.dispose()
            assert database.startswith("tt_test_") and len(database) == 40
            with admin_engine.begin() as connection:
                connection.execute(text(f"DROP DATABASE `{database}`"))
            admin_engine.dispose()
        else:
            engine.dispose()
