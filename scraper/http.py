"""Shared HTTP layer.

The four Polish plot sources each carry their own copy of this retry loop.
New code (the Brussels monitor) uses this module instead of copy-pasting it
again; the existing sources are deliberately left untouched.
"""

import logging
import time
from typing import Optional

from curl_cffi import requests

logger = logging.getLogger(__name__)

# Belgian portals serve EN/FR/NL; ask for English first, then the local languages.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,fr-BE;q=0.8,fr;q=0.7,nl-BE;q=0.6,nl;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

RETRY_DELAYS = [2, 8, 32]


def make_session(impersonate: str = "chrome120", headers: Optional[dict] = None):
    session = requests.Session(impersonate=impersonate)
    session.headers.update(headers or BROWSER_HEADERS)
    return session


def get_html(
    session,
    url: str,
    *,
    retries: int = 3,
    timeout: int = 30,
    label: str = "",
) -> Optional[str]:
    """GET a page, retrying with backoff. Returns None when every attempt fails."""
    who = label or "http"
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            logger.warning("%s returned %d for %s", who, resp.status_code, url)
        except Exception as e:
            logger.warning("%s request error for %s: %s", who, url, e)
        if attempt < retries - 1:
            time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    return None
