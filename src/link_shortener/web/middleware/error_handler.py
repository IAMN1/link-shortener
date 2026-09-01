from flask import Flask, jsonify, request, make_response
from flask_babel import gettext
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import BadRequest, HTTPException

from link_shortener.web.i18n import translate_error
from link_shortener.web.security.context import create_request_context
from link_shortener.web.responses import error_page, wants_html
from link_shortener.web.schemas.error import ErrorDetail, ErrorResponse
from link_shortener.application import AuditLogger, Logger
from link_shortener.domain.exceptions import (
    DomainError, LinkNotFoundError, PermissionDeniedError
)
from link_shortener.domain.exceptions import (
    ValidationError as DomainValidationError
)


STATUS_BY_CODE = {
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "USER_NOT_FOUND": 404,
    "ROLE_NOT_FOUND": 404,
    # A name in the address that is not one of the three journals. 404
    # rather than 400 for the reason the other two are 404: the caller
    # named a resource, and there is no such resource.
    "JOURNAL_NOT_FOUND": 404,
    "INVALID_CREDENTIALS": 401,
    # Raised deep in the token service when a spent refresh token comes
    # back, and caught by `RefreshSessionUseCase`, which records the act
    # and answers the caller the way any unusable token is answered. Named
    # here anyway: the one thing worse than the wrong status for it would
    # be a 500, which is what an uncaught path would produce, and 401 is
    # what the caught path already returns.
    "REFRESH_TOKEN_REPLAYED": 401,
    # `EMAIL_NOT_VERIFIED` stood here and no longer does. Nothing raises
    # it: signing in with an unconfirmed address answers
    # `INVALID_CREDENTIALS`, the same as a wrong password, so that the
    # pair cannot be used to tell whether a password landed. An entry for
    # a code nothing raises is a line that cannot be measured -- removing
    # it changes no answer, which is the definition of dead -- and the
    # sweep below (`test_every_code_raised_is_named_in_the_table`) puts it
    # back the moment anything raises it again.
    "ACCOUNT_INACTIVE": 403,
    "VALIDATION_ERROR": 400,
    # A role that exists and that no account may wear -- ``guest``. The
    # request is well formed and names something real, so it is not a 404
    # and not a 403: the caller is entitled, and the operation is one the
    # service does not perform.
    "ROLE_NOT_ASSIGNABLE": 400,
    "LINK_NOT_FOUND": 404,
    "LINK_EXPIRED": 410,
    "GUEST_LINK_LIMIT": 429,
    "CODE_GENERATION_FAILED": 500,
    # The same condition as CODE_GENERATION_FAILED, reached from the batch
    # path: every attempt lost a race for a code. The service failed to
    # store a link, so it is not the caller's fault; without this entry
    # the default below would answer 400 on the batch endpoint and 500 on
    # the single one for one and the same failure.
    "LINK_CONFLICT": 500,
    # The caller asked for a code somebody already holds. Their request,
    # their fix -- and 409 says which kind of fix.
    "LINK_CODE_TAKEN": 409,
    "CONFIGURATION_ERROR": 500,
    # A deployment that cannot register anybody: the default role is not
    # in the database. 503 for the reason MAIL_NOT_HANDED_OFF is one --
    # the request was fine and the service's own machinery is not. Its
    # own code rather than CONFIGURATION_ERROR, which it used to share,
    # because the two carry sentences written for different readers: this
    # one is shown to whoever tried to register, and the other names a
    # role from the configuration and belongs in the log.
    "REGISTRATION_UNAVAILABLE": 503,
    # The queue would not take a confirmation message. The request was
    # fine and the account is fine; what failed is the service's own
    # machinery, and 503 is what says so -- answered 500 by the default
    # below, it would have read as a bug in handling the request instead.
    "MAIL_NOT_HANDED_OFF": 503,
    # The caller asked for a name somebody already holds -- the same shape
    # as LINK_CODE_TAKEN, and answered the same way: their request, and a
    # fix only they can make.
    "ROLE_ALREADY_EXISTS": 409,
    # The same answer as the name a role already carries: the
    # request is well formed and the service simply has it. It
    # answered 400 under the generic validation code, so a client
    # could not tell a taken address from a malformed one without
    # reading the sentence.
    "EMAIL_ALREADY_REGISTERED": 409,
    # The role is there and the service owns it. 400 rather than 403: the
    # caller holds `admin:manage_roles` and is refused by what they named,
    # not by who they are.
    "ROLE_IS_SYSTEM": 400,
    "PERMISSIONS_NOT_FOUND": 400,
}
"""What HTTP status each domain error code is answered with.

At module level rather than inside the handler because the handler is no
longer the only reader: ``AuthController`` answers two of these codes with
a status of its own, and it still has to know which sentence the code may
show a client. Two copies of this table would agree until one of them
gained a code.
"""


