"""Controller for public HTML pages."""

from flask import Blueprint, render_template


class FrontendController:

    def __init__(self):
        self.bp = Blueprint(
            'frontend',
            __name__,
            static_folder='../static',
            static_url_path='/static'
        )
        self._register_routes()

    def _register_routes(self):
        self.bp.add_url_rule('/', view_func=self.index, methods=['GET'])
        self.bp.add_url_rule('/register', view_func=self.register_form, methods=['GET'])
        self.bp.add_url_rule('/login', view_func=self.login_page, methods=['GET'])
        self.bp.add_url_rule('/api/docs', view_func=self.api_docs, methods=['GET'])

    def index(self):
        return render_template("public/index.html")

    def register_form(self):
        return render_template('public/register.html')

    def login_page(self):
        return render_template('public/login.html')

    def api_docs(self):
        return render_template('public/index.html')
