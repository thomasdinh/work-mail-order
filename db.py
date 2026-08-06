"""
Database connection setup.

Multi-user note: since this tool is meant for a support team, not a
single local user, it's built against PostgreSQL by default so
everyone connects to the same shared database. Point DATABASE_URL at
your Postgres instance:

    export DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/orders"

For local development/testing without a Postgres server, you can fall
back to a SQLite file (NOT suitable for real multi-user use, only for
trying things out):

    export DATABASE_URL="sqlite:///./orders_dev.db"
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./orders_dev.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create all tables. Safe to call repeatedly (no-op if they exist)."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """FastAPI dependency: yields a session and closes it after the request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
