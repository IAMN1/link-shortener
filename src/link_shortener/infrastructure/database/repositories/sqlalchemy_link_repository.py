"""
SQLAlchemy implementation of the ``LinkRepository`` interface.

This module provides the ``SQLAlchemyLinkRepository`` class, which translates
domain operations into SQLAlchemy queries and commands. It is designed to work
within a unit-of-work session and handles all persistence concerns for the
``Link`` aggregate.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from link_shortener.domain import (Link, LinkRepository, OriginalUrl,
                                   ShortCode, UrlHash, LinkConflictError,
                                   LinkNotFoundError, DedupScope, OwnerID,
                                   ServiceLinkStats, UserLinkStats)
from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.models.link_model import LinkModel


SHORT_CODE_INDEX_NAME = next(
    index.name
    for index in Base.metadata.tables[LinkModel.__tablename__].indexes
    if [column.name for column in index.columns] == ["short_code"]
)
"""Name of the unique index on ``urls.short_code``.

Read off the model rather than written out, for the reason given beside
``EMAIL_INDEX_NAME``: the name is what PostgreSQL reports a violation of,
and the two would otherwise have to be kept in step by hand. The migration
creates it under this name as well.
"""


def _is_code_clash(error: IntegrityError) -> bool:
    """
    Report whether an integrity error is the short code index refusing.

    Asked because ``urls`` is refused by more than one constraint, so
    "something violated a constraint" is not the same question as "that
    code is taken". Measured on the running stack: saving a link whose
    owner had gone answered ``ForeignKeyViolation`` on
    ``fk_urls_owner_id_users``, and reported as a lost race it sent the
    creation round its five retries and out as "every attempt lost a race
    with a concurrent creation" -- a cause that had nothing to do with it.

    The two databases say it differently, and both forms are covered:
    PostgreSQL names the constraint and offers it as
    ``diag.constraint_name``, while SQLite names the column in the message
    and offers no diagnostics -- ``UNIQUE constraint failed:
    urls.short_code``.

    Args:
        error: The integrity error the flush raised.

    Returns:
        ``True`` if the short code index is what refused the write.
    """
    diagnostics = getattr(error.orig, "diag", None)
    constraint = getattr(diagnostics, "constraint_name", None)
    if constraint:
        return constraint == SHORT_CODE_INDEX_NAME
    return "urls.short_code" in str(error.orig)


class SQLAlchemyLinkRepository(LinkRepository):
    """
    Concrete repository for ``Link`` entities backed by SQLAlchemy.

    All methods operate within the session provided at construction time.
    Transaction management is the responsibility of the caller (typically
    a ``UnitOfWork`` instance).
    """

    DELETE_CHUNK_SIZE = 500
    """Rows per delete statement; keeps bind parameters well under every
    driver's ceiling (32 766 on SQLite, 65 535 on PostgreSQL)."""

    @contextmanager
    def _conflicts_reported(self):
        """
        Turn a uniqueness violation into something the domain can act on.

        The unique index on ``short_code`` is the only authority on whether a
        code is free. A lookup beforehand is a hint that goes stale the
        moment another transaction commits, so the write has to be able to
        say "somebody got there first" instead of surfacing a driver error
        as a 500.

        That index and no other: every other way ``urls`` can refuse a
        write is a different fault, and answering all of them with "lost a
        race" hands the caller a retry loop that cannot succeed and a
        reason that is not the reason. Anything else leaves as it came, to
        be answered as the failure it is.

        Raises:
            LinkConflictError: If the short code index refused the write.
        """
        try:
            yield
        except IntegrityError as error:
            if not _is_code_clash(error):
                raise
            # The session is unusable after this; the unit of work rolls it
            # back on the way out and the caller retries in a fresh one.
            raise LinkConflictError() from error

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session bound to the current transaction.
        """
        self.session = session

    # ------------------------------------------------------------------
    # Save operations
    # ------------------------------------------------------------------
    def save(self, link: Link) -> Link:
        """Insert a Link, or overwrite the stored row if one already exists.

        ``merge`` is what makes the second half of that promise true. Adding
        a freshly built model unconditionally -- which is what this did --
        made every save an insert, so saving an entity that had been read
        back from the database raised ``IntegrityError`` on its own primary
        key instead of updating it.

        The update writes *every* column from the entity, this being the
        whole aggregate rather than a patch. An entity read a while ago and
        saved back therefore reverts whatever changed meanwhile -- notably
        the click counter, which ``increment_clicks`` moves in the database
        without telling any entity. Callers that only mean to bump counters
        must use that method, not this one.

        Args:
            link: Domain Link entity to save.

        Returns:
            The same Link instance (the entity is not mutated here; the ORM
            model is merged into the session).

        Raises:
            LinkConflictError: If another link claimed the short code first.
        """
        with self._conflicts_reported():
            self.session.merge(self._to_model(link))
            self.session.flush()
        return link

    def save_many(self, links: List[Link]) -> List[Link]:
        """Bulk insert Link entities.

        Insert path only, unlike ``save``: this serves batch creation, where
        every link is new by construction.

        Args:
            links: List of Link domain entities.

        Returns:
            The same list of Links.

        Raises:
            LinkConflictError: If another link claimed one of the short codes
                first.
        """
        models = [self._to_model(link) for link in links]
        with self._conflicts_reported():
            self.session.add_all(models)
            self.session.flush()
        return links

    # ------------------------------------------------------------------
    # Single‑object lookups
    # ------------------------------------------------------------------
    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Retrieve a Link by its short code.

        Args:
            short_code: ShortCode value object.

        Returns:
            Link entity if found, otherwise ``None``.
        """
        model = (
            self.session.query(LinkModel)
            .filter_by(short_code=short_code.value)
            .first()
        )
        return self._to_domain(model) if model else None

    def find_live_by_hash(
        self, url_hash: UrlHash, scope: DedupScope
    ) -> Optional[Link]:
        """Find the link a URL deduplicates against, within one scope.

        Args:
            url_hash: UrlHash value object.
            scope: The scope to deduplicate within.

        Returns:
            The oldest live link for this hash in this scope, or ``None``.
        """
        model = (
            self._live_in_scope(scope)
            .filter(LinkModel.url_hash == url_hash.value)
            # Deterministic winner: nothing prevents two concurrent
            # creations from landing in the same scope, and every caller
            # must then be handed the same one of them.
            .order_by(LinkModel.created_at.asc(), LinkModel.id.asc())
            .first()
        )
        return self._to_domain(model) if model else None

    def find_by_owner(self, user_id: str, offset: int = 0, limit: int = 50) -> List[Link]:
        """
        Retrieve links owned by a specific user with pagination.

        Args:
            user_id: UUID of the link owner.
            offset: Number of links to skip (default 0).
            limit: Maximum number of links to return (default 50).

        Returns:
            List of ``Link`` entities belonging to the user (may be empty).
        """
        models = (
            self.session.query(LinkModel)
            .filter_by(owner_id=user_id)
            .order_by(LinkModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._to_domain(m) for m in models]

    # ------------------------------------------------------------------
    # Bulk lookups
    # ------------------------------------------------------------------
    def find_by_codes(
        self, short_codes: List[ShortCode]
    ) -> Dict[ShortCode, Optional[Link]]:
        """Bulk lookup by short codes.

        Queries the database once and builds a dictionary mapping every
        requested code to the found Link (or ``None`` if missing).

        Args:
            short_codes: List of ShortCode value objects.

        Returns:
            Dictionary where each input ShortCode is a key; value is the
            corresponding Link or ``None``.
        """
        code_values = [sc.value for sc in short_codes]
        models = (
            self.session.query(LinkModel)
            .filter(LinkModel.short_code.in_(code_values))
            .all()
        )
        result: Dict[ShortCode, Optional[Link]] = {
            ShortCode(m.short_code): self._to_domain(m) for m in models
        }
        # Ensure every requested code is present in the dict (with None if absent)
        for code in short_codes:
            result.setdefault(code, None)
        return result

    def find_live_by_hashes(
        self, url_hashes: List[UrlHash], scope: DedupScope
    ) -> Dict[UrlHash, Optional[Link]]:
        """Bulk form of ``find_live_by_hash``.

        Args:
            url_hashes: List of UrlHash value objects.
            scope: The scope to deduplicate within.

        Returns:
            Dictionary mapping each requested UrlHash to its live link in
            this scope, or ``None``.
        """
        hash_values = [h.value for h in url_hashes]
        models = (
            self._live_in_scope(scope)
            .filter(LinkModel.url_hash.in_(hash_values))
            .order_by(LinkModel.created_at.asc(), LinkModel.id.asc())
            .all()
        )

        result: Dict[UrlHash, Optional[Link]] = {}
        for model in models:
            # Ordered oldest first, so the first row seen for a hash is the
            # one the single-hash lookup would return.
            result.setdefault(UrlHash(model.url_hash), self._to_domain(model))
        for url_hash in url_hashes:
            result.setdefault(url_hash, None)
        return result

    # ------------------------------------------------------------------
    # Statistics & click updates
    # ------------------------------------------------------------------
    def increment_clicks(self, short_code: ShortCode) -> None:
        """Atomically increment the click counter and update ``last_accessed``.

        One statement, and it returns nothing: the ``UPDATE``'s own row
        count answers the ``LinkNotFoundError`` below, and reading the row
        back would cost half again as much on the redirect path, which is
        the one path this service runs hot. A row handed back here would
        also be a snapshot from the moment of the update, and the counter
        is the one thing another request may already have moved.

        Pending session state is flushed first -- ``autoflush`` is off on
        this session factory -- so the ``UPDATE`` sees every row this
        session has created and its count can be trusted.

        The session is left unsynchronised (``synchronize_session=False``),
        so a model still in the identity map answers with the counter it
        had before. Nothing reads the row again inside this session, and
        ``commit()`` expires its objects, so the next read is fresh.

        Args:
            short_code: ShortCode of the link to update.

        Raises:
            LinkNotFoundError: If no link with the given code exists.
        """
        self.session.flush()

        # Atomic UPDATE in the database
        updated = self.session.query(LinkModel).filter_by(
            short_code=short_code.value
        ).update(
            {
                LinkModel.clicks: LinkModel.clicks + 1,
                LinkModel.last_accessed: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )

        if not updated:
            raise LinkNotFoundError(short_code.value)

    def get_stats(self) -> ServiceLinkStats:
        """Compute service-wide statistics.

        Returns:
            The counts and up to ten most-clicked links.
        """
        total_urls = self.session.query(func.count(LinkModel.id)).scalar()
        total_clicks = self.session.query(func.sum(LinkModel.clicks)).scalar() or 0
        popular_links = (
            self.session.query(LinkModel)
            .order_by(LinkModel.clicks.desc())
            .limit(10)
            .all()
        )
        return ServiceLinkStats(
            total_urls=total_urls,
            total_clicks=total_clicks,
            popular_links=[self._to_domain(m) for m in popular_links],
        )

    GUEST_QUOTA_LOCK_NAMESPACE = 1029701804
    """First half of the advisory lock key.

    Advisory lock keys are one flat namespace per database, shared with
    anything else that takes them, so the pair form is used with a constant
    that identifies this application's guest quota. The value is
    ``blake2b(b"link_shortener.guest_link_quota", digest_size=4)`` read as a
    signed 32-bit integer -- derived from a name so it can be re-derived,
    fixed in the source so it can never drift.
    """

    def lock_guest_quota(self, identifier: str) -> None:
        """Serialise link creation for one guest identifier.

        Uses ``pg_advisory_xact_lock``: it needs no row to lock, which is
        the whole difficulty here -- a guest who has created nothing yet has
        nothing to take a row lock on, and that is exactly the caller who
        can spend the allowance twice.

        Held until the transaction ends, released by the database whichever
        way it ends. A holder that hangs does not block others forever
        either: the wait is a statement, so ``statement_timeout`` bounds it.

        On any other engine this does nothing, and the quota is advisory
        there. PostgreSQL is what production runs; SQLite serves local
        development and the test suite, where concurrent guests do not
        arise. The gap is stated rather than hidden.

        Args:
            identifier: Guest identifier the quota is counted under.
        """
        if self.session.get_bind().dialect.name != "postgresql":
            return

        digest = hashlib.blake2b(
            identifier.encode("utf-8"), digest_size=4
        ).digest()
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {
                "namespace": self.GUEST_QUOTA_LOCK_NAMESPACE,
                "key": int.from_bytes(digest, "big", signed=True),
            },
        )

    def count_guest_links_by_identifier(self, identifier: str, since_days: int) -> int:
        """
        Count guest-created links for a given identifier within a time window.

        Args:
            identifier: Guest identifier (e.g. IP address).
            since_days: Number of past days to include in the count.

        Returns:
            Number of guest links created by this identifier since the cutoff.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        count = self.session.query(func.count(LinkModel.id)).filter(
            # Owned links are nobody's guest links. Without this the count
            # was wrong wherever the identifier is NULL -- a caller with no
            # address, such as the CLI -- because every registered user's
            # link also has a NULL guest identifier, and ten of them were
            # enough to report the guest quota as spent.
            LinkModel.owner_id.is_(None),
            LinkModel.guest_identifier == identifier,
            LinkModel.created_at >= cutoff
        ).scalar()
        return count or 0

    def get_user_stats(self, user_id) -> UserLinkStats:
        """
        Retrieve activity statistics for a specific user.

        Args:
            user_id: UUID of the user.

        Returns:
            The account's counts and its ten most recent links.
        """
        total_links = self.session.query(func.count(LinkModel.id)).filter(
            LinkModel.owner_id == user_id
        ).scalar() or 0
        total_clicks = self.session.query(func.sum(LinkModel.clicks)).filter(
            LinkModel.owner_id == user_id
        ).scalar() or 0
        recent = self.session.query(LinkModel).filter(
            LinkModel.owner_id == user_id
        ).order_by(LinkModel.created_at.desc()).limit(10).all()
        return UserLinkStats(
            total_links=total_links,
            total_clicks=total_clicks,
            recent_links=[self._to_domain(m) for m in recent],
        )


    # ------------------------------------------------------------------
    # Deletion & cleanup
    # ------------------------------------------------------------------
    def delete(self, link_id: str) -> bool:
        """Delete a link by its identifier.

        Answers from the number of rows the statement removed, not from a
        read that preceded it. Under READ COMMITTED two concurrent deletions
        both see the row in their own snapshot and both issue a DELETE, but
        only one matches anything; judging by the earlier read, both would
        report success and both would write a "link deleted" audit line.

        Args:
            link_id: Identifier of the link to delete.

        Returns:
            ``True`` if this call removed the row, ``False`` if it was
            already gone -- including when another transaction took it
            between the lookup and the delete.
        """
        removed = self.session.query(LinkModel).filter(
            LinkModel.id == link_id
        ).delete(synchronize_session=False)
        self.session.flush()
        return bool(removed)

    def get_recent(self, limit: int = 10) -> List[Link]:
        """Return the most recently created links.

        Args:
            limit: Maximum number of links to return (default 10).

        Returns:
            List of Link entities ordered by ``created_at`` descending.
        """
        models = (
            self.session.query(LinkModel)
            .order_by(LinkModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_domain(m) for m in models]

    def delete_by_owner(self, user_id: str) -> List[Link]:
        """Delete every link belonging to one account.

        Chunked for the same reason as ``delete_expired``: the delete names
        its rows by primary key, every key is a bind parameter, and one
        statement for an account with tens of thousands of links hits the
        driver's parameter ceiling and deletes nothing at all.

        Args:
            user_id: Identifier of the owning account.

        Returns:
            The deleted Link entities.
        """
        deleted: List[Link] = []

        while True:
            models = self.session.query(LinkModel).filter(
                LinkModel.owner_id == user_id
            ).limit(self.DELETE_CHUNK_SIZE).all()

            if not models:
                return deleted

            chunk = [self._to_domain(model) for model in models]
            self.session.query(LinkModel).filter(
                LinkModel.id.in_([link.id for link in chunk])
            ).delete(synchronize_session=False)
            self.session.flush()

            deleted.extend(chunk)

    def delete_expired(self, now: datetime) -> List[Link]:
        """Delete links whose expiry has passed.

        Worked in chunks, because the delete names its rows by primary key
        and every key is a bind parameter: one statement for the whole
        backlog hits the driver's parameter ceiling -- 32 766 on SQLite,
        65 535 on PostgreSQL -- and raises instead of deleting anything.
        That failure is self-perpetuating: nothing gets removed, the backlog
        only grows, and every later run fails the same way.

        Args:
            now: Timezone-aware UTC instant to judge expiry against.

        Returns:
            The deleted Link entities.

        Note:
            ``now`` is the caller's clock, not the database's. A host whose
            clock runs ahead deletes links that have not expired yet.
        """
        deleted: List[Link] = []

        while True:
            models = self.session.query(LinkModel).filter(
                LinkModel.expires_at.is_not(None),
                LinkModel.expires_at <= now,
            ).limit(self.DELETE_CHUNK_SIZE).all()

            if not models:
                return deleted

            chunk = [self._to_domain(model) for model in models]
            # Deleted by primary key rather than by re-stating the expiry
            # condition: every selected row must go, or the next query
            # selects it again and the loop never ends. The cost is a
            # window -- a row whose expiry is extended between the select
            # and the delete is removed anyway -- and nothing writes
            # ``expires_at`` after creation today.
            self.session.query(LinkModel).filter(
                LinkModel.id.in_([link.id for link in chunk])
            ).delete(synchronize_session=False)
            self.session.flush()

            deleted.extend(chunk)

    # ------------------------------------------------------------------
    # Scope helpers
    # ------------------------------------------------------------------
    def _live_in_scope(self, scope: DedupScope) -> Any:
        """
        Build a query restricted to unexpired links inside one scope.

        Args:
            scope: The scope to restrict to.

        Returns:
            A SQLAlchemy query over ``LinkModel``.
        """
        now = datetime.now(timezone.utc)
        query = self.session.query(LinkModel).filter(
            or_(LinkModel.expires_at.is_(None), LinkModel.expires_at > now)
        )

        if scope.owner_id is not None:
            return query.filter(LinkModel.owner_id == scope.owner_id)

        # An owner-less scope has to say so explicitly. Filtering on the
        # guest identifier alone would let an owned link answer for a guest
        # who happened to share the address it was created from.
        query = query.filter(LinkModel.owner_id.is_(None))
        if scope.guest_identifier is not None:
            return query.filter(
                LinkModel.guest_identifier == scope.guest_identifier
            )
        return query.filter(LinkModel.guest_identifier.is_(None))

    # ------------------------------------------------------------------
    # Domain <-> ORM conversion helpers
    # ------------------------------------------------------------------
    def _to_domain(self, model: LinkModel) -> Link:
        """
        Convert an ORM model to a domain Link entity.

        Ensures that ``created_at`` and ``last_accessed`` are timezone-aware
        (UTC). If they are naive, they are assumed to be UTC and converted.

        Args:
            model: The SQLAlchemy ``LinkModel`` instance.

        Returns:
            The corresponding domain ``Link`` entity.
        """
        created_at = model.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        last_accessed = model.last_accessed
        if last_accessed is not None and last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)

        expires_at = model.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return Link(
            id=model.id,
            url_hash=UrlHash(model.url_hash),
            short_code=ShortCode(model.short_code),
            # Rebuilt as stored, not re-admitted: see OriginalUrl.from_storage.
            original_url=OriginalUrl.from_storage(model.original_url),
            created_at=created_at,
            clicks=model.clicks,
            last_accessed=last_accessed,
            owner=OwnerID(model.owner_id) if model.owner_id else None,
            expires_at=expires_at,
            guest_identifier=model.guest_identifier,
        )

    @staticmethod
    def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
        """
        Convert an aware timestamp to UTC before it is stored.

        SQLite has no timestamp type: the driver writes the wall clock and
        drops the offset, so ``12:00+05:00`` comes back as ``12:00`` and is
        then read as UTC -- five hours out. PostgreSQL converts properly, so
        without this the two backends disagree about the same entity.
        Nothing writes non-UTC times today; this is what keeps it that way.

        Args:
            value: Timestamp to normalise, or ``None``.

        Returns:
            The same instant expressed in UTC, or ``None``.
        """
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc)

    def _to_model(self, link: Link) -> LinkModel:
        """
        Convert a domain Link entity to an ORM model.

        The returned model is transient; it is not yet added to the session.

        Args:
            link: Domain Link entity.

        Returns:
            A new ``LinkModel`` instance.
        """
        return LinkModel(
            id=link.id,
            url_hash=link.url_hash.value,
            short_code=link.short_code.value,
            original_url=link.original_url.value,
            created_at=self._as_utc(link.created_at),
            clicks=link.clicks,
            last_accessed=self._as_utc(link.last_accessed),
            owner_id=link.owner.value if link.owner else None,
            expires_at=self._as_utc(link.expires_at),
            guest_identifier=link.guest_identifier,
        )
