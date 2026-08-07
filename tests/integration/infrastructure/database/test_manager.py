"""Integration tests for DatabaseManager with real in-memory SQLite."""

import pytest
from sqlalchemy import text


class TestDatabaseManager:
    """Test DB manager lifecycle and operations."""

    def test_create_tables(self, app):
        with app.app_context():
            db = app.container.get_db_manager()
            # Tables should already be created by conftest fixture
            with db.session() as session:
                result = session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
                tables = {row[0] for row in result.fetchall()}
                assert "urls" in tables
                assert "users" in tables
                assert "roles" in tables
                assert "permissions" in tables

    def test_session_commit(self, app):
        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                session.execute(text(
                    "INSERT INTO urls (id, url_hash, short_code, original_url, "
                    "created_at, clicks) VALUES ('test-id', 'aa', 'test0001', "
                    "'https://test.com', datetime('now'), 0)"
                ))
                session.commit()

            with db.session() as session:
                result = session.execute(
                    text("SELECT short_code FROM urls WHERE id='test-id'")
                )
                row = result.fetchone()
                assert row is not None
                assert row[0] == "test0001"

    def test_session_rollback(self, app):
        """Verify that session context manager rolls back on exception."""
        with app.app_context():
            db = app.container.get_db_manager()
            try:
                with db.session() as session:
                    session.execute(text(
                        "INSERT INTO urls (id, url_hash, short_code, original_url, "
                        "created_at, clicks) VALUES ('rollback-id', 'bb', 'rollback1', "
                        "'https://test.com', datetime('now'), 0)"
                    ))
                    raise ValueError("force rollback")
            except ValueError:
                pass

            with db.session() as session:
                result = session.execute(
                    text("SELECT COUNT(*) FROM urls WHERE id='rollback-id'")
                )
                # Zero, not "either": `in (0, 1)` stood here and accepted the
                # broken outcome. Measured -- replacing the rollback in
                # DatabaseManager.session() with a commit leaves the whole
                # suite green, so this is the only test that can notice a
                # failed request committing its partial writes.
                count = result.fetchone()[0]
                assert count == 0

    def test_seed_roles(self, app):
        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                result = session.execute(
                    text("SELECT name FROM roles ORDER BY name")
                )
                roles = {row[0] for row in result.fetchall()}
                assert "admin" in roles
                assert "user" in roles
                assert "guest" in roles
                assert "analyst" in roles
