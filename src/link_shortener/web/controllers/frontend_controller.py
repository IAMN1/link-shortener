from flask import Blueprint, redirect, render_template, url_for
from link_shortener.application import LinkService


class FrontendController:
    """
    Controller for frontend (HTML) routes. Now only renders pages,
    all data operations go through the API (JSON).
    """

    def __init__(self, link_service: LinkService):
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
        self.bp.add_url_rule('/', view_func=self.index, methods=['GET'])
        self.bp.add_url_rule('/info/<short_code>', view_func=self.info_redirect, methods=['GET'])
        self.bp.add_url_rule('/extended/<short_code>', view_func=self.extended_info_redirect, methods=['GET'])
        self.bp.add_url_rule('/stats', view_func=self.stats, methods=['GET'])
        self.bp.add_url_rule('/api/docs', view_func=self.api_docs, methods=['GET'])

    def index(self):
        return render_template("index.html")

    def info_redirect(self, short_code: str):
        return redirect(url_for('frontend.index', mode='info', code=short_code))

    def extended_info_redirect(self, short_code: str):
        return redirect(url_for('frontend.index', mode='extended', code=short_code))

    def stats(self):
        stats = self.link_service.get_service_stats()
        return render_template('stats.html', stats=stats)

    def api_docs(self):
        # Замените на реальную документацию (например, Swagger UI)
        return redirect("https://swagger.io")
