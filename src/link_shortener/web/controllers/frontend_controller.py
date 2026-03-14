from flask import Blueprint, g, redirect, render_template, request, url_for
from link_shortener.application import LinkService
from link_shortener.application.context import RequestContext


class FrontendController:
    """
    Controller for frontend (HTML) routes.

    Now only renders pages; all data operations go through the API (JSON).
    """

    def __init__(self, link_service: LinkService):
        """
        Initialize the frontend controller.

        Args:
            link_service: Application service facade.
        """
        self.link_service = link_service
        self.bp = Blueprint(
            'frontend',
            __name__,
            template_folder='../templates',
            static_folder='../static',
            static_url_path='/static'
        )
        self._register_routes()

    def _register_routes(self):
        """Register all frontend routes."""

        self.bp.add_url_rule('/', view_func=self.index, methods=['GET'])
        self.bp.add_url_rule('/info/<short_code>', view_func=self.info_redirect, methods=['GET'])
        self.bp.add_url_rule('/extended/<short_code>', view_func=self.extended_info_redirect, methods=['GET'])
        self.bp.add_url_rule('/stats', view_func=self.stats, methods=['GET'])
        self.bp.add_url_rule('/api/docs', view_func=self.api_docs, methods=['GET'])

    def _get_request_context(self) -> RequestContext:
        """Create a RequestContext object from the current Flask request."""
        return RequestContext(
            request_id=g.get('request_id'),
            remote_addr=request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip(),
            user_agent=request.user_agent.string if request.user_agent else None,
            request_path=request.path,
            request_method=request.method
        )

    def index(self):
        """Render the main page."""
        return render_template("index.html")

    def info_redirect(self, short_code: str):
        """
        Redirect to the main page with info mode for the given short code.
        """
        return redirect(url_for('frontend.index', mode='info', code=short_code))

    def extended_info_redirect(self, short_code: str):
        """
        Redirect to the main page with extended mode for the given short code.
        """
        return redirect(url_for('frontend.index', mode='extended', code=short_code))

    def stats(self):
        """Render the statistics page."""
        context = self._get_request_context()
        stats = self.link_service.get_service_stats(context)
        return render_template('stats.html', stats=stats)

    def api_docs(self):
        """Redirect to API documentation (e.g., Swagger UI)."""
        # TODO Replace with actual documentation URL
        return redirect("https://swagger.io")
