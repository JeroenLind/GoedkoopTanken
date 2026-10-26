"""Rijafstanden berekenen via OSRM (OpenStreetMap-routering).

De publieke demoserver is bedoeld voor licht gebruik. Voor dit programma is dat genoeg:
twee aanvragen per zoekopdracht. Zet in de config een eigen `osrm_url` als je de limiet raakt.
"""

from __future__ import annotations

import urllib.parse

from typing import NamedTuple

from . import http
from .geo import haversine_km

DEFAULT_OSRM = "https://router.project-osrm.org"
# Rijafstand is gemiddeld ongeveer 1,3x de hemelsbrede afstand. Alleen gebruikt als terugval.
DETOUR_FACTOR = 1.3
# Gemiddelde snelheid (km/u) waarmee de reistijd wordt geschat als er geen route is.
FALLBACK_SPEED_KMH = 50.0


class RouteLine(NamedTuple):
    """De route van A naar B zelf: de lijn, de lengte en de rijtijd."""
    line: list  # [(lat, lon), ...]
    km: float
    minutes: float
    estimated: bool


class Route(NamedTuple):
    km_out: float
    km_back: float
    min_out: float
    min_back: float
    estimated: bool


def _estimate(home, point) -> Route:
    km = haversine_km(home[0], home[1], point[0], point[1]) * DETOUR_FACTOR
    minutes = km / FALLBACK_SPEED_KMH * 60
    return Route(km, km, minutes, minutes, True)


def _estimate_detour(a, b, point) -> Route:
    extra_air = (haversine_km(a[0], a[1], point[0], point[1]) + haversine_km(point[0], point[1], b[0], b[1])
                 - haversine_km(a[0], a[1], b[0], b[1]))
    km = max(0.0, extra_air) * DETOUR_FACTOR
    return Route(km, 0.0, km / FALLBACK_SPEED_KMH * 60, 0.0, True)


class Router:
    def __init__(self, base_url: str = DEFAULT_OSRM, enabled: bool = True):
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled

    def distances(
        self, home: tuple[float, float], points: list[tuple[float, float]]
    ) -> list[Route]:
        """Per punt: afstand en reistijd heen en terug. Volgorde gelijk aan `points`."""
        if not points:
            return []
        if self.enabled:
            try:
                return self._osrm(home, points)
            except (http.FetchError, KeyError, IndexError, TypeError, ValueError):
                pass  # terugval op schatting hieronder
        return [_estimate(home, p) for p in points]

    def _osrm(self, home, points):
        coords = [home] + list(points)
        coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
        base = f"{self.base_url}/table/v1/driving/{coord_str}"
        # heen: van huis naar alle punten; terug: van alle punten naar huis
        out = http.fetch_json(base + "?" + urllib.parse.urlencode(
            {"sources": 0, "annotations": "distance,duration"}))
        back = http.fetch_json(base + "?" + urllib.parse.urlencode(
            {"destinations": 0, "annotations": "distance,duration"}))
        if out.get("code") != "Ok" or back.get("code") != "Ok":
            raise ValueError("OSRM gaf geen Ok")
        dist_out, time_out = out["distances"][0][1:], out["durations"][0][1:]
        dist_back = [row[0] for row in back["distances"][1:]]
        time_back = [row[0] for row in back["durations"][1:]]
        result = []
        for i, point in enumerate(points):
            vals = (dist_out[i], dist_back[i], time_out[i], time_back[i])
            if any(v is None for v in vals):  # niet bereikbaar over de weg
                result.append(_estimate(home, point))
            else:
                result.append(Route(vals[0] / 1000.0, vals[1] / 1000.0,
                                    vals[2] / 60.0, vals[3] / 60.0, False))
        return result

    # --- zoeken langs een route ---------------------------------------------------------

    def route_line(self, a: tuple[float, float], b: tuple[float, float]) -> RouteLine:
        """De route van `a` naar `b`. Zonder routering een rechte lijn met geschatte waarden."""
        return self.path([a, b])

    def path(self, points: list[tuple[float, float]], overview: str = "simplified") -> RouteLine:
        """De route langs de opgegeven punten (bv. vertrek, station, bestemming), in die volgorde.
        Zonder routering rechte lijnen met geschatte waarden."""
        if self.enabled:
            try:
                coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
                data = http.fetch_json(
                    f"{self.base_url}/route/v1/driving/{coords}?"
                    + urllib.parse.urlencode({"overview": overview, "geometries": "geojson"}))
                if data.get("code") != "Ok":
                    raise ValueError("OSRM gaf geen Ok")
                best = data["routes"][0]
                line = [(lat, lon) for lon, lat in best["geometry"]["coordinates"]]
                if len(line) >= 2:
                    return RouteLine(line, best["distance"] / 1000.0, best["duration"] / 60.0, False)
            except (http.FetchError, KeyError, IndexError, TypeError, ValueError):
                pass
        km = sum(haversine_km(p[0], p[1], q[0], q[1]) for p, q in zip(points, points[1:])) * DETOUR_FACTOR
        return RouteLine(list(points), km, km / FALLBACK_SPEED_KMH * 60, True)

    def detours(self, a: tuple[float, float], b: tuple[float, float],
                points: list[tuple[float, float]]) -> list[Route]:
        """Per punt de omweg ten opzichte van de directe route a -> b.

        Het resultaat gebruikt `Route` zo, dat `km_out` de extra kilometers is en `min_out` de
        extra minuten (`km_back` en `min_back` zijn 0). Zo rekent de rest van het programma
        hetzelfde als bij een rit heen en terug.
        """
        if not points:
            return []
        if self.enabled:
            try:
                return self._osrm_detours(a, b, points)
            except (http.FetchError, KeyError, IndexError, TypeError, ValueError):
                pass
        return [_estimate_detour(a, b, p) for p in points]

    def _osrm_detours(self, a, b, points):
        coords = [a, b] + list(points)
        base = f"{self.base_url}/table/v1/driving/" + ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
        # a -> alles (inclusief b), en alles -> b
        out = http.fetch_json(base + "?" + urllib.parse.urlencode(
            {"sources": 0, "annotations": "distance,duration"}))
        back = http.fetch_json(base + "?" + urllib.parse.urlencode(
            {"destinations": 1, "annotations": "distance,duration"}))
        if out.get("code") != "Ok" or back.get("code") != "Ok":
            raise ValueError("OSRM gaf geen Ok")
        direct_km, direct_s = out["distances"][0][1], out["durations"][0][1]
        if direct_km is None or direct_s is None:
            raise ValueError("a en b zijn niet over de weg verbonden")
        result = []
        for i, point in enumerate(points):
            to_s = (out["distances"][0][i + 2], out["durations"][0][i + 2])
            from_s = (back["distances"][i + 2][0], back["durations"][i + 2][0])
            if None in to_s or None in from_s:
                result.append(_estimate_detour(a, b, point))
                continue
            extra_km = max(0.0, (to_s[0] + from_s[0] - direct_km) / 1000.0)
            extra_min = max(0.0, (to_s[1] + from_s[1] - direct_s) / 60.0)
            result.append(Route(extra_km, 0.0, extra_min, 0.0, False))
        return result
