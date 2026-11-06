from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    monkeypatch.setenv("TRAVELTRACE_DATABASE_URL", url)
    monkeypatch.setenv("TRAVELTRACE_JWT_SECRET", "migration-test-secret-" + "x" * 40)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        tables = inspect(engine).get_table_names()
        assert {"users", "rooms", "room_members", "invitations", "messages"} <= set(tables)
        assert {"room_id", "user_id"} == set(inspect(engine).get_unique_constraints("room_members")[0]["column_names"])
        command.check(config)
    finally:
        engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()


def test_mysql_migration_sql(monkeypatch):
    import io
    monkeypatch.setenv("TRAVELTRACE_DATABASE_URL", "mysql+pymysql://unused:unused@localhost/unused")
    monkeypatch.setenv("TRAVELTRACE_JWT_SECRET", "migration-test-secret-" + "x" * 40)
    output = io.StringIO()
    command.upgrade(Config("alembic.ini", output_buffer=output), "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE users" in sql and "AUTO_INCREMENT" in sql
    assert "DATETIME(6)" in sql
