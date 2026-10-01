"""Rate limiting. A single shared ``Limiter`` instance so tests can reset its
in-memory storage between cases via ``limiter.reset()``.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def rate_limit_key(request: Request) -> str:
    """Per-user key for authenticated, expensive endpoints (SECURITY.md:
    "per-user rate limits on analysis endpoints") — falls back to per-IP
    (the unauthenticated-endpoint rule) if get_current_user hasn't run yet
    for this request, so it's always a valid key either way.
    """
    user_id = getattr(request.state, "user_id", None)
    return user_id if user_id else get_remote_address(request)
