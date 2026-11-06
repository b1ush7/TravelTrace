from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.config import Settings


def create_database_engine(settings: Settings, **overrides):
    url = settings.database_url.get_secret_value()
    backend = make_url(url).get_backend_name()
    options = {"pool_pre_ping": True}
    if backend == "mysql":
        options.update(
            isolation_level="READ COMMITTED",
            pool_recycle=1800,
            connect_args={
                "connect_timeout": settings.db_connect_timeout_seconds,
                "read_timeout": 8,
                "write_timeout": 8,
                "init_command": "SET SESSION innodb_lock_wait_timeout=3",
            },
        )
        if "poolclass" not in overrides:
            options["pool_timeout"] = settings.db_pool_timeout_seconds
    elif backend != "sqlite":
        raise ValueError("Use a mysql+pymysql database URL")
    options.update(overrides)
    return create_engine(url, **options)
