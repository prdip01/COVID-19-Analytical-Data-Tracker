"""
Database connection configuration for the COVID-19 Data Tracker.

Dynamically configures connection pooling based on whether the dialect is
SQLite or PostgreSQL, provides session management, and exposes initialization helpers.
"""

import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from config import DATABASE_URL
from database.models import Base

logger = logging.getLogger(__name__)

# Determine dialect and set connection pool parameters accordingly
is_sqlite = DATABASE_URL.startswith("sqlite:")

engine_args = {}
if is_sqlite:
    # SQLite-specific settings for multithreaded Flask usage
    engine_args = {
        "connect_args": {"check_same_thread": False}
    }
else:
    # PostgreSQL-specific settings with robust connection pooling
    engine_args = {
        "pool_size": 10,          # Standard pool size
        "max_overflow": 20,       # Allow burst connections
        "pool_recycle": 1800,     # Recycle connection every 30 minutes
        "pool_pre_ping": True     # Health check before using a connection
    }

try:
    engine = create_engine(DATABASE_URL, **engine_args)
    # Define session factory
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.exception("Failed to initialize database engine for URL: %s", DATABASE_URL)
    raise RuntimeError(f"Database initialization failed: {e}") from e


def init_db() -> None:
    """
    Initializes the database schema.
    Creates all tables defined in models.py if they do not exist.
    """
    try:
        logger.info("Initializing database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")
    except SQLAlchemyError as e:
        logger.error("Failed to create database tables: %s", e)
        raise RuntimeError(f"Database creation failed: {e}") from e


@contextmanager
def get_db() -> Generator[scoped_session, None, None]:
    """
    Context manager to provide a transactional database session scope.
    Ensures the session is cleanly closed on exit.
    
    Yields:
        SQLAlchemy Session object.
    """
    session = SessionLocal()
    try:
        yield session
        # If no exceptions occur within block, keep transaction intact
    except Exception as e:
        logger.error("Database transaction error encountered. Rolling back. Detail: %s", e)
        session.rollback()
        raise
    finally:
        session.close()
