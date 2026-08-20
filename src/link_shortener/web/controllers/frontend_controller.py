"""Controller for public HTML pages."""

from flask import Blueprint, current_app, jsonify, render_template, request

from link_shortener.web.schemas.openapi import build_openapi


class FrontendController:

    def __init__(self):
        # No static folder of its own. Flask registers `static` on every
        # app over `/static/<path:filename>`, and this blueprint asked for
        # the same rule over the same directory: both resolve
        # to web/static. Two rules on one path means the second is never
        # matched: `frontend.static` built URLs that Flask's own endpoint
        # then served, which is a dead route wearing a live one's clothes.
        # Templates address `static` directly instead.
        self.bp = Blueprint('frontend', __name__)
        self._register_routes()

    def _register_routes(self):
        self.bp.add_url_rule('/', view_func=self.index, methods=['GET'])
        self.bp.add_url_rule('/register', view_func=self.register_form, methods=['GET'])
        self.bp.add_url_rule('/login', view_func=self.login_page, methods=['GET'])
        self.bp.add_url_rule('/verify', view_func=self.verify_page, methods=['GET'])
        self.bp.add_url_rule(
            '/forgot-password', view_func=self.forgot_password_page, methods=['GET']
        )
        self.bp.add_url_rule(
            '/reset-password', view_func=self.reset_password_page, methods=['GET']
        )
        self.bp.add_url_rule('/api/docs', view_func=self.api_docs, methods=['GET'])
        self.bp.add_url_rule(
            '/api/openapi.json', view_func=self.openapi, methods=['GET']
        )

    def index(self):
        """
        Serve the landing page.

        The guest allowance travels with it. The quota was invisible until
        it was spent: the form offered itself, and the eleventh link of the
        day came back refused with no earlier word that a limit existed.
        Both numbers are read from the configuration rather than written
        into the markup, so a deployment that changes them changes what the
        page says.
        """
        return render_template(
            "public/index.html",
            guest_link_limit=current_app.config.get("GUEST_LINK_LIMIT"),
            guest_ttl_days=round(
                current_app.config.get("DEFAULT_GUEST_TTL_SECONDS", 0) / 86400
            ),
        )

    def register_form(self):
        return render_template('public/register.html')

    def login_page(self):
        return render_template('public/login.html')

    def verify_page(self):
        """
        Show the page the confirmation link in the mail points at.

        The token is handed to the markup and spent by a click, not by
        this request: a mail scanner that follows the link renders a page
        and leaves the token unspent for the person the message was for.
        """
        return render_template(
            'public/verify.html', token=request.args.get('token')
        )

    def forgot_password_page(self):
        """
        Show the form that asks for a password reset link.

        Nothing is passed to it. The page says the same thing to everyone
        and the answer it shows says the same thing about every address.
        """
        return render_template('public/forgot_password.html')

    def reset_password_page(self):
        """
        Show the page the reset link in the mail points at.

        The token is handed to the markup and spent by the form on it, not
        by this request. That is not merely the polite arrangement it is
        for confirmation -- it is the only possible one, because the new
        password does not exist until somebody types it. A mail scanner
        following the link renders a form and spends nothing.
        """
        return render_template(
            'public/reset_password.html', token=request.args.get('token')
        )

    def api_docs(self):
        """
        Render the API description as a page.

        Generated from the same document ``/api/openapi.json`` serves, so
        the page and the machine-readable version cannot drift apart.
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
