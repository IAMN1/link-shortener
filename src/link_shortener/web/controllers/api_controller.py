"""
Main API controller for link operations and statistics.

Access rules:
  - POST /api/v1/shorten – everyone (guests have limits).
  - GET /api/v1/links/<code> – authenticated users with permission on the specific link.
  - GET /api/v1/links/<code>/extended – same as above.
  - GET /api/v1/stats – roles with 'stats:view_basic'.
  - GET /api/v1/links/mine – authenticated users only.
  - GET /api/v1/stats/mine – authenticated users only.
"""

from flask import Blueprint, g, jsonify, request

from link_shortener.domain import SystemPermissions
from link_shortener.application import LinkService, AdminService, AuthorizationService
from link_shortener.web.schemas.batch import BatchCreateResponse
from link_shortener.web.schemas.link import ExtendedLinkInfoResponse, ShortLinkResponse
from link_shortener.web.schemas.requests import BatchCreateLinkRequest, CreateShortLinkRequest
from link_shortener.web.schemas.stats import ServiceStatsResponse
from link_shortener.web.security.authorization import check_can_view_link
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import login_required, require_permission

class ApiController:
    """Controller for REST API endpoints (JSON)."""

    def __init__(self, link_service: LinkService, admin_service: AdminService, authorization_service: AuthorizationService):
        self.link_service = link_service
        self.admin_service = admin_service
        self.authorization_service = authorization_service
        self.bp = Blueprint("api", __name__, url_prefix="/api/v1")
        self._register_routes()

    def _register_routes(self):
        self.bp.add_url_rule('/shorten', view_func=self.create_short_link, methods=['POST'])
        self.bp.add_url_rule('/links/<short_code>', view_func=self.get_link_info, methods=['GET'])
        self.bp.add_url_rule('/links/<short_code>/extended', view_func=self.get_extended_link_info, methods=['GET'])
        self.bp.add_url_rule('/batch/shorten', view_func=self.batch_create, methods=['POST'])
        self.bp.add_url_rule('/stats', view_func=self.get_stats, methods=['GET'])
        self.bp.add_url_rule('/links/mine', view_func=self.get_my_links, methods=['GET'])
        self.bp.add_url_rule('/links/<short_code>', view_func=self.delete_link, methods=['DELETE'])
        self.bp.add_url_rule('/stats/mine', view_func=self.get_my_stats, methods=['GET'])

    # ------------------------------------------------------------------
    # POST /api/v1/shorten
    # ------------------------------------------------------------------
    def create_short_link(self):
        """
        Create a short link.

        Accepts JSON with ``url`` and optional ``ttl_seconds``.
        Returns 201 if new, 200 if existing.
        """
        data = request.get_json()
        validated = CreateShortLinkRequest(**data)
        context = create_request_context()
        ttl = validated.ttl_seconds if validated.ttl_seconds is not None else 0
        result_dto = self.link_service.create_short_link(validated.url, context, ttl_seconds=ttl)
        response_data = ShortLinkResponse.from_dto(result_dto)
        status = 201 if result_dto.is_new else 200
        return jsonify(response_data.model_dump()), status

    # ------------------------------------------------------------------
    # GET /api/v1/links/<short_code>
    # ------------------------------------------------------------------
    def get_link_info(self, short_code: str):
        """Get basic information about a link. Public endpoint."""
        context = create_request_context()
        result_dto = self.link_service.get_link_info(short_code, context)
        response_data = ShortLinkResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump())

    # ------------------------------------------------------------------
    # GET /api/v1/links/<short_code>/extended
    # ------------------------------------------------------------------
    def get_extended_link_info(self, short_code: str):
        """Get extended information about a link. Public endpoint."""
        context = create_request_context()
        result_dto = self.link_service.get_extended_link_info(short_code, context)
        response_data = ExtendedLinkInfoResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump())

    # ------------------------------------------------------------------
    # POST /api/v1/batch/shorten
    # ------------------------------------------------------------------
    def batch_create(self):
        """Batch create short links."""
        data = request.get_json()
        validated = BatchCreateLinkRequest(**data)
        context = create_request_context()
        result_dto = self.link_service.batch_create_short_links(validated.urls, context)
        response_data = BatchCreateResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump()), 200

    # ------------------------------------------------------------------
    # GET /api/v1/stats
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.STATS_VIEW_BASIC.value)
    def get_stats(self):
        """Get service-wide statistics (analyst/admin)."""
        context = create_request_context()
        result_dto = self.link_service.get_service_stats(context)
        response_data = ServiceStatsResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump())

    # ------------------------------------------------------------------
    # DELETE /api/v1/links/<short_code>
    # ------------------------------------------------------------------
    @login_required
    def delete_link(self, short_code: str):
        """Delete a short link (owner or admin only)."""
        context = create_request_context()
        info = self.link_service.get_link_info(short_code, context)
        check_can_view_link(info.owner_id, self.authorization_service)
        deleted = self.link_service.delete_link(short_code, context)
        if not deleted:
            return jsonify({"error": "Link not found"}), 404
        return jsonify({"message": "Link deleted"})

    # ------------------------------------------------------------------
    # GET /api/v1/links/mine
    # ------------------------------------------------------------------
    @login_required
    def get_my_links(self):
        """Get links created by the current user with pagination."""
        user = g.current_user
        context = create_request_context()
        offset = request.args.get("offset", 0, type=int)
        limit = request.args.get("limit", 50, type=int)
        offset = max(0, offset)
        limit = max(1, min(limit, 200))
        links = self.link_service.get_user_links(user.id, context, offset=offset, limit=limit)
        return jsonify([ShortLinkResponse.from_dto(link).model_dump() for link in links])

    # ------------------------------------------------------------------
    # GET /api/v1/stats/mine
    # ------------------------------------------------------------------
    @login_required
    def get_my_stats(self):
        """Get personal link statistics."""
        user = g.current_user
        context = create_request_context()
        stats = self.admin_service.get_user_activity_stats(user.id, context)
        return jsonify({
            "total_links": stats.total_links,
            "total_clicks": stats.total_clicks,
            "avg_clicks_per_link": stats.avg_clicks_per_link,
            "recent_links": [ShortLinkResponse.from_dto(link).model_dump() for link in stats.recent_links]
        })
