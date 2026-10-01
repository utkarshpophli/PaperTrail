"""One place for provider HTTP timeout policy.

A full-document extraction on a large hosted model routinely exceeds a minute
before the first byte, so the read timeout comes from settings
(``provider_read_timeout_seconds``); connect/write/pool stay short so an
unreachable host still fails fast.
"""

import httpx

from app.core.config import get_settings

# Model listing is a cheap metadata call; it must never hang a settings UI.
LIST_MODELS_TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)


def default_timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=10, read=get_settings().provider_read_timeout_seconds, write=30, pool=10)
