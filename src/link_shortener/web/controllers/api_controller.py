"""
Main API controller for link operations and statistics.

Access rules:
  - POST /api/v1/shorten – 'link:create'; anonymous callers hold it through
    the 'guest' role and are additionally bounded by the guest quota.
  - POST /api/v1/batch/shorten – same as above.
  - GET /api/v1/links/<code> – everyone. The owner's identifier and the
    click counters are included only for those entitled to them: the link's
    owner, an admin, a holder of 'stats:view_any', or whoever presents that
    link's deletion token, which is what a guest holds in place of an owner.
  - GET /api/v1/links/<code>/extended – the same four. Every field it adds
    is computed from the counters above, so the two endpoints withhold from
    the same people or neither withholds anything.
  - GET /api/v1/stats – roles with 'stats:view_basic'; the popular-links
    breakdown additionally needs 'stats:view_full'.
  - GET /api/v1/stats/visits and /stats/visits/daily – 'stats:view_basic'
    for the service-wide answer, 'link:view_own' for 'scope=mine'. A
    named '?code=' is checked against the link's own owner on top of
    either. The top-links table needs 'stats:view_full'.
  - GET /api/v1/links/mine – 'link:view_own'.
  - GET /api/v1/stats/mine – 'link:view_own'.
  - DELETE /api/v1/links/<code> – 'link:delete_own' for one's own link,
    'link:delete_any' for anyone else's. Decided inside the use case,
    against the stored row.
"""

from flask import Blueprint, current_app, g, jsonify, request

