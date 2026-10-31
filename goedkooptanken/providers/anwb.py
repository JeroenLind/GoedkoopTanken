"""ANWB Onderweg: tankstations met prijzen binnen een kader (bounding box).

Endpoint en responsvorm zijn overgenomen uit de open-source bibliotheek pyfuelprices
(gebruikt door de Home Assistant-integratie ha-fuelprices). Dit is geen gedocumenteerde,
officieel ondersteunde publieke API: hij kan zonder waarschuwing wijzigen of verdwijnen.

Responsvorm (zoals verwacht):
  {"value": [{"id", "title", "address": {"streetAddress", "city", "postalCode"},
              "coordinates": {"latitude", "longitude"},
              "prices": [{"fuelType": "EURO95", "value": 1.859}, ...]}]}
Bij te veel resultaten geeft de API {"error": {"code": "limit_exceeded"}}; dan splitsen we
het kader in vieren.
"""

from __future__ import annotations

import urllib.parse

from .. import http
from ..geo import bounding_box, haversine_km
from ..models import DIESEL, LPG, PETROL95, PETROL98, Station
from .base import Provider, ProviderError

API_URL = "https://api.anwb.nl/routing/points-of-interest/v3/all"
MAX_SPLIT_DEPTH = 3

FUEL_MAP = {
    "EURO95": PETROL95,
    "EURO98": PETROL98,
    "DIESEL": DIESEL,
    "AUTOGAS": LPG,
}


class AnwbProvider(Provider):
    name = "anwb"
    label = "ANWB Onderweg"
    # Dekking volgens pyfuelprices; wij gebruiken NL, DE en BE.
    countries = ("NL", "DE", "BE")
    official = False
    note = ("ANWB Onderweg is geen officiële, gedocumenteerde bron. Die kan zonder bericht veranderen of "
            "wegvallen, en is niet door de ANWB goedgekeurd voor dit gebruik. Gebruik is op eigen risico; "
            "zet de bron uit als je dat liever niet wilt.")
    test_point = (51.1942, 5.9876, "Roermond")
    attribution = "Prijzen: ANWB Onderweg"

    def __init__(self):
        self.fuel_types_seen: set[str] = set()  # voor het `check`-commando

    def fetch(self, lat: float, lon: float, radius_km: float) -> list[Station]:
        box = bounding_box(lat, lon, radius_km)
        found: dict[str, Station] = {}
        self._fetch_box(box, 0, found)
        return [s for s in found.values()
                if haversine_km(lat, lon, s.lat, s.lon) <= radius_km]

    def _fetch_box(self, box, depth, found):
        min_lat, min_lon, max_lat, max_lon = box
        url = API_URL + "?" + urllib.parse.urlencode({
            "type-filter": "FUEL_STATION",
            "bounding-box-filter": f"{min_lat},{min_lon},{max_lat},{max_lon}",
        })
        data = http.fetch_json(url)
        error = data.get("error") if isinstance(data, dict) else None
        if error is None:
            for raw in data.get("value") or []:
                station = self.parse_station(raw)
                if station:
                    found[station.id] = station
            return
        if error.get("code") == "limit_exceeded" and depth < MAX_SPLIT_DEPTH:
            mid_lat, mid_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
            for sub in ((min_lat, min_lon, mid_lat, mid_lon),
                        (min_lat, mid_lon, mid_lat, max_lon),
                        (mid_lat, min_lon, max_lat, mid_lon),
                        (mid_lat, mid_lon, max_lat, max_lon)):
                self._fetch_box(sub, depth + 1, found)
            return
        raise ProviderError(f"ANWB gaf een fout: {error}")

    def parse_station(self, raw: dict) -> Station | None:
        coords = raw.get("coordinates") or {}
        if "latitude" not in coords or "longitude" not in coords or "id" not in raw:
            return None
        prices: dict[str, float] = {}
        for p in raw.get("prices") or []:
            ftype = str(p.get("fuelType", "")).upper()
            self.fuel_types_seen.add(ftype)
            canonical = FUEL_MAP.get(ftype)
            try:
                value = float(p.get("value"))
            except (TypeError, ValueError):
                continue
            if canonical and value > 0:
                prices[canonical] = value
        addr = raw.get("address") or {}
        address = ", ".join(x for x in (addr.get("streetAddress"), addr.get("city")) if x)
        return Station(
            id=f"anwb:{raw['id']}",
            name=raw.get("title") or "Onbekend station",
            lat=float(coords["latitude"]),
            lon=float(coords["longitude"]),
            source=self.name,
            address=address,
            prices=prices,
        )
