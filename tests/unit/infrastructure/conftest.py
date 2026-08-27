from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.manager import DatabaseManager
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker



@pytest.fixture
def test_config():
    """Return a TestingConfig object for testing."""
    return TestingConfig()

@pytest.fixture
def in_memory_db_engine():
    """Create an in-memory SQLite engine and create tables."""

    engine = create_engine('sqlite:///:memory:', echo=False)
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture
def db_session(in_memory_db_engine):
    """Provide a SQLAlchemy session for testing."""
    
    SessionLocal = sessionmaker(bind=in_memory_db_engine)
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def db_manager(test_config):
    """Provide a DatabaseManager for testing (in-memory)."""
    
    manager = DatabaseManager(test_config.DATABASE_URL, echo=False, database_type="sqlite")
    manager.connect()
    manager.create_tables()
    yield manager
    manager.close()

