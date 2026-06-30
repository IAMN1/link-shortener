from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import BadRequest

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

        Returns ``True`` if the request path does not start with ``/api/``
        or the ``Accept`` header includes ``text/html``.
        """

        if request.path.startswith("/api/"):
            return False
        
        if 'text/html' in request.headers.get('Accept', ''):
            return True
        
        # Default to HTML for frontend routes
        return True

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

            self.logger.warning(
                "Validation error", errors=error.errors(), path=request.path
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
                "CONFIGURATION_ERROR": 500,
                "ROLE_CREATION_FAILED": 400,
                "ROLE_DELETION_FAILED": 400,
                "ROLE_UPDATE_FAILED": 400,
            }

            status_code = status_mapping.get(error.code, 400)

            if self._should_return_html():
                return render_template(
                    "error.html", error=error.message
                ), status_code

            response = ErrorResponse(
                error=error.code,
                message=error.message
            )
            self.logger.error(
                "Domain error", error=error.message, code=error.code
            )

            return jsonify(response.model_dump()), status_code

        @self.app.errorhandler(ValueError)
        def handle_value_error(error: ValueError):
            """
            Handle generic ValueError exceptions
            (e.g., from invalid input).
            """

            response = ErrorResponse(
                error="VALUE_ERROR",
                message=str(error)
            )

            self.logger.warning("Value error", error=str(error))

            return jsonify(response.model_dump()), 400

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
