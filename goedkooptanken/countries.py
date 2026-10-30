"""Landen die de app kent, en de bepaling in welk land een station ligt.

Een land toevoegen:
  1. zet het hieronder in COUNTRIES (ISO-code en Nederlandse naam);
  2. genereer de grenzen opnieuw met scripts/maak_landgrenzen.py (zie daar);
  3. laat een bron het land dekken via `countries` in zijn Provider-klasse.
De instellingen en de interface passen zich vanzelf aan; er is geen andere code te wijzigen.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

# ISO-landcode -> Nederlandse naam. De volgorde is die in de interface.
COUNTRIES = {"NL": "Nederland", "DE": "Duitsland", "BE": "België"}

BORDERS_FILE = Path(__file__).parent / "data" / "landgrenzen.json"
NEAR_BORDER_KM = 0.5  # een punt net buiten een grens (kaartonnauwkeurigheid) hoort bij het dichtstbijzijnde land


@lru_cache(maxsize=1)
def _borders() -> dict:
    """code -> lijst polygonen; elke polygoon is [buitenring, gaten...], een ring is [[lon, lat], ...]."""
    data = json.loads(BORDERS_FILE.read_text(encoding="utf-8"))
    out = {}
    for code, polys in data.items():
        out[code] = [(_bbox(p[0]), p) for p in polys]
    return out


def _bbox(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _in_ring(lon, lat, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon, lat, poly) -> bool:
    return _in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, hole) for hole in poly[1:])


def _km_to_ring(lon, lat, ring) -> float:
    """Kortste afstand (km) van een punt tot de rand van een ring, lokaal vlak benaderd."""
    kx = 111.32 * math.cos(math.radians(lat))
    ky = 110.57
    best = float("inf")
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        ax, ay, bx, by = (x1 - lon) * kx, (y1 - lat) * ky, (x2 - lon) * kx, (y2 - lat) * ky
        dx, dy = bx - ax, by - ay
        n = dx * dx + dy * dy
        t = 0.0 if n == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / n))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


@lru_cache(maxsize=4096)
def country_of(lat: float, lon: float) -> str | None:
    """Landcode (uit COUNTRIES) waarin het punt ligt, of None als het in geen bekend land ligt."""
    borders = _borders()
    for code in COUNTRIES:
        for (x0, y0, x1, y1), poly in borders.get(code, []):
            if x0 <= lon <= x1 and y0 <= lat <= y1 and _in_polygon(lon, lat, poly):
                return code
    best, best_code = NEAR_BORDER_KM, None
    for code in COUNTRIES:
        for (x0, y0, x1, y1), poly in borders.get(code, []):
            if x0 - 0.02 <= lon <= x1 + 0.02 and y0 - 0.02 <= lat <= y1 + 0.02:
                d = _km_to_ring(lon, lat, poly[0])
                if d < best:
                    best, best_code = d, code
    return best_code
