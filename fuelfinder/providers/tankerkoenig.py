"""Tankerkönig: Duitse tankstationprijzen (data van de Markttransparenzstelle MTS-K).

Gratis API-key aanvragen op https://creativecommons.tankerkoenig.de. De data valt onder
CC BY 4.0, dus de bronvermelding hieronder moet zichtbaar blijven.
Maximale zoekstraal van de API: 25 km. Vraag niet vaker dan eens per paar minuten.
"""

from __future__ import annotations

import urllib.parse

from .. import http
from ..models import DIESEL, PETROL95, PETROL98, Station
from .base import Provider, ProviderError

API_URL = "https://creativecommons.tankerkoenig.de/json/list.php"
MAX_RADIUS_KM = 25.0


class TankerkoenigProvider(Provider):
    name = "tankerkoenig"
    countries = ("DE",)
    attribution = "Duitse prijzen: Tankerkönig.de / MTS-K, licentie CC BY 4.0"
    max_radius_km = MAX_RADIUS_KM

    def __init__(self, api_key: str | None, allow_e10: bool = True):
        self.api_key = api_key
        self.allow_e10 = allow_e10

    def fetch(self, lat: float, lon: float, radius_km: float) -> list[Station]:
        if not self.api_key:
            raise ProviderError(
                "Geen Tankerkönig API-key. Vraag er gratis een aan op "
                "creativecommons.tankerkoenig.de en zet hem in config.toml of in de "
                "omgevingsvariabele TANKERKOENIG_API_KEY.")
        url = API_URL + "?" + urllib.parse.urlencode({
            "lat": f"{lat:.6f}", "lng": f"{lon:.6f}",
            "rad": f"{min(radius_km, MAX_RADIUS_KM):.1f}",
            "sort": "dist", "type": "all", "apikey": self.api_key,
        })
        data = http.fetch_json(url)
        if not data.get("ok"):
            raise ProviderError(f"Tankerkönig weigerde de aanvraag: {data.get('message')}")
        return [s for raw in data.get("stations") or [] if (s := self.parse_station(raw))]

    def parse_station(self, raw: dict) -> Station | None:
        if "lat" not in raw or "lng" not in raw or "id" not in raw:
            return None

        def price(key):
            v = raw.get(key)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None

        prices: dict[str, float] = {}
        e5, e10, diesel = price("e5"), price("e10"), price("diesel")
        petrol = [p for p in ((e5, e10) if self.allow_e10 else (e5,)) if p is not None]
        if petrol:
            prices[PETROL95] = min(petrol)
        if diesel is not None:
            prices[DIESEL] = diesel
        address = " ".join(x for x in (
            f"{raw.get('street', '')} {raw.get('houseNumber', '')}".strip(),
            f"{raw.get('postCode', '')} {raw.get('place', '')}".strip()) if x)
        brand, nm = raw.get("brand") or "", raw.get("name") or ""
        name = nm if brand.lower() in nm.lower() else f"{brand} {nm}".strip()
        return Station(
            id=f"tk:{raw['id']}",
            name=name or "Onbekend station",
            lat=float(raw["lat"]), lon=float(raw["lng"]),
            source=self.name,
            address=address,
            prices=prices,
            is_open=raw.get("isOpen"),
        )
