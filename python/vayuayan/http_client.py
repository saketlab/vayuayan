"""
The one HTTP request helper of the package: retries and an SSL fallback.

CPCB certificates are often broken, so a request whose certificate check fails
is sent again without verification, and later requests to that host skip the
check. Log messages name the host and path only: the CPCB token request carries
the credentials in its query string, and requests puts the URL in its errors.
"""

import logging
import time
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Set
from urllib.parse import urlsplit

import requests
import urllib3
from tqdm import tqdm

from .constants import DEFAULT_BACKOFF_FACTOR

logger = logging.getLogger(__name__)

# Process-wide; make it per-session if one process needs both verified and
# unverified clients for the same host
_INSECURE_HOSTS: Set[str] = set()

Sender = Callable[..., requests.Response]


def request(
    method: str,
    url: str,
    *,
    session: Optional[requests.Session] = None,
    retries: int = 0,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ssl_fallback: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """Send a request and raise for an HTTP error status.

    Args:
        method: HTTP method, such as "get" or "post".
        url: Request URL.
        session: Optional session to send the request through.
        retries: Number of times to send the request again after a network
            error or a 5xx status. 4xx statuses are not retried.
        backoff_factor: The wait before retry n is backoff_factor * 2**n seconds.
        ssl_fallback: If True, send the request again without SSL verification
            when the verification fails. Only for hosts with known broken
            certificates, such as CPCB.
        **kwargs: More arguments for requests, such as headers, data or timeout.

    Returns:
        The response, with a 2xx or 3xx status.

    Raises:
        requests.RequestException: If the last attempt fails.
    """
    send: Sender = session.request if session is not None else requests.request
    where = _where(url)
    for attempt in range(retries):
        try:
            return _send(send, method, url, ssl_fallback, **kwargs)
        except requests.RequestException as e:
            status = getattr(e.response, "status_code", None)
            if status is not None and 400 <= status < 500:
                raise
            wait = backoff_factor * 2**attempt
            logger.debug(
                "%s %s failed (%s); retry %d/%d in %.1fs",
                method.upper(),
                where,
                failure_reason(e),
                attempt + 1,
                retries,
                wait,
            )
            time.sleep(wait)
    return _send(send, method, url, ssl_fallback, **kwargs)


def _send(
    send: Sender, method: str, url: str, ssl_fallback: bool, **kwargs: Any
) -> requests.Response:
    host = urlsplit(url).hostname or ""
    verify = kwargs.pop("verify", True)
    if verify and not (ssl_fallback and host in _INSECURE_HOSTS):
        try:
            response = send(method, url, verify=True, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError:
            if not ssl_fallback:
                raise
            logger.warning(
                "SSL verification failed for %s; sending without verification", host
            )
            _INSECURE_HOSTS.add(host)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        response = send(method, url, verify=False, **kwargs)
    response.raise_for_status()
    return response


@contextmanager
def atomic_path(path: Path) -> Iterator[Path]:
    """Yield a temporary path to write; it becomes path only if the block succeeds.

    So path never holds a partly written file, also after an interruption.
    """
    part = path.with_name(path.name + ".part")
    try:
        yield part
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def stream_to_file(response: requests.Response, path: Path, desc: str) -> int:
    """Write a streamed response to path with a progress bar; return its size."""
    total_size = int(response.headers.get("content-length", 0))
    with atomic_path(path) as part, open(part, "wb") as f:
        with tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=desc,
            ncols=80,
        ) as pbar:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))
    return path.stat().st_size


def failure_reason(error: BaseException) -> str:
    """The HTTP status of a failed request, else the error type; never the URL."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    return str(status) if status is not None else type(error).__name__


def _where(url: str) -> str:
    """The host and path of a URL, without the query string."""
    parts = urlsplit(url)
    return f"{parts.hostname}{parts.path}"
