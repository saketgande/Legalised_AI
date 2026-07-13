"""Database engine + session plumbing.

Sync SQLAlchemy 2.0. A single engine, a session factory, and a FastAPI
dependency that yields a request-scoped session. The skeleton creates tables
via ``Base.metadata.create_all`` on startup; a real deploy swaps that for
Alembic migrations (noted in the README).
"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
