from flask import Blueprint, current_app, redirect, render_template, request, url_for
from link_shortener.application import LinkService
from link_shortener.domain.exceptions import LinkNotFoundError


class FrontendController:
    """Controller for frontend (HTML) routes.

    Handles rendering of templates and form submissions."""
    
    def __init__(self, link_service: LinkService):
        """
        Initialize the controller with the link service.

        Args:
            link_service: Application service facade.
        """

        self.link_service = link_service

        self.bp = Blueprint(
            'Frontend',
            __name__,
            template_folder="../templates",
            static_folder="../static",
            static_url_path="/static"
        )
        self._register_routes()
    
    def _register_routes(self):
        """Register all frontend routes."""

        self.bp.add_url_rule(
            '/', view_func=self.index, methods=['GET']
        )
        self.bp.add_url_rule(
            '/shorten', view_func=self.shorten, methods=['POST']
        )
        self.bp.add_url_rule(
            '/info/<short_code>', view_func=self.info, methods=['GET']
        )

    def _get_client_ip(self):
        """
        Extract real client IP from request headers, accounting for proxies.

        Returns:
            Client IP address as string.
        """

        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        return request.remote_addr
    
    def index(self):
        """Render the main page with URL input form."""
        return render_template("index.html")
    
    def shorten(self):
        """
        Handle form submission: create a short link 
            and redirect to info page.
        """

        url = request.form.get("url")
        if not url:
            return render_template("error.html", error="URL cannot be empty"), 400
        
        try:
            # Получение IP и User-Agent для аудита
            user_ip = self._get_client_ip()
            user_agent = request.user_agent.string if request.user_agent else None

            result = self.link_service.create_short_link(
                url, user_ip=user_ip, user_agent=user_agent
            )

            # перенаправление на страницу с результатом
            return redirect(url_for("frontend.info", short_code=result.short_code))
        except Exception as e:
            
            current_app.logger.error(f"Frontend shorten error: {e}")
            
            return render_template("error.html", error=str(e)), 500
    
    def info(self, short_code: str):
        """Render information page for a short link."""
        try:
            info = self.link_service.get_link_info(short_code)
            return render_template('info.html', link=info)
        except LinkNotFoundError:
            return render_template('error.html', error='Link not found'), 404
        except Exception as e:
            current_app.logger.error(f"Frontend info error: {e}")
            return render_template('error.html', error='Internal error'), 500
