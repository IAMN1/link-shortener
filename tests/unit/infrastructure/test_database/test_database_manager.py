from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.models import LinkModel
import pytest
from sqlalchemy import text


# ------------------------------------------------------------------
# TestDatabaseManager
# ------------------------------------------------------------------
class TestDatabaseManager:
    """Tests for DatabaseManager."""

    def test_connect_and_close(self, test_config):
        """Should connect to database and close connection."""

        # Arrange
        manager = DatabaseManager(test_config.DATABASE_URL, echo=False)
        
        # Act & Assert
        manager.connect()
        assert manager.engine is not None
        manager.close()

    def test_session_without_connect_raises(self):
        """
        Should raise RuntimeError 
        when calling session() before connect().
        """
        
        # Arrange
        manager = DatabaseManager('sqlite:///:memory:')

        # Act & Assert
        with pytest.raises(RuntimeError, match="Database not initialized"):
            with manager.session():
                pass

    def test_create_tables(self):
        """Should create tables in the database."""
        
        # Arrange
        manager = DatabaseManager("sqlite:///:memory", echo=False)
        manager.connect()

        # Act
        manager.create_tables()

        # Assert
        with manager.session() as session:
            result = session.execute(
                text(
                    "SELECT NAME FROM sqlite_master WHERE type='table' AND name='urls'"
                )
            ).fetchone()
            assert result is not None
        
        manager.close()

    def test_session_context_manager(self, test_config):
        """
        Should work as a context manager, 
        committing on success.
        """
        
        # Arrange
        manager = DatabaseManager(test_config.DATABASE_URL, echo=False)
        manager.connect()
        manager.create_tables()

        # Act & Assert
        with manager.session() as session:
            
            result = session.execute(text("SELECT 1")).scalar()
            
            assert result == 1
        
        manager.close()
    
    def test_get_session_without_connect_raises(self):

        # Arrange
        manager = DatabaseManager('sqlite:///:memory:')

        # Act & Assert
        with pytest.raises(RuntimeError, match="Database not initialized"):
            manager.get_session()

    def test_get_session_manual(self, test_config):
        """
        Should provide a session 
        for manual use; caller must close.
        """
        
        # Arrange
        manager = DatabaseManager(test_config.DATABASE_URL, echo=False)
        manager.connect()
        manager.create_tables()
        
        # Act
        session = manager.get_session()
        
        # Assert
        try:
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1
        finally:
            session.close()
        manager.close()

    def test_session_rollback_on_exception(self, db_manager):
        """
        Should rollback transaction 
        when an exception occurs inside session.
        """
        
        with db_manager.session() as session:
            link = LinkModel(id='1', url_hash='a'*64, short_code='abc123', original_url='http://test.com')
            session.add(link)

        # Теперь в новой сессии вызовем исключение после изменения
        with pytest.raises(ValueError, match='test rollback'):
            with db_manager.session() as session:
                link = session.query(LinkModel).first()
                link.clicks = 5
                raise ValueError('test rollback')

        # Проверяем, что изменения не сохранились
        with db_manager.session() as session:
            link = session.query(LinkModel).first()
            assert link.clicks == 0
