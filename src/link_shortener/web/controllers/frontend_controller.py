from flask import Blueprint, render_template
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
        self.bp.add_url_rule('/info/<short_code>', view_func=self.info, methods=['GET'])
        self.bp.add_url_rule('/info/<short_code>/extended', view_func=self.extended_info, methods=['GET'])
        self.bp.add_url_rule('/stats', view_func=self.stats, methods=['GET'])

    def index(self):
        return render_template("index.html")

    def info(self, short_code: str):

        info = self.link_service.get_link_info(short_code)
        return render_template('info.html', link=info)

    def extended_info(self, short_code: str):
        """Render extended information page for a short link."""
        info = self.link_service.get_extended_link_info(short_code)
        return render_template('extended_info.html', link=info)

    def stats(self):

        stats = self.link_service.get_service_stats()
        return render_template('stats.html', stats=stats)
