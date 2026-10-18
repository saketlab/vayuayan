"""
Requests of the CPCB clients: send(), the old base64 endpoints, and the public
RSS station feed.

The clients send their requests through send(), so tests patch
cpcb_common.send. The RSS feed goes through utils.safe_get.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

import requests

from . import http_client
from .exceptions import CPCBError
from .utils import decode_b64_json_response, fetch_cpcb_rss_station_data, url_encode

logger = logging.getLogger(__name__)

T = TypeVar("T")


def send(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Send a request of a CPCB client, with the SSL fallback for CPCB hosts.

    The clients call it as cpcb_common.send, so tests can patch it here.

    Args:
        method: HTTP method ('get' or 'post').
        url: Request URL.
        **kwargs: Arguments for http_client.request, such as headers, data,
            session or timeout (default 30 seconds).

    Raises:
        requests.RequestException: If the request fails.
    """
    kwargs.setdefault("timeout", 30)
    return http_client.request(method, url, ssl_fallback=True, **kwargs)


# The errors of a data source that is down or answers garbage. Other errors
# are bugs, so they propagate.
SOURCE_ERRORS: Tuple[Type[BaseException], ...] = (requests.RequestException, ValueError)


def attempt(
    call: Callable[[], T],
    message: str,
    level: int = logging.INFO,
    errors: Tuple[Type[BaseException], ...] = SOURCE_ERRORS,
) -> Optional[T]:
    """Return call(), or log message % failure reason and return None.

    The log has the HTTP status or error type only, never the error text,
    which can have the request URL.
    """
    try:
        return call()
    except errors as e:
        logger.log(level, message, http_client.failure_reason(e))
        return None


def legacy_post(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    session: Optional[requests.Session] = None,
) -> Any:
    """POST to an old CPCB endpoint: base64 JSON in, base64 JSON out.

    Raises:
        requests.RequestException: If the request fails.
        ValueError: If the response is not base64 JSON.
    """
    response = send(
        "post",
        url,
        headers=headers,
        data=url_encode(payload),
        cookies=cookies,
        session=session,
    )
    return decode_b64_json_response(response)


class RSSFeed:
    """Mixin for the public CPCB RSS station feed, fetched at most once per client."""

    _rss_cache: Optional[List[Dict[str, Any]]] = None

    def _rss_cities(self) -> List[Dict[str, Any]]:
        """The RSS feed in the package station shape, or [] if it is unavailable."""
        if self._rss_cache is None:
            self._rss_cache = (
                attempt(
                    lambda: fetch_cpcb_rss_station_data(timeout=30),
                    "CPCB RSS feed unavailable (%s)",
                    logging.WARNING,
                    SOURCE_ERRORS + (CPCBError,),
                )
                or []
            )
        return self._rss_cache
