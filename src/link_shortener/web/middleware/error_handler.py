from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError as PydanticValidationError

from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain.exceptions import (
    DomainError, LinkNotFoundError
)
from link_shortener.domain.exceptions import (
    ValidationError as DomainValidationError
)
from link_shortener.web.schemas.responses import ErrorDetail, ErrorResponse


class ErrorHandlerMiddleware:
    """
    Middleware for centralized error handling in the Flask application.

    It registers error handlers for various exception types and returns
    appropriate JSON responses for API routes or HTML error pages for frontend routes.
    """

    def __init__(self, app: Flask, logger: Logger):
        """
        Initialize the middleware and register error handlers.

        Args:
            app (Flask): Flask application instance.
            logger (Logger): Logger instance for logging errors.
        """
        self.app = app
        self.logger = logger
        self._register_error_handlers()

    def _should_return_html(self) -> bool:
        """
        Determine whether the client expects an HTML response.

        Returns True if the request path does not start with '/api/'
        or the Accept header contains 'text/html'. This allows the same
        error handler to serve both API and frontend requests appropriately.
        """

        if request.path.startswith("/api/"):
            return False
        
        accept = request.headers.get("Accept", "")
        
        if "text/html" in accept:
            return True
        
        # Default to HTML for frontend routes
        return True

    def _register_error_handlers(self):
        """Register all error handlers with the Flask app."""

        @self.app.errorhandler(404)
        def handle_not_found(error):
            """Handle 404 Not Found errors."""

            if self._should_return_html():
                return render_template(
                    "error.html", error="Page not found"
                ), 404

            response = ErrorResponse(
                error="NOT_FOUND", message="Resourse not found"
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
            Handle Pydantic validation errors (raised by request schema validation).
            Converts Pydantic's error list into a structured ErrorResponse.
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
                "Domain validation error", message=error.message, field=error.field
            )

            return jsonify(response.model_dump()), 400

        @self.app.errorhandler(LinkNotFoundError)
        def handle_link_not_found(error: LinkNotFoundError):
            """Handle case when a requested link is not found."""

            response = ErrorResponse(
                error=error.code,
                message=error.message
            )
            
            self.logger.info(
                "Link not found", short_code=getattr(error, 'short_code', None)
            )
            return jsonify(response.model_dump()), 404

        @self.app.errorhandler(DomainError)
        def handle_domain_error(error: DomainError):
            """Handle generic domain errors (base class)."""

            response = ErrorResponse(
                error=error.code,
                message=error.message
            )
            self.logger.error(
                "Domain error", error=error.message, code=error.code
            )

            return jsonify(response.model_dump()), 400

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

            self.logger.warning("Value error", message=str(error))

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
