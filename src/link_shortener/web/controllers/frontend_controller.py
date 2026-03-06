from flask import Blueprint, current_app, render_template
from link_shortener.application import LinkService
from link_shortener.domain.exceptions import LinkNotFoundError


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
            static_folder='../static',          # папка со статикой
            static_url_path='/static'           # URL для статики
        )
        self._register_routes()

    def _register_routes(self):
        self.bp.add_url_rule('/', view_func=self.index, methods=['GET'])
        self.bp.add_url_rule('/info/<short_code>', view_func=self.info, methods=['GET'])
        self.bp.add_url_rule('/stats', view_func=self.stats, methods=['GET'])

    def index(self):
        return render_template("index.html")

    def info(self, short_code: str):
        try:
            info = self.link_service.get_link_info(short_code)
            return render_template('info.html', link=info)
        except LinkNotFoundError:
            current_app.logger.info(f"Link not found (frontend): {short_code}")
            return render_template('error.html', error='Link not found'), 404
        except Exception as e:
            current_app.logger.error(f"Frontend info error: {e}", exc_info=True)
            return render_template('error.html', error='Internal error'), 500

    def stats(self):
        try:
            stats = self.link_service.get_service_stats()
            return render_template('stats.html', stats=stats)
        except Exception as e:
            current_app.logger.error(f"Frontend stats error: {e}", exc_info=True)
            return render_template('error.html', error='Internal error'), 500