def status_for(code: str) -> int:
    """
    Say which status a domain error code is answered with.

    Args:
        code: The error's machine-readable code.

    Returns:
        The mapped status, or 500. An unmapped code is a code nobody
        classified, and the safe reading of that is "we do not know what
        went wrong" rather than "the request was bad". Reported as 400, a
        new internal failure looked like ordinary client noise and stayed
        out of error monitoring.
    """
    return STATUS_BY_CODE.get(code, 500)


CODES_WORDED_FOR_THE_CLIENT = frozenset({
    "REGISTRATION_UNAVAILABLE",
    # Raised by one route, and that route is an administrative one:
    # ``POST /admin/users/<id>/resend-verification`` tells three answers
    # apart on purpose, and the sentence it assembles names the address
    # the message was meant for -- which its docstring argues is no
    # disclosure, the caller reading the whole account list already.
    # Measured with the broker stopped: 503 arrived as "An internal error
    # occurred", so the operator who is the whole reason this route
    # answers three ways saw what any other failure looks like, and a
    # sentence translated into both catalogues reached nobody.
    "MAIL_NOT_HANDED_OFF",
})
"""5xx codes whose sentence was written for whoever is reading it.

The rule below is a proxy: a 5xx code usually means the service is
describing its own state, and its sentence names things -- a role from the
configuration, a broker -- that a stranger is not the audience for. This
is the list of codes where the proxy is wrong, so it is the list of
sentences that must stay marked and translated.

It is a list rather than a flag on the error because the audience is a
property of the code, not of the moment: one code, one sentence, one
reader. A code that starts needing an entry here is usually a code that
should have been two codes.
"""


def client_message(error: DomainError) -> str:
    """
    Say what this refusal may tell a client, in the client's language.

    A 5xx message usually describes the service's own state -- a missing
    role, a name from the configuration -- and the client is not the
    audience for it. Which of those is which is decided by the code and
    never by the status the answer happens to carry: ``AuthController``
    answers ``REGISTRATION_UNAVAILABLE`` with 400 because the status is
    that endpoint's to choose, and what the sentence may say is still the
    code's to decide.

    Here rather than inside the handler because the handler is not the
    only place that answers a ``DomainError``. Left there, the rule held
    on every route but the two that build their own response -- and those
    two are on the unauthenticated registration path.

    Args:
        error: The refusal being answered.

    Returns:
        The generic sentence for a code answered 5xx, the translated one
        otherwise.
    """
    if (
        status_for(error.code) >= 500
        and error.code not in CODES_WORDED_FOR_THE_CLIENT
    ):
        return gettext("An internal error occurred")

    return translate_error(error)


