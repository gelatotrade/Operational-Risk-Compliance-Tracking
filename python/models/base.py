"""
SQLAlchemy Base Configuration und Datenbankverbindung
"""

import sys
from pathlib import Path

# Projektverzeichnis zum Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager

from config.settings import settings

# SQLAlchemy Engine erstellen
engine = create_engine(
    settings.database.connection_string,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    echo=settings.debug
)

# Session Factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Deklarative Basis
Base = declarative_base()


def get_db():
    """Generator für Datenbank-Sessions (für FastAPI Dependency Injection)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context Manager für Datenbank-Sessions"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Initialisiert die Datenbank (erstellt alle Tabellen)"""
    Base.metadata.create_all(bind=engine)


def drop_db():
    """Löscht alle Tabellen (nur für Entwicklung!)"""
    if settings.environment != "development":
        raise RuntimeError("drop_db() ist nur in der Entwicklungsumgebung erlaubt!")
    Base.metadata.drop_all(bind=engine)


# Event Listener für Verbindungstest
@event.listens_for(engine, "connect")
def set_search_path(dbapi_connection, connection_record):
    """Setzt den Schema-Suchpfad bei jeder Verbindung"""
    cursor = dbapi_connection.cursor()
    cursor.execute(f"SET search_path TO {settings.database.schema}")
    cursor.close()


class TimestampMixin:
    """Mixin für automatische Zeitstempel"""
    from sqlalchemy import Column, DateTime
    from sqlalchemy.sql import func

    created_at = Column(DateTime, default=func.current_timestamp())
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp())
