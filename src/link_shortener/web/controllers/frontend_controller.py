"""Controller for public HTML pages."""

from flask import Blueprint, current_app, jsonify, render_template

from link_shortener.web.schemas.openapi import build_openapi


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
        self.bp.add_url_rule(
            '/api/openapi.json', view_func=self.openapi, methods=['GET']
        )

    def index(self):
        return render_template("public/index.html")

    def register_form(self):
        return render_template('public/register.html')

    def login_page(self):
        return render_template('public/login.html')

    def api_docs(self):
        """
        Render the API description as a page.

        This route used to render the landing page: it existed, answered
        200, and told nobody anything. What it shows now is generated from
        the same document ``/api/openapi.json`` serves, so the page and the
        machine-readable version cannot drift apart.
        """
        return render_template(
            'public/api_docs.html',
            doc=build_openapi(current_app.config.get("BASE_URL", "/")),
        )

    def openapi(self):
        """
        Serve the OpenAPI document.

        Every request and response body in it is the Pydantic model the
        endpoint actually validates against, so a field that changes shape
        changes shape here with it.
        """
        return jsonify(
            build_openapi(current_app.config.get("BASE_URL", "/"))
        )
