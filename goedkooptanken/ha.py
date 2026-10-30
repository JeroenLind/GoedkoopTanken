"""Kleine, alleen-lezen koppeling met Home Assistant (alleen actief als add-on).

De Supervisor geeft de add-on een token in SUPERVISOR_TOKEN. Dat token heeft brede rechten, dus
deze module doet bewust maar twee dingen: één entiteit lezen en de lijst van trackers ophalen.
Er wordt nooit iets geschreven, en het token komt nergens in een log of antwoord.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

API = "http://supervisor/core/api"
TIMEOUT = 10
ENTITY_RE = re.compile(r"^device_tracker\.[a-z0-9_]+$")


class HAError(Exception):
    """Leesbare melding als Home Assistant niet bereikbaar is of geen locatie geeft."""


def available() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def _get(path: str):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise HAError("Niet gestart als Home Assistant-add-on")
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HAError("Entiteit niet gevonden in Home Assistant" if e.code == 404
                      else f"Home Assistant antwoordde met HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise HAError(f"Home Assistant is niet bereikbaar: {e}") from e


def location(entity: str) -> tuple[float, float, float | None]:
    """(breedte, lengte, nauwkeurigheid in m) van een device_tracker."""
    if not ENTITY_RE.match(entity or ""):
        raise HAError("Kies eerst een tracker in de instellingen")
    attrs = (_get("/states/" + urllib.parse.quote(entity)) or {}).get("attributes") or {}
    lat, lon = attrs.get("latitude"), attrs.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise HAError("Deze tracker geeft nu geen locatie")
    acc = attrs.get("gps_accuracy")
    return float(lat), float(lon), float(acc) if isinstance(acc, (int, float)) else None


def trackers() -> list[dict]:
    """Beschikbare device_tracker-entiteiten met een locatie, met hun naam."""
    out = []
    for st in _get("/states") or []:
        eid = st.get("entity_id", "")
        attrs = st.get("attributes") or {}
        if ENTITY_RE.match(eid) and "latitude" in attrs:
            out.append({"entity_id": eid, "name": attrs.get("friendly_name") or eid})
    return sorted(out, key=lambda t: t["name"].lower())
