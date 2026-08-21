"""A 403 leaves a record naming who was refused, what, and where.

Measured on the running stack before this existed. A caller holding the
``user`` role asked for two things a second apart and was refused both:

    GET /api/v1/journals/audit  -> 403
    GET /api/v1/admin/roles     -> 403

``audit.log`` gained nothing either time. ``application.log`` gained one
line for the first -- written by ``ReadJournalUseCase``, carrying the
account, the address, the journal and the permission -- and for the second
only this:

    {"error": "Not authorized", "code": "FORBIDDEN", "event": "Domain error"}

No account, no address, no path, and no ``request_id`` to join it to the
``Request completed`` line that has one. So the service recorded refusals
on the routes that happened to refuse in a use case, and recorded nothing
on the routes that refuse in a decorator -- which is most of them.

Both halves are fixed here and both are checked: the application line is
bound to the request, and the audit journal gains an event of its own,
under ``audit:view`` rather than ``logs:view``.
"""

from unittest.mock import Mock

import pytest
from flask import Flask

from link_shortener.domain.exceptions import (
    DomainError, PermissionDeniedError,
)
from link_shortener.web.i18n import init_babel
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware


@pytest.fixture
def audit():
    """The audit logger, watched for what a refusal writes to it."""
    logger = Mock()
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def application_log():
    """The application logger, watched the same way."""
    logger = Mock()
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def refusing(application_log, audit):
    """An application whose one route refuses by privilege.

    Built here rather than taken from ``conftest``: the shared fixture
    swaps the authorization service for a ``Mock`` that agrees to
    everything, so no route on it can produce the refusal this file is
    about.
    """
    app = Flask(__name__)
    app.config["TESTING"] = True
    # The handler translates its own sentences, and ``gettext`` reads the
    # extension out of ``app.extensions``: an application built by hand
    # has to wire Babel the way the factory does, or what this measures is
    # ``KeyError: 'babel'``.
    app.config["SUPPORTED_LANGUAGES"] = ["en"]
    app.config["DEFAULT_LANGUAGE"] = "en"
    init_babel(app)
    ErrorHandlerMiddleware(app, application_log, audit)

    @app.route("/api/v1/admin/roles", methods=["POST"])
    def create_role():
        raise PermissionDeniedError(
            "Not authorized", required=["admin:manage_roles"]
        )

    @app.route("/api/v1/admin/roles/last", methods=["DELETE"])
    def delete_last():
        # A 403 that is not about a privilege: what is wrong is the state
        # of the service, not who is asking.
        raise DomainError(
            "This would leave the system without an administrator",
            code="FORBIDDEN",
        )

    @app.route("/api/v1/admin/grant", methods=["POST"])
    def grant():
        raise PermissionDeniedError(
            "You cannot grant permissions you do not hold yourself: admin:all",
            exceeded=["admin:all"],
        )

    return app


class TestTheAuditJournalGainsTheRefusal:

    def test_a_refusal_by_privilege_is_written_down(self, refusing, audit):
        refusing.test_client().post("/api/v1/admin/roles")

        audit.log_permission_denied.assert_called_once()

    def test_the_record_says_which_permission_was_missing(
        self, refusing, audit
    ):
        """"Somebody was refused something" is not a fact anybody can act
        on.

        The address and the method are not checked here because they are
        not arguments: they arrive through the bound request context, and
        the test below reads them there. Named twice, they were written
        twice -- measured on the running stack, one record carried both
        ``request_path`` and ``path``.
        """
        refusing.test_client().post("/api/v1/admin/roles")

        _, kwargs = audit.log_permission_denied.call_args
        assert kwargs["required"] == ("admin:manage_roles",)

    def test_an_escalation_attempt_is_recorded_as_one(self, refusing, audit):
        """Handing out what you do not hold is not an ordinary refusal.

        It reads differently in the journal, and it has to: the caller was
        entitled to be there and tried to leave with more than they came
        with.
        """
        refusing.test_client().post("/api/v1/admin/grant")

        _, kwargs = audit.log_permission_denied.call_args
        assert kwargs["exceeded"] == ("admin:all",)
        assert kwargs["required"] == ()

    def test_the_record_carries_the_request_it_was_made_on(
        self, refusing, audit
    ):
        """Bound from the request, the way every use case binds its own."""
        refusing.test_client().post(
            "/api/v1/admin/roles", headers={"User-Agent": "prober/1.0"}
        )

        bound = audit.bind.call_args.kwargs
        assert bound["request_path"] == "/api/v1/admin/roles"
        assert bound["request_method"] == "POST"
        assert bound["user_agent"] == "prober/1.0"

        # And not a second time under a shorter name.
        _, kwargs = audit.log_permission_denied.call_args
        assert "path" not in kwargs
        assert "method" not in kwargs

    def test_a_refusal_about_the_state_is_not_filed_as_an_attempt(
        self, refusing, audit
    ):
        """The distinction the event exists to keep.

        "This would leave the system without an administrator" is a 403
        about the service, not about the caller. Filed as attempted
        escalation it would bury the refusals that are -- which is the
        whole reason ``PermissionDeniedError`` is a class and not a code.
        """
        refusing.test_client().delete("/api/v1/admin/roles/last")

        audit.log_permission_denied.assert_not_called()


class TestTheApplicationLineSaysWhichRequest:

    def test_the_domain_error_line_carries_the_request(
        self, refusing, application_log
    ):
        refusing.test_client().post("/api/v1/admin/roles")

        bound = application_log.bind.call_args.kwargs
        assert bound["request_path"] == "/api/v1/admin/roles"
        assert bound["request_method"] == "POST"

    def test_every_domain_error_gets_it_and_not_only_the_refusals(
        self, refusing, application_log
    ):
        """The binding is on the handler, not on the refusal branch."""
        refusing.test_client().delete("/api/v1/admin/roles/last")

        application_log.bind.assert_called()
        application_log.error.assert_called_once()
