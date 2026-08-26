"""Shared TLS-tolerant HTTP requests used by the tbench.ai and Harbor-hub clients.

Both sites have occasionally tripped Python's default certificate trust
store; retrying once without verification keeps a single flaky connection
from aborting a bulk run.

Uses one shared, connection-pooled Session rather than the bare
`requests.request()` function: the latter opens a brand new TCP+TLS
connection for every single call, which under a thread pool means many
simultaneous fresh handshakes to the same host -- a pattern more likely to
trip a site's rate-limiting/bot-defense heuristics than the same request
volume over reused connections, and slower regardless (every call pays a
full handshake). `requests.Session` is safe to share across threads for
making requests."""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter

_POOL_SIZE = 32  # >= the largest worker count any caller uses, so no thread
                 # ever blocks waiting for a free pooled connection

_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=_POOL_SIZE, pool_maxsize=_POOL_SIZE)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

_RETRY_DELAY_S = 2  # one short pause before a single retry on a connection-
                    # level failure -- lets a brief block/hiccup clear


def _request(method: str, url: str, **kwargs):
    """Issue `method` against `url`, retrying once without TLS verification
    on an SSLError, and once more after a short delay on any other
    connection-level failure (DNS, timeout, reset). Returns the Response, or
    None if every attempt fails — callers decide how to read the status/body."""
    for attempt in range(2):
        try:
            try:
                return _session.request(method, url, **kwargs)
            except requests.exceptions.SSLError:
                return _session.request(method, url, verify=False, **kwargs)
        except requests.exceptions.RequestException:
            if attempt == 0:
                time.sleep(_RETRY_DELAY_S)
    return None


def get(url: str, *, headers: dict | None = None, timeout: float | tuple = 60, **kwargs):
    return _request("GET", url, headers=headers, timeout=timeout, **kwargs)


def post(url: str, *, headers: dict | None = None, timeout: float | tuple = 60, **kwargs):
    return _request("POST", url, headers=headers, timeout=timeout, **kwargs)