class ErrorHandlerMiddleware:
    """
    Registers Flask error handlers for known exceptions.

    For API routes (``/api/…``) a JSON response is returned; for other
    routes an HTML error page is rendered.
    """

    def __init__(self, app: Flask, logger: Logger, audit_logger: AuditLogger):
        """
        Args:
            app: Flask application instance.
            logger: Application logger.
            audit_logger: Where a refusal by privilege is recorded. This
                middleware is the one place every ``DomainError`` passes
                through, which is what makes it the place to write that
                event from: the alternative is each raiser writing its own
                and the next one forgetting.
        """
        self.app = app
        self.logger = logger
        self.audit_logger = audit_logger
        self._register_error_handlers()

    def _record_refusal(self, error: PermissionDeniedError, context) -> None:
        """
        Write down an attempt that was refused for want of a privilege.

        The event the audit trail had no record of at all. Measured on the
        running stack before this: a caller with no ``audit:view`` asking
        for the audit journal and the same caller asking for the role list
        both came back 403, and ``audit.log`` gained nothing either time.

        The request's own context is bound, because "somebody was refused"
        without an account, an address or a path is not a fact anybody can
        act on -- and the line the error handler already wrote carried
        none of the three. It is also where the path and the method come
        from: ``for_logging`` carries both, so the event does not name
        them again.

        Args:
            error: The refusal, carrying what the caller would have needed.
            context: The request context, built once by the handler and
                passed in -- ``create_request_context`` negotiates a
                language on its way, and doing that twice for one answer
                is twice for nothing.
        """
        audit = self.audit_logger.bind(**context.for_logging())
        audit.log_permission_denied(
            required=error.required, exceeded=error.exceeded
        )

    def _should_return_html(self) -> bool:
        """
        Determine whether the client expects an HTML response.

        One rule, in one place: ``wants_html`` in ``web.responses``. The
        throttle answers 429 on the same routes and asks the same
        function, so the two cannot come apart.

        Returns:
            ``True`` when this request should be answered with a page.
        """
        return wants_html()

    def _sentence_for(self, error: HTTPException) -> str:
        """
        Say what a Werkzeug refusal says, in the reader's language.

        ``HTTPException.description`` is written inside Werkzeug and is
        English wherever the visitor is from -- "Did not attempt to load
        JSON data because the request Content-Type was not
        'application/json'." It is also written for a developer rather
        than for whoever is looking at the page.

        So the ones that reach a browser get a sentence of this project's
        own, marked and translated like every other. The rest keep the
        library's, which is the honest answer for a status nobody here
        anticipated: it is at least accurate, and it is in the log either
        way.

        Args:
            error: The refusal Flask or a view raised.

        Returns:
            The sentence to show, translated where there is one to show.
        """
        # By status rather than by exception class: `abort(403)` and a
        # decorator raising `Forbidden` are the same answer to the caller,
        # and Werkzeug's own hierarchy is not the thing being described.
        sentences = {
            400: gettext("The request could not be understood"),
            403: gettext("You do not have access to this"),
            409: gettext("That conflicts with something already stored"),
            413: gettext("What was sent is too large"),
            415: gettext("The service expects a JSON body"),
            503: gettext("The service is unavailable right now"),
        }

        return sentences.get(error.code or 0) or error.description or ""

    def _respond_http_exception(self, error: HTTPException):
        """
        Answer with the status the exception already carries.

        Args:
            error: The refusal Flask or a view raised.

        Returns:
            A Flask response with the exception's own status code.
        """
        code = "_".join(error.name.upper().split())

        # The library's own wording, not the shown one: an operator
        # matching this against a Werkzeug traceback needs the sentence
        # Werkzeug wrote.
        self.logger.info(
            "Request refused",
            status=error.code,
            path=request.path,
            description=error.description,
        )

        message = self._sentence_for(error)

        # `HTTPException.code` is optional -- the base class carries None,
        # and a subclass that forgot to set one would arrive here. 500 is
        # the honest reading of "an exception with no status": something
        # went wrong and nobody classified it.
        status = error.code or 500

        if self._should_return_html():
            return error_page(code, message, status)

        response = ErrorResponse(error=code, message=message)
        return jsonify(response.model_dump()), status

    def _register_error_handlers(self):
        """Wire Flask error handlers to the appropriate methods."""

        @self.app.errorhandler(404)
        def handle_not_found(error):
            """Handle 404 Not Found errors."""

            if self._should_return_html():
                return error_page("NOT_FOUND", gettext("Page not found"), 404)

            response = ErrorResponse(
                error="NOT_FOUND", message=gettext("Resource not found")
            )

            return jsonify(response.model_dump()), 404

        @self.app.errorhandler(405)
        def handle_method_not_allowed(error):
            """Handle 405 Method Not Allowed errors.

            The answer carries ``Allow``. RFC 9110 15.5.6 is not soft
            about it -- "The origin server MUST generate an Allow header
            field in a 405 response containing a list of the target
            resource's currently supported methods" -- and it is the only
            thing that makes the refusal actionable: a client told "not
            allowed" and nothing else has to guess which verb to try.

            Werkzeug puts the list on the exception it raises, and this
            handler replaced its response with a JSON body of its own,
            which left the header behind. Measured before this: every
            route answered 405 with no ``Allow`` at all -- `TRACE
            /api/v1/stats`, `DELETE /api/v1/stats`, `PUT /health`, `POST
            /api/v1/links/mine`. Found by the contract run, which
            generates a request per method and reads the answer against
            the standard.

            Args:
                error: The Werkzeug exception, which knows the methods.

            Returns:
                The refusal, with the header on both the page and the
                JSON form.
            """
            # `valid_methods` is what Werkzeug's MethodNotAllowed carries;
            # anything else reaching this handler leaves the header off
            # rather than inventing a list.
            allowed = sorted(getattr(error, "valid_methods", None) or [])

            if self._should_return_html():
                # `error_page` answers (body, status); the header belongs
                # on a real response, so one is built from it either way
                # rather than in a branch mypy has to reconcile.
                body, status = error_page(
                    "METHOD_NOT_ALLOWED", gettext("Method not allowed"), 405
                )
                page = make_response(body, status)
                if allowed:
                    page.headers["Allow"] = ", ".join(allowed)
                return page

            response = ErrorResponse(
                error="METHOD_NOT_ALLOWED",
                # The method is a value, not a word to translate, and it
                # is named rather than positional so a translation can put
                # it where that language puts it.
                message=gettext(
                    "Method %(method)s not allowed", method=request.method
                )
            )

            answer = make_response(jsonify(response.model_dump()), 405)
            if allowed:
                answer.headers["Allow"] = ", ".join(allowed)
            return answer

        @self.app.errorhandler(PydanticValidationError)
        def handle_pydantic_validation(error: PydanticValidationError):
            """
            Convert Pydantic validation errors into structured ErrorResponse.
            """

            details = []
            for err in error.errors():
                details.append(
                    ErrorDetail(
                        field='.'.join(str(loc) for loc in err['loc']),
                        message=err['msg'],
                        code=err['type']
                    )
                )
            response = ErrorResponse(
                error="VALIDATION_ERROR",
                message=gettext("Request validation failed"),
                # `details` stays English. Those sentences are Pydantic's
                # own -- "Input should be a valid string" -- built inside
                # the library from a rule name, not written here, so there
                # is no msgid to mark and no place to mark it. What names
                # the field is `field`, which is a machine name either way.
                details=details
            )

            # ``include_input=False``: pydantic puts the rejected value
            # itself in every error dict, and the values this application
            # rejects include passwords: on ``CreateUserRequest``
            # with a password shorter than the policy: the plaintext went
            # into application.log as ``'input': 'sh0rt!'`` while the 400
            # body stayed clean. What the operator needs is which field
            # failed and why, and that is what is left.
            self.logger.warning(
                "Validation error",
                errors=error.errors(include_input=False),
                path=request.path,
            )
            return jsonify(response.model_dump()), 400

        @self.app.errorhandler(DomainValidationError)
        def handle_domain_validation(error: DomainValidationError):
            """
            Handle domain-level validation errors.
            These errors originate from value objects or domain entities.
            """

            # Translated once and used twice: the envelope's `message` and
            # the per-field detail are the same sentence, and translating
            # each on its own is how the two start to differ.
            message = translate_error(error)

            response = ErrorResponse(
                error=error.code,
                message=message,
                details=[
                    ErrorDetail(field=error.field, message=message)
                ] if error.field else None
            )

            self.logger.warning(
                "Domain validation error", field=error.field, code=error.code
            )

            # The status comes from the code, as it does for every other
            # domain error, rather than being 400 whatever was raised. A
            # validation error that names no code of its own still gets
            # 400 -- that is what `VALIDATION_ERROR` is, and it is not in
            # the table -- but a subclass that carries one is answered by
            # it: a taken address is `EMAIL_ALREADY_REGISTERED`, and the
            # table answers that 409, the way it answers a taken role name.
            return jsonify(response.model_dump()), STATUS_BY_CODE.get(
                error.code, 400
            )

        @self.app.errorhandler(LinkNotFoundError)
        def handle_link_not_found(error: LinkNotFoundError):
            """Handle case when a requested link is not found."""

            if self._should_return_html():
                # The page says the plain sentence rather than the error's
                # own, which names the code that failed. The visitor typed
                # that code; repeating it back is noise, and the page
                # already shows the path it was asked for.
                return error_page(error.code, gettext("Link not found"), 404)

            response = ErrorResponse(
                error=error.code,
                message=translate_error(error)
            )

            self.logger.info(
                "Link not found", short_code=error.short_code
            )
            return jsonify(response.model_dump()), 404

        @self.app.errorhandler(DomainError)
        def handle_domain_error(error: DomainError):
            """Handle generic domain errors (base class)."""

            status_code = status_for(error.code)

            # Logged before either answer is built, and therefore on both
            # paths. It used to sit below the HTML branch's `return`, so a
            # domain failure on a page route -- the ones a person is
            # actually looking at -- was answered and never recorded.
            # Always in English: the operator reading `application.log` is
            # not the visitor whose cookie chose a language.
            # Bound to the request, which it was not: the line read
            # ``{"error": "Not authorized", "code": "FORBIDDEN"}`` and
            # nothing else -- no account, no address, no path, and no
            # request id to join it to the ``Request completed`` line that
            # has one. Measured on the running stack: two different 403s a
            # second apart were indistinguishable in the journal.
            context = create_request_context()
            log = self.logger.bind(**context.for_logging())
            log.error("Domain error", error=error.message, code=error.code)

            # The audit trail's own record of the refusal, which is a
            # different journal read by different people: `logs:view`
            # opens the line above, `audit:view` opens this one.
            if isinstance(error, PermissionDeniedError):
                self._record_refusal(error, context)

            # Asked of `client_message` rather than decided here, because
            # this is no longer the only place that answers a DomainError:
            # `AuthController` builds two of these responses itself, and
            # the rule has to reach them too. It stays in the log line
            # above either way.
            #
            # Said once for both shapes. Said only in the JSON branch, the
            # page showed the sentence the API refused to show: measured,
            # `GET /dashboard/` with the default role missing put "Default
            # role 'user' is missing from the database" on screen.
            message = client_message(error)

            if self._should_return_html():
                return error_page(error.code, message, status_code)

            response = ErrorResponse(error=error.code, message=message)
            headers = {}

            # A refusal that clears in a day must not be mistaken for one
            # that clears in a minute. The rate limiter sends Retry-After
            # with its own 429; the guest quota answers with the same status
            # and had nothing to say about when to come back.
            retry_after = getattr(error, "retry_after_seconds", None)
            if retry_after:
                headers["Retry-After"] = str(retry_after)

            return jsonify(response.model_dump()), status_code, headers

        # There is deliberately no handler for ValueError. Invalid input is
        # already rejected by the Pydantic request schemas and by the domain
        # ValidationError above, so a ValueError reaching this layer comes
        # from code that did not expect its own state -- a bug. Reporting it
        # as 400 hid those bugs as user mistakes and kept them out of error
        # monitoring; it now falls through to the 500 handler below.

        @self.app.errorhandler(BadRequest)
        def handle_bad_request(error):
            """Handle malformed request body (e.g., invalid JSON)."""

            if self._should_return_html():
                return error_page("BAD_REQUEST", gettext("Bad request"), 400)

            response = ErrorResponse(
                error="BAD_REQUEST",
                message=gettext("Malformed request body")
            )
            return jsonify(response.model_dump()), 400

        @self.app.errorhandler(Exception)
        def handle_generic_error(error: Exception):
            """
            Catch-all handler for any unhandled exception.

            Logs the full exception and returns a generic 500 error.
            For HTML requests, renders an error template.
            """
            if isinstance(error, HTTPException) and error.code is not None:
                # An HTTPException is an answer, not a failure: Flask itself
                # raises it for a body without ``Content-Type: application/json``
                # (415) and for a method the route does not take, and any
                # ``abort(403)`` written from here on would arrive the same
                # way. Catching them alongside real crashes turned every one
                # of them into 500 -- a status that says the service broke
                # about a request it correctly refused, and that tells a
                # client to retry what will never succeed.
                return self._respond_http_exception(error)

            self.logger.exception("Unhandled exception", exc_info=error)

            if self._should_return_html():
                return error_page(
                    "INTERNAL_SERVER_ERROR", gettext("Internal server error"), 500
                )

            response = ErrorResponse(
                error="INTERNAL_SERVER_ERROR",
                message=gettext("An internal error occurred")
            )

            return jsonify(response.model_dump()), 500
