from flask import Blueprint, jsonify, request
from link_shortener.domain import LinkNotFoundError
from pydantic import ValidationError as PydanticValidationError
from link_shortener.application import LinkService
from link_shortener.web.schemas.requests import BatchCreateLinkRequest, CreateShortLinkRequest
from link_shortener.web.schemas.responses import BatchCreateResponse, ServiceStatsResponse, ShortLinkResponse


class ApiController:
    """
    Controller for REST API endpoints (JSON).

    Handles requests under /api/v1/ and returns JSON responses.
    """
    
    def __init__(self, link_service: LinkService):
        """
        Initialize the controller with the link service.

        Args:
            link_service: Application service facade.
        """
        self.link_service = link_service
        self.bp = Blueprint("api", __name__, url_prefix="/api/v1")
        self._register_routes()
    
    def _register_routes(self):
        """Register all API routes."""

        self.bp.add_url_rule(
            '/shorten', view_func=self.create_short_link, methods=['POST']
        )
        self.bp.add_url_rule(
            '/links/<short_code>', view_func=self.get_link_info, methods=['GET']
        )
        self.bp.add_url_rule(
            '/batch/shorten', view_func=self.batch_create, methods=['POST']
        )
        self.bp.add_url_rule(
            '/stats', view_func=self.get_stats, methods=['GET']
        )
    
    def _get_client_ip(self):
        """
        Extract real client IP from request headers, accounting for proxies.

        Returns:
            Client IP address as string.
        """

        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].rstrip()
        return request.remote_addr
    
    def create_short_link(self):
        """Handle POST /api/v1/shorten - create a short link."""

        data = request.get_json()

        try:
            validated = CreateShortLinkRequest(**data)
        except PydanticValidationError as e:
            return jsonify({
                "error": "VALIDATION_ERROR",
                "details": e.errors()
            }), 400
        
        user_ip = self._get_client_ip()
        user_agent = request.headers.get("User-Agent")

        result_dto = self.link_service.create_short_link(
            validated.url,
            user_ip=user_ip,
            user_agent=user_agent
        )

        response_data = ShortLinkResponse.from_dto(result_dto)

        status = 201 if result_dto.is_new else 200

        return jsonify(response_data.model_dump()), status
    
    def get_link_info(self, short_code: str):
        """Handle GET /api/v1/links/<short_code> - get link info."""
        try:
            result_dto = self.link_service.get_link_info(short_code)
        except LinkNotFoundError as e:
            return jsonify({
                "error": e.code, 
                "message": e.message
            }), 404

        response_data = ShortLinkResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump())
    
    def batch_create(self):
        """Handle POST /api/v1/batch/shorten - batch create links."""

        data = request.get_json()

        try:
            validated = BatchCreateLinkRequest(**data)
        except PydanticValidationError as e:
            return jsonify({
                "error": "VALIDATION_ERROR", "details": e.errors()
            }), 400

        user_ip = self._get_client_ip()
        user_agent = request.headers.get("User-Agent")

        result_dto = self.link_service.batch_create_short_links(
            validated.urls,
            user_ip=user_ip,
            user_agent=user_agent
        )
        response_data = BatchCreateResponse.from_dto(result_dto)
        
        return jsonify(response_data.model_dump()), 201
    
    def get_stats(self):
        """Handle GET /api/v1/stats - get service statistics."""

        result_dto = self.link_service.get_service_stats()
        response_data = ServiceStatsResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump())
