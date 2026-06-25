import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup environment variables for testing before importing anything
os.environ["SECRET_KEY"] = "test_secret_key"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_API_KEY"] = "test_admin_key"
os.environ["DISABLE_PANDERA_IMPORT_WARNING"] = "True"

from app import app as flask_app, limiter
from database.models import Base

from database.connection import engine as db_engine_global

@pytest.fixture(scope="session")
def db_engine():
    # Use the global application database engine
    return db_engine_global

@pytest.fixture
def db_session(db_engine):
    # Setup connection session
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def clean_db(db_engine):
    # Ensure database is dropped and recreated for a clean test run
    Base.metadata.drop_all(bind=db_engine)
    Base.metadata.create_all(bind=db_engine)
    yield

@pytest.fixture
def test_app(db_engine):
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test_secret_key"
    flask_app.config["ADMIN_API_KEY"] = "test_admin_key"
    flask_app.config["WTF_CSRF_ENABLED"] = True
    flask_app.config["RATELIMIT_ENABLED"] = False
    
    # Programmatically disable rate limits for test suite
    limiter.enabled = False
    
    Session = sessionmaker(bind=db_engine)
    
    class MockSessionScope:
        def __init__(self):
            self.session = Session()
        def __enter__(self):
            return self.session
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type:
                self.session.rollback()
            self.session.close()

    # Override get_db in the module namespace
    import app as app_module
    app_module.get_db = lambda: MockSessionScope()
    
    # Also override in database connection module
    import database.connection as conn_module
    conn_module.get_db = lambda: MockSessionScope()
    
    return flask_app

@pytest.fixture
def test_client(test_app):
    with test_app.test_client() as client:
        yield client
