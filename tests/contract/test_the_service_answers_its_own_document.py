"""
The service is held against the document it publishes, by the document.

Every other test in this repository asks a question somebody thought to
ask. This one asks the questions nobody thought of: Schemathesis reads
``/api/openapi.json``, generates requests from the schemas in it -- values
at the edges of every declared type, absent optional fields, wrong types
where the document permits them -- and checks each answer against what the
same document promises.

It is here because of what this session found. Two defects were the
document and the service disagreeing (``EMAIL_NOT_VERIFIED`` promised long
after it stopped being answered; ``security`` declared on two operations
out of thirty-nine), and both were found by a person reading. A document
that is only ever read by people falls behind the code between readings.

**What it does not replace.** Generated requests know the shape of an
answer, not its meaning: that the counters belong to whoever made the link,
that a sweep writes to the journal, that a refusal says the same thing for
a wrong password and an unconfirmed address -- those are properties, and
they are held by the tests that name them. This holds the contract: status
codes the document declares, media types, response bodies against their
schemas, and no 500 anywhere.
"""

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.generation import GenerationMode
from sqlalchemy import text

from link_shortener.application.context import RequestContext
from tests.contract.conftest import build_application


APP = build_application()
"""One application for the whole file: the schema is loaded from it."""

ADMIN = "contract-admin@example.com"
PASSWORD = "ContractPass1!"


def _an_administrator() -> str:
    """
    An account holding every permission, and its access token.

    The generated requests reach admin operations, and a run that met
    ``401`` everywhere would check the refusal rather than the contract.
    Made through the same services the CLI uses.
    """
    with APP.app_context():
        container = APP.container
        with container.get_uow_factory()() as uow:
            container.get_user_management_service().create_user(
                uow,
                email=ADMIN,
                password=PASSWORD,
                roles=[uow.roles.get_by_name("admin")],
            )
            uow.commit()

        with container.get_db_manager().session() as session:
            session.execute(
                text("UPDATE users SET email_verified = 1 WHERE email = :e"),
                {"e": ADMIN},
            )
            session.commit()

        signed_in = container.get_login_use_case().execute(
            ADMIN, PASSWORD, RequestContext(request_id="contract-setup")
        )
    return signed_in.access_token


TOKEN = _an_administrator()

schema = schemathesis.openapi.from_wsgi("/api/openapi.json", APP)

# The document declares `bearerAuth`, so Schemathesis would generate an
# `Authorization` header of its own -- a random string -- and the requests
# would measure the refusal instead of the contract. Turned off here; a
# real token is passed on every call below.
schema.config.generation.with_security_parameters = False

# Three operations end the very session the run is authenticated with, and
# after any of them every later request is answered 401 -- a run measuring
# its own sign-out rather than the contract. Measured: with them in, eight
# operations reported "undocumented status 401", all of them answers to a
# token this run had already invalidated.
#
# They are not untested. Signing out is held by
# `test_the_journal_records_what_changed_who_may_act.py` and
# `test_a_presented_credential_is_not_ignored.py`; changing a password by
# `tests/integration/web/controllers/test_password_reset.py`; and the
# document's account of all three is held by the status sweep in
# `test_the_document_declares_what_the_routes_answer.py`.
schema = schema.exclude(path="/api/v1/auth/logout")
schema = schema.exclude(path="/api/v1/auth/change-password")
schema = schema.exclude(path="/api/v1/auth/refresh")

# Positive data only, and the reason is worth stating rather than hiding.
#
# Negative generation asks a second question: "does the service refuse
# everything the document says it should?" Asking it fairly needs a
# document that states every rule -- and some of this service's rules
# cannot be stated in a schema at all. Measured, one at a time:
#
#   * `POST /api/v1/admin/roles` with `permissions: [""]` is refused
#     `400 PERMISSIONS_NOT_FOUND` -- not because the string is empty
#     (`description: ""` is accepted, 201) but because no permission by
#     that name exists. "A name that is in the table" is not a JSON
#     Schema constraint, and writing today's names into an `enum` would
#     be a document that forbids a permission an operator adds tomorrow.
#   * `DELETE /api/v1/admin/roles/admin` is refused `400 ROLE_IS_SYSTEM`.
#     Which roles are the service's own is likewise not a shape.
#   * A password is refused when it appears on a common-password list,
#     which is a list of thousands and not a pattern.
#
# What *was* expressible has been written down: `email` now carries the
# pattern `Email` matches with and `format: email`, and a password its
# length bounds, both imported from the policies that enforce them rather
# than copied. That removed four of the disagreements outright -- sign-in,
# registration, the reset request and the resend were all sending
# `"invalid-url"` and meeting a `400` the document had not predicted.
#
# So this run holds the half that is true of every operation: what comes
# back is what the document declares. The other half is held by the tests
# that name each rule, which is where a rule with no shape belongs.
schema.config.generation.modes = [GenerationMode.POSITIVE]


@schema.parametrize()
@settings(
    # Small and fixed. This runs inside the ordinary suite, which CI runs
    # twice, and a contract check that takes minutes is one that gets
    # switched off. Derandomised so a failure is reproducible from the
    # name alone rather than from a seed printed in a log nobody kept.
    max_examples=8,
    deadline=None,
    derandomize=True,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
    ],
)
def test_every_operation_answers_what_the_document_declares(case):
    """
    One test per operation, generated from the document.

    Args:
        case: The request Schemathesis built for this operation.
    """
    case.call_and_validate(
        # Named rather than left to the default set, so that what this run
        # holds is readable here: no 500 anywhere, the status is one the
        # document declares, the media type is one it declares, the body
        # matches the schema declared for that status, and a method the
        # document does not describe is refused as RFC 9110 asks.
        checks=(
            schemathesis.checks.not_a_server_error,
            *(check for check in schemathesis.checks.CHECKS.get_all()
              if check.__name__ in {
                  "status_code_conformance",
                  "content_type_conformance",
                  "response_schema_conformance",
                  "unsupported_method",
              }),
        ),
        headers={
            # The credential every generated request carries. Passed here
            # rather than registered as an auth provider: the provider is
            # not applied to the requests the "unsupported method" check
            # makes on its own, and those must go out **without** a token
            # anyway -- a service that answers 401 to an unauthenticated
            # TRACE is answering about the credential, which is what it
            # was asked about.
            "Authorization": f"Bearer {TOKEN}",
            # Uncompressed, because the WSGI client hands the body over
            # exactly as the application wrote it: with compression
            # negotiated, the checks read gzip bytes as UTF-8 and report a
            # deserialization failure that says nothing about the service.
            # The compression layer has tests of its own.
            "Accept-Encoding": "identity",
        },
    )
