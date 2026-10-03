"""HTTP GET with retries, shared by every external source."""

from __future__ import annotations

import logging
import re
import time

import requests

log = logging.getLogger(__name__)

# 429 and 5xx are worth retrying; other 4xx mean the request itself is wrong.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
USER_AGENT = "FlatFair/0.1 (DAISI 2026 student project; open data client)"


class SourceError(RuntimeError):
    """An external source failed in a way retries could not fix."""


def get_with_retries(
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 5,
    backoff_seconds: float = 2.0,
    timeout_seconds: float = 90,
    session: requests.Session | None = None,
) -> requests.Response:
    http = session or requests
    last_error: str = "no attempt made"
    for attempt in range(1, max_retries + 1):
        try:
            response = http.get(
                url, params=params, timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            # Any 2xx counts: data.gov.sg's poll-download answers 201 on success.
            if 200 <= response.status_code < 300:
                return response
            # Strip query strings: error bodies can contain signed download URLs.
            body = re.sub(r"\?[^\s\"'<>]+", "?…", response.text[:300])
            last_error = f"HTTP {response.status_code}: {body[:200]}"
            if response.status_code not in RETRYABLE_STATUS:
                raise SourceError(f"GET {url} failed with {last_error}")
        if attempt < max_retries:
            wait = backoff_seconds * 2 ** (attempt - 1)
            log.warning("GET %s attempt %d/%d failed (%s); retrying in %.0fs", url, attempt, max_retries, last_error, wait)
            time.sleep(wait)
    raise SourceError(f"GET {url} failed after {max_retries} attempts: {last_error}")
