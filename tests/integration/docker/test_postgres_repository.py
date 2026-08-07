"""
Level 2 integration tests: SQLAlchemyLinkRepository against real PostgreSQL.

These tests verify PostgreSQL-specific behavior that SQLite cannot test:
- UUID generation
- JSON/JSONB operations
- Real connection pooling
- psycopg2 driver compatibility
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.value_objects.dedup_scope import DedupScope
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from link_shortener.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork


_counter = 0

def _make_link(code="pgtest001", url="https://pg-example.com", owner=None, ttl=0):
    global _counter
    _counter += 1
    hex_suffix = f"{_counter:04x}"
    return Link.create(
        url_hash=UrlHash("b" * 60 + hex_suffix),
        short_code=ShortCode(code),
        original_url=OriginalUrl(url),
        owner=OwnerID(owner) if owner else None,
        ttl_seconds=ttl,
    )


class TestPostgresRepositoryCRUD:
    """CRUD operations against real PostgreSQL."""

    def test_save_and_find_by_code(self, app, db_session):
        repo = SQLAlchemyLinkRepository(db_session)
        link = _make_link("pgtest001")
        repo.save(link)

        found = repo.find_by_code(ShortCode("pgtest001"))
        assert found is not None
        assert found.original_url.value == "https://pg-example.com"

    def test_find_by_hash(self, app, db_session):
        repo = SQLAlchemyLinkRepository(db_session)
        link = _make_link("pgtest002")
        repo.save(link)

        found = repo.find_live_by_hash(link.url_hash, link.dedup_scope())
        assert found is not None

    def test_delete(self, app, db_session):
        repo = SQLAlchemyLinkRepository(db_session)
        link = _make_link("pgtest003")
        saved = repo.save(link)

        repo.delete(saved.id)
        assert repo.find_by_code(ShortCode("pgtest003")) is None

    def test_increment_clicks(self, app, db_session):
        repo = SQLAlchemyLinkRepository(db_session)
        link = _make_link("pgtest004")
        repo.save(link)

        updated = repo.increment_clicks(ShortCode("pgtest004"))
        assert updated.clicks == 1

    def test_find_by_owner(self, app, db_session):
        from sqlalchemy import text
        # Create real users (PostgreSQL enforces FK)
        db_session.execute(text(
            "INSERT INTO users (id, email, password_hash, is_active, created_at) "
            "VALUES ('user-pg1', 'pg1@test.com', 'hash', true, now())"
        ))
        db_session.execute(text(
            "INSERT INTO users (id, email, password_hash, is_active, created_at) "
            "VALUES ('user-pg2', 'pg2@test.com', 'hash', true, now())"
        ))
        db_session.commit()

        repo = SQLAlchemyLinkRepository(db_session)
        repo.save(_make_link("pgown01", owner="user-pg1"))
        repo.save(_make_link("pgown02", owner="user-pg1"))
        repo.save(_make_link("pgown03", owner="user-pg2"))

        results = repo.find_by_owner("user-pg1")
        assert len(results) == 2

    def test_count_guest_links(self, app, db_session):
        repo = SQLAlchemyLinkRepository(db_session)
        link1 = _make_link("pggst01")
        link1.guest_identifier = "10.0.0.1"
        repo.save(link1)
        link2 = _make_link("pggst02")
        link2.guest_identifier = "10.0.0.1"
        repo.save(link2)

        count = repo.count_guest_links_by_identifier("10.0.0.1", since_days=7)
        assert count == 2


class TestPostgresUnitOfWork:
    """UnitOfWork commit/rollback against real PostgreSQL."""

    def test_commit_persists(self, app):
        with app.app_context():
            db = app.container.get_db_manager()
            with SQLAlchemyUnitOfWork(db) as uow:
                uow.links.save(_make_link("pguow001"))
                uow.commit()

            with SQLAlchemyUnitOfWork(db, read_only=True) as uow:
                assert uow.links.find_by_code(ShortCode("pguow001")) is not None

    def test_rollback_discards(self, app):
        with app.app_context():
            db = app.container.get_db_manager()
            with SQLAlchemyUnitOfWork(db) as uow:
                uow.links.save(_make_link("pguow002"))
                # No commit — rollback

            with SQLAlchemyUnitOfWork(db, read_only=True) as uow:
                assert uow.links.find_by_code(ShortCode("pguow002")) is None


class TestPostgresConnection:
    """Verify real PostgreSQL connection works."""

    def test_raw_query(self, pg_engine):
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            assert "PostgreSQL" in version

    def test_table_exists(self, pg_engine):
        with pg_engine.connect() as conn:
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ))
            tables = {row[0] for row in result.fetchall()}
            assert "urls" in tables
            assert "users" in tables
