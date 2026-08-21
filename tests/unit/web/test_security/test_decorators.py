"""What the authorization decorators do when they refuse.

``require_any_permission`` guards one page -- the journal viewer -- and
nothing in the suite measured it: 77% of the module, with the whole body
of the decorator unmeasured, and the only mention of it under ``tests/``
was in the live run, which exercises the branch that passes. The two that
refuse decide whether a caller is told "log in" or "logging in will not
help", and one of them cannot be reached through the page at all: it sits
behind ``@login_required``, so the anonymous branch is only reachable from
a route that does not carry that decorator, and one may be written.

Built on a Flask application of its own rather than the shared ``app``
fixture: that fixture's conftest replaces the authorization service with a
bare ``Mock()``, which answers truthfully to anything, so the decorator
would never actually decide.
"""

import pytest
from flask import Flask, g

from link_shortener.domain import DomainError
from link_shortener.web.security.decorators import (
    require_any_permission, require_permission
)


class Answers:
    """An authorization service that holds exactly these permissions."""

    def __init__(self, *held):
        self.held = set(held)

    def is_allowed(self, user, permission):
        """Report whether the caller holds one of the listed permissions."""
        return user is not None and permission in self.held


class Anybody:
    """A stand-in for the domain user; the decorators only test for None."""


@pytest.fixture()
def guarded():
    """An application with one route behind each decorator.

    Returns:
        The application, whose two routes are ``/any`` and ``/one``.
    """
    application = Flask(__name__)

    @application.route("/any")
    @require_any_permission("audit:view", "logs:view")
    def any_route():
        return "the page"

    @application.route("/one")
    @require_permission("audit:view")
    def one_route():
        return "the page"

    return application


def _call(application, path, *, service, user):
    """Run one request with the given service and caller in ``g``."""
    with application.test_request_context(path):
        if service is not None:
            g.authorization_service = service
        if user is not None:
            g._domain_user = user
        return application.view_functions[
            "any_route" if path == "/any" else "one_route"
        ]()


class TestRequireAnyPermission:
    """Holding either permission opens the page; holding neither does not."""

    @pytest.mark.parametrize("held", ["audit:view", "logs:view"])
    def test_either_permission_opens_it(self, guarded, held):
        answer = _call(
            guarded, "/any", service=Answers(held), user=Anybody()
        )

        assert answer == "the page"

    def test_holding_neither_is_forbidden(self, guarded):
        with pytest.raises(DomainError) as refusal:
            _call(
                guarded, "/any",
                service=Answers("admin:view_users"), user=Anybody(),
            )

        assert refusal.value.code == "FORBIDDEN"

    def test_holding_nothing_at_all_is_forbidden(self, guarded):
        with pytest.raises(DomainError) as refusal:
            _call(guarded, "/any", service=Answers(), user=Anybody())

        assert refusal.value.code == "FORBIDDEN"

    def test_an_anonymous_caller_is_told_to_log_in(self, guarded):
        """Not 403: a client can tell "log in" from "that will not help"."""
        with pytest.raises(DomainError) as refusal:
            _call(guarded, "/any", service=Answers("audit:view"), user=None)

        assert refusal.value.code == "UNAUTHENTICATED"

    def test_without_a_service_it_refuses_to_guess(self, guarded):
        """No middleware ran, so nothing established who is calling."""
        with pytest.raises(RuntimeError):
            _call(guarded, "/any", service=None, user=Anybody())


class TestRequirePermission:
    """The single-permission decorator, in the branch nothing measured."""

    def test_without_a_service_it_refuses_to_guess(self, guarded):
        with pytest.raises(RuntimeError):
            _call(guarded, "/one", service=None, user=Anybody())
