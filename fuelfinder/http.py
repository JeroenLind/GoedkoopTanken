"""Minimale HTTP-laag (alleen standaardbibliotheek).

Alle modules halen JSON op via `fetch_json`, zodat tests deze functie kunnen vervangen.
"""

from __future__ import annotations

import json
import os
import threading
import time
import contextlib
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "fuelfinder/0.1 (open source; https://github.com/)"


def user_agent() -> str:
    """Herkenbare User-Agent. Met FUELFINDER_CONTACT (bijv. een e-mailadres) kunnen beheerders van
    gedeelde diensten (Nominatim, OSRM) je bereiken als er iets misgaat."""
    contact = os.environ.get("FUELFINDER_CONTACT", "").strip()
    return f"{USER_AGENT[:-1]}; {contact})" if contact else USER_AGENT
TIMEOUT = 20


_local = threading.local()


@contextlib.contextmanager
def quick(timeout: float = 10.0):
    """Eén poging met een korte time-out in deze thread (voor de testknoppen: snel en eerlijk antwoord)."""
    _local.quick = timeout
    try:
        yield
    finally:
        _local.quick = None


class FetchError(Exception):
    """Mislukte HTTP-aanvraag, met een leesbare melding."""


def fetch_json(url: str, headers: dict[str, str] | None = None, retries: int = 2):
    req_headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    last: Exception | None = None
    timeout = getattr(_local, "quick", None)
    if timeout:
        retries = 0
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            # 4xx is zelden tijdelijk, dus niet opnieuw proberen (behalve 429)
            if 400 <= e.code < 500 and e.code != 429:
                raise FetchError(f"HTTP {e.code} van {_host(url)}: {body}") from e
            last = FetchError(f"HTTP {e.code} van {_host(url)}: {body}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = FetchError(f"{_host(url)}: {e}")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise last


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc
