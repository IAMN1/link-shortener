"""
Serving the journals the application writes.

A blueprint of its own, at ``/api/v1/journals``, rather than a pair of
endpoints under ``/api/v1/admin``. Reading a journal is not an
administrative act: ``audit:view`` and ``logs:view`` sit outside the
``admin`` resource, the ``auditor`` role holds them and nothing else, and
``admin:all`` deliberately does not carry the first of them. An address
under ``/admin`` would say the opposite of all three, and an address is
the first thing anybody reads.

There is no ``@require_permission`` on the route, and that is the one
decision here worth stating. Which permission applies depends on which
journal was asked for -- ``audit:view`` for one, ``logs:view`` for the
other two -- and a decorator is fixed at import time. The check therefore
lives in ``ReadJournalUseCase``, over ``PERMISSION_FOR``, which is the
single place the mapping exists. A decorator naming one of the two here
would be a second, coarser answer to the same question, and the coarser
of two answers is the one that eventually decides.
"""

from flask import Blueprint, jsonify, request

from link_shortener.application import ReadJournalUseCase
from link_shortener.application.use_cases.security.get_security_counts import (
    DEFAULT_PERIOD, GetSecurityCountsUseCase,
)
from link_shortener.application.ports.journal_reader import Journal
from link_shortener.domain import DomainError
from link_shortener.domain.i18n import N_
from link_shortener.web.schemas.journal import JournalPageResponse, JournalQuery
from link_shortener.web.schemas.security import SecurityCountsResponse
from link_shortener.web.security.context import create_request_context


class JournalApiController:
    """
    RESTful controller for reading the journals.

    Read-only by construction: the port behind it has no method that
    writes, so there is no verb here to register but ``GET``.

    Attributes:
        read_journal: The use case, which decides who may read what.
    """

    def __init__(
        self,
        read_journal_use_case: ReadJournalUseCase,
        security_counts_use_case: GetSecurityCountsUseCase,
    ):
        self.read_journal = read_journal_use_case
        self.security_counts = security_counts_use_case
        self.bp = Blueprint("journal_api", __name__, url_prefix="/api/v1/journals")
        self._register_routes()

    def _register_routes(self):
        # The counters first, and the order is not decoration: `/<journal>`
        # would otherwise match the word `counters` and answer 404 for a
        # journal nobody asked for. Werkzeug prefers the static rule
        # whatever the registration order, but a reader of this file
        # should not have to know that to be sure.
        self.bp.add_url_rule(
            "/counters", view_func=self.read_counters, methods=["GET"]
        )
        self.bp.add_url_rule(
            "/<journal>", view_func=self.read_journal_page, methods=["GET"]
        )

    def read_counters(self):
        """
        Handle ``GET /api/v1/journals/counters`` -- the figures of a span.

        Under this blueprint rather than beside the visit statistics,
        because these figures are the audit journal counted: they are read
        under ``audit:view``, the permission that opens that journal, and
        `stats:view_basic` does not open it. An address under `/stats`
        would say the opposite, and an address is the first thing anybody
        reads.

        Returns:
            A ``SecurityCountsResponse`` body.

        Raises:
            DomainError: ``VALIDATION_ERROR`` for a span that is not on
                offer, ``UNAUTHENTICATED`` or ``FORBIDDEN`` from the use
                case.
        """
        counts = self.security_counts.execute(
            create_request_context(),
            period=request.args.get("period", DEFAULT_PERIOD),
        )
        # `mode="json"`, as the visit endpoints do it: without it the two
        # datetimes leave the model as `datetime` objects, and Flask's
        # encoder writes those as RFC 1123 -- "Tue, 18 Aug 2026 10:46:53
        # GMT" where this endpoint's own OpenAPI schema says
        # `format: date-time`, and where the visit chart beside it on the
        # same page is given ISO 8601. One page, two spellings of a moment.
        return jsonify(
            SecurityCountsResponse.from_domain(counts).model_dump(mode="json")
        )

    def read_journal_page(self, journal: str):
        """
        Handle ``GET /api/v1/journals/<journal>`` -- the end of one journal.

        Args:
            journal: Which journal, by name: ``application``, ``error`` or
                ``audit``.

        Returns:
            A ``JournalPageResponse`` body.

        Raises:
            DomainError: ``JOURNAL_NOT_FOUND`` for a name that is not one
                of the three, ``UNAUTHENTICATED`` or ``FORBIDDEN`` from the
                use case.
        """
        # ``model_validate`` rather than ``JournalQuery(**args)``: every
        # query value arrives as a string, and the keyword form declares
        # the fields' own types at the call site -- which a checker is
        # right to refuse. Validation coerces either way; only this
        # spelling says so.
        query = JournalQuery.model_validate(request.args.to_dict())
        page = self.read_journal.execute(
            self._journal_named(journal),
            create_request_context(),
            limit=query.limit,
            include_archives=query.archives,
            following=query.follow,
            where=query.to_filter(),
        )
        return jsonify(
            JournalPageResponse.from_domain(journal, page).model_dump()
        )

    @staticmethod
    def _journal_named(name: str) -> Journal:
        """
        Turn the name in the address into the journal it stands for.

        This conversion is the reason a caller cannot ask for a path. The
        enum has three members and nothing else constructs one, so
        ``../../etc/passwd`` fails here rather than reaching a file system
        -- and it fails before the permission check, which is the right
        order: what is refused is the *name*, and answering "you may not
        read that" about a journal that does not exist would say there is
        one.

        Args:
            name: The name as it arrived in the address.

        Returns:
            The journal.

        Raises:
            DomainError: ``JOURNAL_NOT_FOUND`` if no journal is called that.
        """
        try:
            return Journal(name)
        except ValueError:
            raise DomainError(
                f"No journal is called {name}",
                code="JOURNAL_NOT_FOUND",
                template=N_("No journal is called %(name)s"),
                params={"name": name},
            )
