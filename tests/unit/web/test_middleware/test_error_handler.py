import ast
import pathlib

import link_shortener
from link_shortener.domain.exceptions import DomainError, LinkNotFoundError, ValidationError as DomainValidationError
from link_shortener.web.middleware.error_handler import STATUS_BY_CODE


SOURCE = pathlib.Path(link_shortener.__file__).parent
"""The package itself -- swept rather than listed, so a new code counts."""


class TestErrorHandlerMiddleware:
    """Tests for the centralized error handling middleware."""

    def test_404_html(self, client, mock_link_service):
        """Request to non-existent HTML route returns 404 page."""

        # Arrange
        mock_link_service.redirect.side_effect = LinkNotFoundError("nonexistent")

        # Act
        response = client.get("/nonexistent", headers={"Accept": "text/html"})

        # Assert
        assert response.status_code == 404
        assert b"Rendered error.html" in response.data

    def test_404_json(self, client):
        """Request to non-existent API route returns JSON error."""

        # Act
        response = client.get("/api/v1/nonexistent", headers={"Accept": "application/json"})

        # Assert
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "NOT_FOUND"

    def test_405_json(self, client):
        """POST to GET-only API route returns 405 JSON."""

        # Act
        response = client.post("/api/v1/stats")

        # Assert
        assert response.status_code == 405
        data = response.get_json()
        assert data["error"] == "METHOD_NOT_ALLOWED"

    def test_405_html(self, client):
        """POST to GET-only HTML route should return 405 HTML page."""

        # Act
        response = client.post("/", headers={"Accept": "text/html"})

        # Assert
        assert response.status_code == 405
        assert b"Rendered error.html" in response.data

    def test_pydantic_validation_error(self, client):
        """POST /api/v1/shorten with invalid data type returns 400 JSON."""

        # Act
        response = client.post("/api/v1/shorten", json={"url": 123})
        
        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        assert "details" in data

    def test_domain_validation_error(self, client, mock_link_service):
        """Domain ValidationError should return 400 JSON."""

        # Arrange
        mock_link_service.create_short_link.side_effect = DomainValidationError(
            "Invalid URL", field="url"
        )

        # Act
        response = client.post("/api/v1/shorten", json={"url": "bad"})

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        assert data["details"][0]["field"] == "url"

    def test_domain_error(self, client, mock_link_service):
        """
        A domain error nobody classified reports as 500, not 400.

        Every ``DomainError`` raised in this codebase carries an explicit
        code, and each of those is mapped. What is left over is a code no
        one assigned a status to -- and reading that as "the request was
        bad" is a guess in the direction that hides things: ``LINK_CONFLICT``
        sat in that gap, so the batch endpoint reported a lost race for a
        short code, a storage failure, as the caller's fault and kept it out
        of error monitoring. The single-link path answered 500 for the same
        condition.
        """

        # Arrange
        mock_link_service.create_short_link.side_effect = DomainError("Test domain error")

        # Act
        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        # Assert
        assert response.status_code == 500
        data = response.get_json()
        assert data["error"] == "DOMAIN_ERROR"

    def test_a_code_nobody_mapped_reports_as_500(self, client, mock_link_service):
        """
        The gap this closes had a real occupant: ``LINK_CONFLICT``, raised
        by the batch path when every attempt lost a race for a short code.
        A storage failure, reported to the caller as their own bad request
        -- while the single-link path answered 500 for the same condition.
        """
        mock_link_service.create_short_link.side_effect = DomainError(
            "something nobody classified", code="A_CODE_ADDED_LATER"
        )

        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        assert response.status_code == 500

    def test_losing_a_race_for_a_code_is_not_the_callers_fault(
        self, client, mock_link_service
    ):
        mock_link_service.create_short_link.side_effect = DomainError(
            "every attempt lost a race", code="LINK_CONFLICT"
        )

        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        assert response.status_code == 500

    def test_a_server_side_domain_error_does_not_describe_itself(
        self, client, mock_link_service
    ):
        """
        The message of a 5xx describes the service's own state -- a missing
        default role, a role name out of the configuration. It belongs in
        the log, not in the response.
        """

        mock_link_service.create_short_link.side_effect = DomainError(
            "Default role 'user' not found", code="CONFIGURATION_ERROR"
        )

        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        assert response.status_code == 500
        assert "user" not in response.get_json()["message"]
        assert response.get_json()["error"] == "CONFIGURATION_ERROR"

    def test_a_client_side_domain_error_still_explains_itself(
        self, client, mock_link_service
    ):
        """The rule is about 5xx only: a 4xx must stay useful."""

        mock_link_service.create_short_link.side_effect = DomainError(
            "You are not allowed to delete this link", code="FORBIDDEN"
        )

        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        assert response.status_code == 403
        assert "not allowed" in response.get_json()["message"]

    def test_value_error(self, client, mock_link_service):
        """An unexpected ValueError is a bug, so it reports as 500."""

        # Arrange
        mock_link_service.create_short_link.side_effect = ValueError("Some value error")

        # Act
        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        # Assert
        assert response.status_code == 500
        data = response.get_json()
        assert data["error"] == "INTERNAL_SERVER_ERROR"
        # Input validation belongs to the request schemas and the domain, so
        # a ValueError here must not be dressed up as a user mistake.
        assert "Some value error" not in response.get_data(as_text=True)

    def test_link_not_found_error(self, client, mock_link_service):
        """LinkNotFoundError should return 404 JSON."""

        # Arrange
        mock_link_service.get_link_info.side_effect = LinkNotFoundError("abc123")

        # Act
        response = client.get("/api/v1/links/abc123")

        # Assert
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "LINK_NOT_FOUND"

    def test_generic_exception_html(self, client, mock_link_service):
        """Unhandled exception in HTML route returns 500 page."""

        # Arrange
        mock_link_service.create_short_link.side_effect = Exception("Boom")

        # Act
        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        # Assert
        assert response.status_code == 500

    def test_generic_exception_json(self, client, mock_link_service):
        """Unhandled exception in API route returns 500 JSON."""
        mock_link_service.create_short_link.side_effect = Exception("Boom")

        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})
        assert response.status_code == 500
        data = response.get_json()
        assert data["error"] == "INTERNAL_SERVER_ERROR"

    def test_malformed_json_returns_400(self, client):
        """POST with invalid JSON body returns 400, not 500."""
        response = client.post(
            "/api/v1/shorten",
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "BAD_REQUEST"

class TestTheTableNamesEveryCodeTheServiceRaises:
    """A code missing from ``STATUS_BY_CODE`` is a code answered 500.

    The default is deliberate -- an unclassified failure is safer read as
    "we do not know what went wrong" than as "the request was bad" -- but
    it is a default for codes nobody has got to yet, not a place for codes
    this application raises on purpose. ``EMAIL_NOT_VERIFIED`` sat there:
    the sign-in answers it 401 itself, so the omission never showed, and
    it stopped being harmless the moment anything else read the table.
    Nothing but a sweep can notice that, because the code that hides it is
    the code that works.
    """

    @staticmethod
    def _codes_the_source_raises():
        """
        Collect every error code spelled out under ``src``.

        Returns:
            Dict of code to the places that raise it.
        """
        found = {}
        for path in sorted(SOURCE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue

                # ``DomainError(sentence, code="X")`` and every subclass
                # that names the argument.
                for keyword in node.keywords:
                    if keyword.arg == "code" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        found.setdefault(keyword.value.value, []).append(
                            f"{path.name}:{node.lineno}"
                        )

                # ``super().__init__(sentence, "X")`` inside an exception,
                # and ``DomainError(sentence, "X")`` at a call site: the
                # code is the second positional argument in both.
                name = getattr(
                    node.func, "id", getattr(node.func, "attr", "")
                )
                if name in ("DomainError", "__init__") and len(node.args) > 1:
                    second = node.args[1]
                    if isinstance(second, ast.Constant) and isinstance(
                        second.value, str
                    ):
                        found.setdefault(second.value, []).append(
                            f"{path.name}:{node.lineno}"
                        )
        return found

    def test_the_sweep_finds_codes_to_check(self):
        """A sweep over nothing passes and proves nothing."""
        assert len(self._codes_the_source_raises()) >= 10

    def test_every_code_raised_is_named_in_the_table(self):
        raised = self._codes_the_source_raises()

        unmapped = {
            code: places
            for code, places in raised.items()
            if code not in STATUS_BY_CODE and code.isupper()
        }

        assert unmapped == {}, (
            "these codes are raised but not in STATUS_BY_CODE, so they are "
            f"answered 500: {unmapped}"
        )
