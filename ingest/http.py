from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def send(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    tries: int,
    wait: float,
    **kwargs,
) -> httpx.Response:
    """Send a request, retrying on network errors and 429/5xx.

    Returns the final response without raising on HTTP status; callers decide
    how to treat 4xx (e.g. 404 for a page that no longer exists).
    """
    for attempt in range(1, tries + 1):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt == tries:
                raise
            log.warning("%s %s failed (%s), retry %d/%d", method, url, exc.__class__.__name__, attempt, tries)
            time.sleep(wait)
            continue
        if resp.status_code in RETRY_STATUS and attempt < tries:
            log.warning("%s %s -> %d, retry %d/%d", method, url, resp.status_code, attempt, tries)
            time.sleep(_retry_after(resp) or wait)
            continue
        return resp
    raise AssertionError("unreachable")