from link_shortener.domain import (
    DomainError, LinkNotFoundError, PermissionDeniedError, SystemPermissions
)
from link_shortener.application import LinkService, AdminService, AuthorizationService
from link_shortener.web.schemas.batch import BatchCreateResponse
from link_shortener.web.schemas.link import ExtendedLinkInfoResponse, ShortLinkResponse
from link_shortener.web.schemas.requests import BatchCreateLinkRequest, CreateShortLinkRequest
from link_shortener.web.schemas.stats import ServiceStatsResponse
from link_shortener.web.schemas.visit_stats import (
    DailyVisitsResponse, VisitStatsResponse,
)
from link_shortener.web.security.authorization import (
    can_view_link_details,
    made_this_link,
    presented_link_id,
    require_can_view_link_details,
)
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.deletion_token import issue as issue_deletion_token
from link_shortener.web.paging import window_from_query
from link_shortener.web.request_body import json_object
from link_shortener.web.security.decorators import (
    login_required, require_any_permission, require_permission,
)
from link_shortener.domain.i18n import N_

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
        self.bp.add_url_rule('/stats/visits', view_func=self.get_visit_stats, methods=['GET'])
        self.bp.add_url_rule('/stats/visits/daily', view_func=self.get_daily_visits, methods=['GET'])

    # ------------------------------------------------------------------
    # POST /api/v1/shorten
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.LINK_CREATE.value)
    def create_short_link(self):
        """
        Create a short link.

        Accepts JSON with ``url`` and optional ``ttl_seconds``.
        Returns 201 if new, 200 if existing.
        """
        data = json_object()
        validated = CreateShortLinkRequest(**data)
        context = create_request_context()
        ttl = validated.ttl_seconds if validated.ttl_seconds is not None else 0
        result_dto = self.link_service.create_short_link(validated.url, context, ttl_seconds=ttl)
        response_data = ShortLinkResponse.from_dto(result_dto)

        # A link with no account behind it has no owner to compare against,
        # so its creator could never delete it -- only a holder of
        # 'link:delete_any'. The token is that link's only handle, and it is
        # returned here and nowhere else.
        #
        # Only for a link this request created. Guests deduplicate by
        # address, so a second caller behind the same NAT asking for the same
        # URL gets the first one's link back; issuing the token again would
        # hand it their handle. The token goes once, to whoever created the
        # row.
        if result_dto.is_new and result_dto.owner_id is None and result_dto.link_id:
            response_data.deletion_token = issue_deletion_token(
                current_app.config["SECRET_KEY"], result_dto.link_id
            )

        status = 201 if result_dto.is_new else 200
        return jsonify(response_data.model_dump()), status

    # ------------------------------------------------------------------
    # GET /api/v1/links/<short_code>
    # ------------------------------------------------------------------
    def get_link_info(self, short_code: str):
        """
        Get basic information about a link. Public endpoint.

        Public in the sense that anyone may resolve a code to the address
        behind it and see when it was made. Not public in what it says
        about the link's owner or the link's traffic.

        A short code is seven guessable characters, and this endpoint used
        to turn any of them into the owner's UUID plus a click count. The
        counters go out with the identifier because every field the
        extended endpoint withholds is computed from them: leaving
        ``clicks`` and ``last_accessed`` here made that endpoint's
        restriction a formality anyone could step around with arithmetic.
        """
        context = create_request_context()
        result_dto = self.link_service.get_link_info(short_code, context)
        response_data = ShortLinkResponse.from_dto(result_dto)

        # The token is the only thing a guest link has in place of an
        # owner, and it is what the delete route already accepts as proof.
        # Without this the promise made on the landing page and in the
        # guide -- "its click counters are shown only to whoever made the
        # link" -- was true of nobody for a guest link: `owner_id` is
        # null, so the check below withheld the counters from the person
        # who made it as firmly as from a stranger. Measured: a guest was
        # handed `clicks: 0` in the answer that created the link and
        # `clicks: null` on every look at it afterwards.
        #
        # It widens nothing. The token is signed with `SECRET_KEY` and
        # names the row rather than the code, so it proves this caller
        # made *this* link and stops proving anything the moment the link
        # is deleted and its code handed out again.
        made_it = made_this_link(result_dto.link_id)
        if not made_it and not can_view_link_details(
            result_dto.owner_id, self.authorization_service
        ):
            response_data.owner_id = None
            response_data.clicks = None
            response_data.last_accessed = None

        # `Vary: X-Deletion-Token` and, when the token matched, `no-store`
        # are not set here: `presented_link_id` marked the request and
        # `PrivateCacheMiddleware` marks the answer. This route had those
        # two lines and its `/extended` neighbour, reading the same header
        # for the same decision, did not.
        return jsonify(response_data.model_dump())

    # ------------------------------------------------------------------
    # GET /api/v1/links/<short_code>/extended
    # ------------------------------------------------------------------
    def get_extended_link_info(self, short_code: str):
        """
        Get extended information about a link.

        Restricted to the link's owner, an admin, a holder of
        ``stats:view_any``, or whoever presents the deletion token of this
        link -- the same four the basic endpoint shows counters to, and
        not by coincidence. Every field here is a pure
        function of ``clicks``, ``created_at`` and ``last_accessed`` plus
        two configuration constants, so while those were public this
        restriction was a formality: an anonymous caller could recompute
        ``is_popular``, ``age_days`` and ``clicks_per_day`` exactly.

        The lookup happens before the check, so a refusal here tells the
        caller the code exists. That is not a disclosure: the basic
        endpoint and the redirect answer the same question publicly.
        """
        context = create_request_context()
        result_dto = self.link_service.get_extended_link_info(short_code, context)

        # The same proof the basic endpoint takes, and for the same
        # reason: every field here is arithmetic on `clicks`,
        # `created_at` and `last_accessed`, which the holder of this token
        # is already shown there. Refusing them the derived figures while
        # handing them the inputs is the "formality" this docstring
        # objects to, arriving from the other side.
        if not made_this_link(result_dto.link_id):
            require_can_view_link_details(
                result_dto.owner_id, self.authorization_service
            )
        response_data = ExtendedLinkInfoResponse.from_dto(result_dto)
        return jsonify(response_data.model_dump())

    # ------------------------------------------------------------------
    # POST /api/v1/batch/shorten
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.LINK_CREATE.value)
    def batch_create(self):
        """Batch create short links."""
        data = json_object()
        validated = BatchCreateLinkRequest(**data)
        context = create_request_context()
        result_dto = self.link_service.batch_create_short_links(validated.urls, context)
        response_data = BatchCreateResponse.from_dto(result_dto)

        # Same rule as the single endpoint, and it belongs on both: a guest
        # who shortens ten URLs at once has the same claim on them as one
        # who shortens a single URL. Only for links this request created --
        # a deduplication hit is somebody's existing link, possibly
        # somebody else's behind the same address.
        if getattr(g, "current_user", None) is None:
            secret = current_app.config["SECRET_KEY"]
            for item, source in zip(response_data.results, result_dto.items):
                if source.is_new and source.link_id:
                    item.deletion_token = issue_deletion_token(
                        secret, source.link_id
                    )
        return jsonify(response_data.model_dump()), 200

    # ------------------------------------------------------------------
    # GET /api/v1/stats
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.STATS_VIEW_BASIC.value)
    def get_stats(self):
        """
        Get service-wide statistics.

        Totals need ``stats:view_basic``. The popular-links breakdown needs
        ``stats:view_full`` on top: those entries carry other people's
        original URLs, which is a different thing to disclose than a count.
        """
        context = create_request_context()
        result_dto = self.link_service.get_service_stats(context)
        response_data = ServiceStatsResponse.from_dto(result_dto)
        if not self.authorization_service.is_allowed(
            g.get('_domain_user'), SystemPermissions.STATS_VIEW_FULL.value
        ):
            response_data.popular_links = []
        return jsonify(response_data.model_dump())

    def _require(self, permission: str) -> None:
        """
        Refuse this request unless the caller holds one named permission.

        For the checks a decorator cannot make because the answer depends
        on what the request asked for: one address here serves both the
        service-wide counts and the caller's own, and the two are opened
        by different permissions. The decorator lets a holder of either
        through, and this decides which one this particular request needed.

        Args:
            permission: What the caller has to hold.

        Raises:
            PermissionDeniedError: When they do not. It carries the
                permission that was wanted, so the refusal recorded in the
                audit journal names it.
        """
        if not self.authorization_service.is_allowed(
            g.get('_domain_user'), permission
        ):
            raise PermissionDeniedError(
                N_("Not authorized"), required=[permission]
            )

    def _require_may_read_one_links_traffic(self, short_code, context):
        """
        Check that this caller may see the traffic of one named link.

        ``scope=mine`` is scoped by the account behind the request, and a
        service-wide answer is a count nobody owns -- but a ``code``
        names somebody's link, and its traffic is that link's private
        detail in exactly the sense ``can_view_link_details`` was written
        for. Without this the two endpoints below handed an anonymous
        caller the totals, the timeline and the device split of any code
        they could guess, while the neighbouring endpoints refused the
        same caller the same figures: ``/links/<code>`` nulls its
        counters and ``/links/<code>/extended`` answers 401.

        The lookup happens before the check, so a refusal tells the
        caller the code exists -- which the redirect and the basic
        endpoint already answer publicly, and which is the same trade
        ``/extended`` makes.

        The link it looked up is handed back rather than dropped. Both
        endpoints below need that link's id to read its traffic, and
        finding it a second time meant the same
        ``SELECT ... FROM urls`` ran twice for every request -- measured,
        two identical selects and four pool checkouts per call, on an
        endpoint the chart polls every ten seconds.

        Args:
            short_code: The code named in the query string, or ``None``.
            context: The request context to look the link up with.

        Returns:
            The link, or ``None`` when no code was named.

        Raises:
            DomainError: ``UNAUTHENTICATED`` or ``FORBIDDEN`` when the
                caller may not see that link's details, and whatever the
                lookup raises when no such link exists.
        """
        if not short_code:
            return None

        link = self.link_service.get_link_info(short_code, context)
        require_can_view_link_details(link.owner_id, self.authorization_service)
        return link

    # ------------------------------------------------------------------
    # GET /api/v1/stats/visits
    # ------------------------------------------------------------------
    @require_any_permission(
        SystemPermissions.LINK_VIEW_OWN.value,
        SystemPermissions.STATS_VIEW_BASIC.value,
    )
    def get_visit_stats(self):
        """
        Recorded visits over a span, for the service or for the caller.

        Two questions behind one address, and they are not opened by the
        same permission. The service-wide answer is a count nobody owns
        and needs ``stats:view_basic``, which the seeded ``guest`` role
        carries. ``scope=mine`` is the caller's own traffic and needs
        ``link:view_own`` -- the permission the rest of that account's own
        material is behind, including the page these charts are drawn on
        and ``/stats/mine`` beside them.

        Asked for under ``stats:view_basic`` alone, ``scope=mine`` made
        seeing one's own statistics depend on a permission whose own
        description is "basic *service* statistics", and the dashboard page
        said so in three places while the route did the opposite: measured,
        a role holding ``link:view_own`` opened ``/dashboard/stats``, was
        served its tiles, and got 403 from both charts on it.

        A named ``?code=`` is a third question and carries its own door:
        ``require_can_view_link_details``, against that link's owner. It
        does not additionally need ``stats:view_basic``, which is the
        permission for a count of everything -- and requiring it anyway
        shut a holder of ``stats:view_any`` out of the page written for
        exactly that holder: measured, ``/dashboard/links/<code>/stats``
        answered 200 and the charts on it 403.

        The decorator lets either through and the checks below pick the
        one this request actually needs -- the arrangement the journal
        page uses, where a permission opens the door and the endpoint
        behind each panel enforces its own.

        The top-links table needs ``stats:view_full`` on top of either: a
        short code is somebody's link, which is a different disclosure than
        a count.
        """
        context = create_request_context()
        scope = request.args.get("scope", "service")
        period = request.args.get("period", "7d")

        # The named code first, because whether it was named is what
        # decides which permission the rest of this needs.
        named = self._require_may_read_one_links_traffic(
            request.args.get("code"), context
        )

        owner_id = None
        if scope == "mine":
            if not g.get("current_user"):
                raise DomainError(
                    N_("Sign in to see your own statistics"), code="UNAUTHENTICATED"
                )
            self._require(SystemPermissions.LINK_VIEW_OWN.value)
            owner_id = g.current_user.id
        elif named is None:
            self._require(SystemPermissions.STATS_VIEW_BASIC.value)

        summary = self.link_service.get_visit_stats(
            context,
            period=period,
            link_id=named.link_id if named else None,
            owner_id=owner_id,
        )
        response = VisitStatsResponse.from_domain(summary)
        if owner_id is None and not self.authorization_service.is_allowed(
            g.get('_domain_user'), SystemPermissions.STATS_VIEW_FULL.value
        ):
            response.top_links = []
        return jsonify(response.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # GET /api/v1/stats/visits/daily
    # ------------------------------------------------------------------
    @require_any_permission(
        SystemPermissions.LINK_VIEW_OWN.value,
        SystemPermissions.STATS_VIEW_BASIC.value,
    )
    def get_daily_visits(self):
        """
        Visits per day, reaching past the raw rows into the roll-up.

        Same scoping as ``/stats/visits``, and the same two permissions
        behind it: ``link:view_own`` for one's own, ``stats:view_basic``
        for the service-wide count. The two endpoints are drawn on one
        page by one script, so a caller entitled to one chart and refused
        the other would read half a screen.

        Separate endpoint rather than a ``granularity`` parameter because
        it answers from a different pair of tables and takes a different
        bound: a year of days is a fine question, a year of hours is not.
        """
        context = create_request_context()
        scope = request.args.get("scope", "service")

        # What is wrong with the request, before who is asking -- the order
        # `decisions.md` settles for the administrative routes, and there
        # is no reason for this one to answer in a different order. A
        # mistyped `days` beside a code somebody may not read should say
        # which of the two to fix first, and it is the one the caller can.
        try:
            days = int(request.args.get("days", 90))
        except ValueError as invalid:
            raise DomainError(
                N_("days must be a whole number"), code="VALIDATION_ERROR"
            ) from invalid

        named = self._require_may_read_one_links_traffic(
            request.args.get("code"), context
        )

        owner_id = None
        if scope == "mine":
            if not g.get("current_user"):
                raise DomainError(
                    N_("Sign in to see your own statistics"), code="UNAUTHENTICATED"
                )
            self._require(SystemPermissions.LINK_VIEW_OWN.value)
            owner_id = g.current_user.id
        elif named is None:
            self._require(SystemPermissions.STATS_VIEW_BASIC.value)

        buckets = self.link_service.get_daily_visits(
            context,
            days=days,
            link_id=named.link_id if named else None,
            owner_id=owner_id,
        )
        return jsonify(
            DailyVisitsResponse.from_domain(buckets).model_dump(mode="json")
        )

    # ------------------------------------------------------------------
    # DELETE /api/v1/links/<short_code>
    # ------------------------------------------------------------------
    def delete_link(self, short_code: str):
        """
        Delete a short link (owner, admin, or the holder of its token).

        No ``@login_required`` here, and the reason is not that the endpoint
        got looser. Whether a caller may delete a link is decided in one
        place -- the use case, against the row it is about to delete -- and
        a decorator in front of it could only answer a different question:
        "is anybody logged in". That question has the wrong answer for a
        guest link, whose creator has no account and whose only proof is the
        token issued when it was made. A caller with neither an account nor
        a token is still refused, by the use case, with the same 401 as
        before.

        The ownership question is not asked here either: asking it through
        ``get_link_info`` would make "is this yours" only as reliable as
        whatever is in the cache. The use case decides it from the row it
        deletes, in the same transaction.
        """
        context = create_request_context()
        # A token proves its holder created this particular link. It names
        # the row, not the code: codes are freed by deletion and issued
        # again, so a token naming one would go on deleting whatever link
        # took it next.
        authorized_link_id = presented_link_id()
        deleted = self.link_service.delete_link(
            short_code,
            context,
            enforce_ownership=True,
            authorized_link_id=authorized_link_id,
        )
        if not deleted:
            raise LinkNotFoundError(short_code)
        return jsonify({"message": "Link deleted"})

    # ------------------------------------------------------------------
    # GET /api/v1/links/mine
    # ------------------------------------------------------------------
    @login_required
    @require_permission(SystemPermissions.LINK_VIEW_OWN.value)
    def get_my_links(self):
        """Get links created by the current user with pagination."""
        user = g.current_user
        context = create_request_context()
        limit, offset = window_from_query(default_limit=50)
        links = self.link_service.get_user_links(user.id, context, offset=offset, limit=limit)
        return jsonify([ShortLinkResponse.from_dto(link).model_dump() for link in links])

    # ------------------------------------------------------------------
    # GET /api/v1/stats/mine
    # ------------------------------------------------------------------
    @login_required
    @require_permission(SystemPermissions.LINK_VIEW_OWN.value)
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
