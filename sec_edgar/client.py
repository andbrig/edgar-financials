"""Rate-limited HTTP client for SEC EDGAR / data.sec.gov.

SEC fair-access rules: max 10 requests/second, and requests must carry a
User-Agent identifying the requester. We stay well under the limit.
"""
from __future__ import annotations

import os
import time
import threading
import requests

# SEC requires a User-Agent identifying the requester with real contact info.
# Set EDGAR_CONTACT_EMAIL to your email; the placeholder must be replaced
# before sustained production use.
_CONTACT = os.environ.get("EDGAR_CONTACT_EMAIL", "alfred-research@example.com")
USER_AGENT = f"Alfred-EDGAR-Research/1.0 (contact: {_CONTACT})"
MIN_INTERVAL = 0.15  # seconds between request starts -> ~6.6 req/s max

_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip",
    "Accept": "application/json",
})

_lock = threading.Lock()
_last_start = 0.0


def _pace() -> None:
    global _last_start
    with _lock:
        now = time.monotonic()
        wait = MIN_INTERVAL - (now - _last_start)
        if wait > 0:
            time.sleep(wait)
        _last_start = time.monotonic()


def get_json(url: str, retries: int = 5, timeout: int = 60):
    """GET a JSON URL. Returns parsed JSON, or None on 404. Retries 429/5xx."""
    backoff = 2.0
    for attempt in range(retries):
        _pace()
        try:
            r = _session.get(url, timeout=timeout)
        except requests.RequestException:
            time.sleep(backoff)
            backoff *= 2
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(backoff)
            backoff *= 2
            continue
        # Other client errors: don't retry forever
        if attempt < retries - 1:
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
    return None
