from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import BadRequest, HTTPException

from link_shortener.web.responses import wants_html
from link_shortener.web.schemas.error import ErrorDetail, ErrorResponse
from link_shortener.application import Logger
from link_shortener.domain.exceptions import (
    DomainError, LinkNotFoundError
)
from link_shortener.domain.exceptions import (
    ValidationError as DomainValidationError
)


class ErrorHandlerMiddleware:
    """
    Registers Flask error handlers for known exceptions.

    For API routes (``/api/…``) a JSON response is returned; for other
    routes an HTML error page is rendered.
    """

    def __init__(self, app: Flask, logger: Logger):
        """
        Args:
            app: Flask application instance.
            logger: Application logger.
        """
        self.app = app
        self.logger = logger
        self._register_error_handlers()

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

    def _respond_http_exception(self, error: HTTPException):
        """
        Answer with the status the exception already carries.

        Args:
            error: The refusal Flask or a view raised.

        Returns:
            A Flask response with the exception's own status code.
        """
        code = "_".join(error.name.upper().split())

        self.logger.info(
            "Request refused", status=error.code, path=request.path
        )

        if self._should_return_html():
            return render_template(
                "error.html", error=error.description
            ), error.code

        response = ErrorResponse(error=code, message=error.description)
        return jsonify(response.model_dump()), error.code

    def _register_error_handlers(self):
        """Wire Flask error handlers to the appropriate methods."""

        @self.app.errorhandler(404)
        def handle_not_found(error):
            """Handle 404 Not Found errors."""

            if self._should_return_html():
                return render_template(
                    "error.html", error="Page not found"
                ), 404

            response = ErrorResponse(
                error="NOT_FOUND", message="Resource not found"
            )

            return jsonify(response.model_dump()), 404

        @self.app.errorhandler(405)
        def handle_method_not_allowed(error):
            """Handle 405 Method Not Allowed errors."""

            if self._should_return_html():
                return render_template(
                    "error.html", error="Method not allowed"
                ), 405

            response = ErrorResponse(
                error="METHOD_NOT_ALLOWED", 
                message=f"Method {request.method} not allowed"
            )

            return jsonify(response.model_dump()), 405

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
                message="Request validation failed",
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

            response = ErrorResponse(
                error=error.code,
                message=error.message,
                details=[
                    ErrorDetail(field=error.field, message=error.message)
                ] if error.field else None
            )

            self.logger.warning(
                "Domain validation error", field=error.field, code=error.code
            )

            return jsonify(response.model_dump()), 400

        @self.app.errorhandler(LinkNotFoundError)
        def handle_link_not_found(error: LinkNotFoundError):
            """Handle case when a requested link is not found."""

            if self._should_return_html():
                return render_template(
                    "error.html", error="Link not found"
                ), 404

            response = ErrorResponse(
                error=error.code,
                message=error.message
            )
            
            self.logger.info(
                "Link not found", short_code=error.short_code
            )
            return jsonify(response.model_dump()), 404

        @self.app.errorhandler(DomainError)
        def handle_domain_error(error: DomainError):
            """Handle generic domain errors (base class)."""

            status_mapping = {
                "UNAUTHENTICATED": 401,
                "FORBIDDEN": 403,
                "USER_NOT_FOUND": 404,
                "ROLE_NOT_FOUND": 404,
                "INVALID_CREDENTIALS": 401,
                "ACCOUNT_INACTIVE": 403,
                "VALIDATION_ERROR": 400,
                "LINK_NOT_FOUND": 404,
                "LINK_EXPIRED": 410,
                "GUEST_LINK_LIMIT": 429,
                "CODE_GENERATION_FAILED": 500,
                # The same condition as CODE_GENERATION_FAILED, reached from
                # the batch path: every attempt lost a race for a code. The
                # service failed to store a link, so it is not the caller's
                # fault; without this entry the default below would answer
                # 400 on the batch endpoint and 500 on the single one for one
                # and the same failure.
                "LINK_CONFLICT": 500,
                # The caller asked for a code somebody already holds. Their
                # request, their fix -- and 409 says which kind of fix.
                "LINK_CODE_TAKEN": 409,
                "CONFIGURATION_ERROR": 500,
                "ROLE_CREATION_FAILED": 400,
                "ROLE_DELETION_FAILED": 400,
                "ROLE_UPDATE_FAILED": 400,
            }

            # An unmapped code is a code nobody classified, and the safe
            # reading of that is "we do not know what went wrong" rather
            # than "the request was bad". Reported as 400, a new internal
            # failure looked like ordinary client noise and stayed out of
            # error monitoring.
            status_code = status_mapping.get(error.code, 500)

            if self._should_return_html():
                return render_template(
                    "error.html", error=error.message
                ), status_code

            self.logger.error(
                "Domain error", error=error.message, code=error.code
            )

            # A 5xx message describes the service's own state -- a missing
            # default role, a name from the configuration -- and the client
            # is not the audience for it. It stays in the log line above.
            message = (
                "An internal error occurred"
                if status_code >= 500
                else error.message
            )
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
                return render_template("error.html", error="Bad request"), 400

            response = ErrorResponse(
                error="BAD_REQUEST",
                message="Malformed request body"
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
                return render_template(
                    'error.html', error='Internal server error'
                ), 500

            response = ErrorResponse(
                error="INTERNAL_SERVER_ERROR",
                message="An internal error occurred"
            )

            return jsonify(response.model_dump()), 500
