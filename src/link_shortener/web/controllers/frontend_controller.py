from flask import Blueprint, g, redirect, render_template, request
from link_shortener.application import LinkService, RequestContext


class FrontendController:
    """
    Controller for frontend (HTML) routes.

    Handles rendering of the main page, statistics page, and API documentation
    redirect. All data operations are performed via the JSON API, so this
    controller only serves pages and does not directly call use cases except
    for the statistics page (which retrieves data via the service).

    Available routes:
        - GET /               -> Main page with mode selector and forms.
        - GET /stats          -> Service statistics page.
        - GET /api/docs       -> Redirect to API documentation (placeholder).
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
        self.bp.add_url_rule('/stats', view_func=self.stats, methods=['GET'])
        self.bp.add_url_rule('/api/docs', view_func=self.api_docs, methods=['GET'])

    def _get_request_context(self) -> RequestContext:
        """Create a RequestContext object from the current Flask request."""
        return RequestContext(
            request_id=g.get('request_id'),
            remote_addr=request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip(),
            user_agent=request.headers.get('User-Agent'),
            request_path=request.path,
            request_method=request.method
        )

    def index(self):
        """
        Render the main page.

        The page includes a mode selector (single URL, batch, info, extended)
        and forms that submit to the corresponding API endpoints.
        """
        return render_template("index.html")

    def stats(self):
        """
        Render the service statistics page.

        Retrieves statistics via the link service and passes them to the template.
        """
        context = self._get_request_context()
        stats = self.link_service.get_service_stats(context)
        return render_template('stats.html', stats=stats)

    def api_docs(self):
        """Redirect to API documentation (placeholder)."""
        # TODO Replace with actual documentation URL
        return redirect("https://swagger.io")
