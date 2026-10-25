from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import PROJECT_ROOT, get_settings


class Base(DeclarativeBase):
    pass


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def configure_database(database_url: str | None = None) -> Engine:
    global engine, SessionLocal
    url = database_url or get_settings().database_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            path = Path(db_path)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            path.parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine


def get_engine() -> Engine:
    return engine or configure_database()


def get_session() -> Generator[Session, None, None]:
    if SessionLocal is None:
        configure_database()
    assert SessionLocal is not None
    with SessionLocal() as session:
        yield session


def create_schema() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(get_engine())

