"""Database wiring: SQLAlchemy 2.0 engine, session factory, Base, and helpers.

Provides:
    engine                 — the process-wide SQLAlchemy Engine.
    SessionLocal           — a sessionmaker bound to the engine.
    Base                   — the declarative base all models inherit from.
    get_session()          — FastAPI dependency yielding a Session.
    pg_advisory_xact_lock  — per-merchant chain serialization (Postgres).

The advisory lock is the Postgres analogue of Delta's MariaDB ``GET_LOCK``.
It is taken inside the current transaction and auto-released at COMMIT/ROLLBACK
(``pg_advisory_xact_lock``), keyed by a stable string (typically the merchant
TIN, e.g. ``'receipt_register:'||tin``). See MOR_EIMS_CONTRACT.md §6.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

# pool_pre_ping avoids handing out dead connections after a DB restart/idle.
engine = create_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a Session, always closing it afterward."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def pg_advisory_xact_lock(session: Session, key: str) -> None:
    """Acquire a transaction-scoped Postgres advisory lock for ``key``.

    Blocks until the lock is granted; released automatically when the current
    transaction ends. ``hashtext`` maps the string key to the int4 the advisory
    lock functions expect, matching the spec form
    ``pg_advisory_xact_lock(hashtext('receipt_register:'||tin))``.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": key},
    )
