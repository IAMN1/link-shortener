from flask import Blueprint, current_app, redirect, render_template, request, url_for
from link_shortener.application.services.link_service import LinkService
from link_shortener.domain.exceptions import LinkNotFoundError


class FrontendController:
    """"""
    
    def __init__(self, link_service: LinkService):
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
        """Получение реального IP с учетом прокси"""
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        return request.remote_addr
    
    def index(self):
        """Главная страница с формой для ввода URL"""
        return render_template("index.html")
    
    def shorten(self):
        """Обработка формы: создание короткой ссылки"""

        url = request.form.get("url")
        if not url:
            return render_template("error.html", error="Url не может быть пустым!"), 400
        
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
        """Страница с информацией о ссылке"""
        try:
            info = self.link_service.get_link_info(short_code)
            return render_template('info.html', link=info)
        except LinkNotFoundError:
            return render_template('error.html', error='Ссылка не найдена'), 404
        except Exception as e:
            current_app.logger.error(f"Frontend info error: {e}")
            return render_template('error.html', error='Внутренняя ошибка'), 500
