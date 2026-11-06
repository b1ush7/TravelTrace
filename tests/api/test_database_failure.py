from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app


def test_unavailable_database_returns_safe_503_without_blocking_docs():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def fail_connection(connection, record):
        raise OperationalError("sensitive-connection-details", {}, Exception("sensitive-password"))

    settings = Settings(database_url="sqlite://", jwt_secret="test-secret-" + "x" * 48)
    try:
        with TestClient(create_app(settings, engine)) as client:
            spec = client.get("/openapi.json")
            assert spec.status_code == 200
            assert '503' in spec.json()['paths']['/api/v1/auth/session']['post']['responses']
            result = client.post("/api/v1/auth/session", json={"username": "alice", "password": "password123"})
            assert result.status_code == 503
            assert result.json()["code"] == "DATABASE_UNAVAILABLE"
            assert "sensitive" not in result.text
            assert result.json()["request_id"] == result.headers["x-request-id"]
    finally:
        engine.dispose()
