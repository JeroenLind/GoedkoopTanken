"""Geografische hulpfuncties."""

from __future__ import annotations

import math
import threading
import time
import urllib.parse

from . import http

EARTH_RADIUS_KM = 6371.0088
DEFAULT_NOMINATIM = "https://nominatim.openstreetmap.org"

# Nominatim staat maximaal 1 aanvraag per seconde toe (openbare server). Alle aanvragen van dit
# proces gaan door deze ene slagboom. Tests kunnen de klok en het interval vervangen.
NOMINATIM_MIN_INTERVAL = 1.0
_clock = time.monotonic
_sleep = time.sleep
_gate = threading.Lock()
_last_call: float | None = None


def _nominatim_wait() -> None:
    global _last_call
    with _gate:  # wie wacht, houdt de rest tegen; zo blijft de volgorde netjes
        if _last_call is not None:
            wait = NOMINATIM_MIN_INTERVAL - (_clock() - _last_call)
            if wait > 0:
                _sleep(wait)
        _last_call = _clock()


def _is_public_nominatim(base: str) -> bool:
    return "nominatim.openstreetmap.org" in base


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Retourneert (min_lat, min_lon, max_lat, max_lon) rond een punt."""
    dlat = math.degrees(radius_km / EARTH_RADIUS_KM)
    dlon = math.degrees(radius_km / (EARTH_RADIUS_KM * math.cos(math.radians(lat))))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def geocode(address: str, base: str = DEFAULT_NOMINATIM) -> tuple[float, float, str]:
    """Zoek een adres op via OpenStreetMap Nominatim (max. 1 aanvraag per seconde toegestaan)."""
    url = base.rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": address, "format": "json", "limit": 1}
    )
    if _is_public_nominatim(base):
        _nominatim_wait()
    data = http.fetch_json(url)
    if not data:
        raise http.FetchError(f"Adres niet gevonden: {address!r}")
    hit = data[0]
    return float(hit["lat"]), float(hit["lon"]), hit.get("display_name", address)


def reverse_geocode(lat: float, lon: float, base: str = DEFAULT_NOMINATIM) -> str:
    """Zet coördinaten om in een kort adres ("Straat 1, Plaats"). Valt terug op coördinaten."""
    url = base.rstrip("/") + "/reverse?" + urllib.parse.urlencode(
        {"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": 18, "addressdetails": 1})
    if _is_public_nominatim(base):
        _nominatim_wait()
    try:
        data = http.fetch_json(url)
    except http.FetchError:
        return f"{lat:.5f}, {lon:.5f}"
    addr = data.get("address") or {}
    street = " ".join(x for x in (
        addr.get("road") or addr.get("pedestrian") or addr.get("footway") or "",
        addr.get("house_number") or "") if x)
    place = (addr.get("city") or addr.get("town") or addr.get("village")
             or addr.get("municipality") or "")
    label = ", ".join(x for x in (street, place) if x)
    return label or data.get("display_name") or f"{lat:.5f}, {lon:.5f}"


# --- routes (lijnen van punten) -------------------------------------------------------------

Point = tuple[float, float]  # (lat, lon)


def _local_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """Vlakke benadering rond (lat0, lon0): (x, y) in km. Ruim voldoende voor afstanden < 100 km."""
    kx = math.pi / 180 * EARTH_RADIUS_KM * math.cos(math.radians(lat0))
    ky = math.pi / 180 * EARTH_RADIUS_KM
    return (lon - lon0) * kx, (lat - lat0) * ky


def distance_to_polyline_km(lat: float, lon: float, line: list[Point]) -> float:
    """Kortste afstand van een punt tot een lijn (reeks punten), in km."""
    if len(line) == 1:
        return haversine_km(lat, lon, line[0][0], line[0][1])
    best = float("inf")
    prev = _local_km(lat, lon, *line[0])
    for point in line[1:]:
        cur = _local_km(lat, lon, *point)
        (ax, ay), (bx, by) = prev, cur
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
        prev = cur
    return best


def polyline_length_km(line: list[Point]) -> float:
    return sum(haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(line, line[1:]))


def sample_along(line: list[Point], step_km: float) -> list[Point]:
    """Gelijk verdeelde punten op de lijn, ten hoogste `step_km` uit elkaar (gemeten langs de
    lijn), inclusief begin- en eindpunt. Elk punt van de lijn ligt daardoor binnen `step_km / 2`
    langs de lijn van een van de punten."""
    if len(line) < 2:
        return list(line)
    lengths = [haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(line, line[1:])]
    total = sum(lengths)
    if total == 0:
        return [line[0]]
    parts = max(1, math.ceil(total / step_km - 1e-9))
    out: list[Point] = []
    seg, seg_start = 0, 0.0
    for i in range(parts + 1):
        target = total * i / parts
        while seg < len(lengths) - 1 and seg_start + lengths[seg] < target:
            seg_start += lengths[seg]
            seg += 1
        f = 0.0 if lengths[seg] == 0 else min(1.0, (target - seg_start) / lengths[seg])
        a, b = line[seg], line[seg + 1]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out
