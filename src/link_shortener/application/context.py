from dataclasses import dataclass
from typing import Any, Dict, Optional

from link_shortener.application.dtos.current_user_info import CurrentUserInfo


@dataclass(frozen=True)
class RequestContext:
    """
    Holds metadata about the current HTTP request.

    This object is created by the web layer and injected into use cases.
    It is immutable to prevent accidental modification.

    Attributes:
        request_id: Unique request identifier (from middleware).
        remote_addr: Client IP address (proxy-aware).
        user_agent: User-Agent header.
        request_path: URL path of the request.
        request_method: HTTP method (GET, POST, ...).
        current_user: Authenticated user info, if available.
    """
    request_id: str
    remote_addr: Optional[str] = None
    user_agent: Optional[str] = None
    request_path: Optional[str] = None
    request_method: Optional[str] = None
    current_user: Optional[CurrentUserInfo] = None

    def for_logging(self) -> Dict[str, Any]:
        """Extract a flat dictionary for structured logging.

        Returns:
            Dict containing request_id, remote_addr, user_agent,
            request_path, request_method, and user_id (if present)."""
        data = {
            'request_id': self.request_id,
            'remote_addr': self.remote_addr,
            'user_agent': self.user_agent,
            'request_path': self.request_path,
            'request_method': self.request_method,
        }
        if self.current_user:
            data['user_id'] = self.current_user.id
        return data
