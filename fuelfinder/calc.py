"""De rekenkern: welk station is, alles meegerekend, het goedkoopst?

Model per station:
    vulkosten   = liters x prijs
    omrit       = (km heen + km terug) x verbruik/100 x prijs
    totaal      = vulkosten + omrit

De besparing wordt uitgedrukt ten opzichte van het dichtstbijzijnde station (op rijafstand),
omdat dat is wat je zou doen zonder te zoeken. De brandstof voor de rit wordt gewaardeerd
tegen de prijs van het station zelf; het verschil met je eigen tankinhoud is verwaarloosbaar.
"""

from __future__ import annotations

from .geo import distance_to_polyline_km, haversine_km
from .models import Result, Station
from .routing import Router

# Hoeveel stations we daadwerkelijk laten routeren (de rest valt eerder af).
DEFAULT_CANDIDATES = 40
ALWAYS_INCLUDE_NEAREST = 3
ALONG_CANDIDATES = 60  # langs een route zijn er meer serieuze kandidaten


def _build_results(candidates: list[Station], routes, fuel: str, fill_liters: float,
                   consumption_l_per_100km: float) -> list[Result]:
    """Kosten per station uit de gerouteerde afstanden; markeert de referentie (`is_baseline`)
    en rekent besparing en extra tijd daartegen uit. Gesorteerd op totaal, laagste eerst."""
    results: list[Result] = []
    for s, route in zip(candidates, routes):
        km_out, km_back = route.km_out, route.km_back
        price = s.prices[fuel]
        # Afronden gebeurt hier, zodat alles wat getoond wordt onderling klopt:
        # totaal = tank + omrit, besparing = verschil van totalen, extra tijd = verschil van minuten.
        fill_cost = round(fill_liters * price, 2)
        detour_cost = round((km_out + km_back) * consumption_l_per_100km / 100 * price, 2)
        results.append(Result(s, price, km_out, km_back, route.estimated, fill_cost, detour_cost,
                              round(fill_cost + detour_cost, 2),
                              round(route.min_out + route.min_back)))

    baseline = min(results, key=lambda r: r.km_out + r.km_back)
    baseline.is_baseline = True
    for r in results:
        r.saving_vs_baseline = round(baseline.total - r.total, 2)
        r.extra_min_vs_baseline = r.min_round_trip - baseline.min_round_trip
    return sorted(results, key=lambda r: r.total)


def rank(
    stations: list[Station],
    home: tuple[float, float],
    fuel: str,
    fill_liters: float,
    consumption_l_per_100km: float,
    router: Router,
    max_candidates: int = DEFAULT_CANDIDATES,
) -> list[Result]:
    """Sorteer stations op totale kosten (laagste eerst). Stations zonder prijs vallen af."""
    priced = [s for s in stations if fuel in s.prices and s.is_open is not False]
    if not priced:
        return []

    def air_km(s: Station) -> float:
        return haversine_km(home[0], home[1], s.lat, s.lon)

    # Voorselectie op basis van hemelsbrede afstand (ondergrens van de echte kosten)
    def lower_bound(s: Station) -> float:
        p = s.prices[fuel]
        return fill_liters * p + 2 * air_km(s) * consumption_l_per_100km / 100 * p

    by_bound = sorted(priced, key=lower_bound)[:max_candidates]
    nearest = sorted(priced, key=air_km)[:ALWAYS_INCLUDE_NEAREST]
    candidates = list({s.id: s for s in by_bound + nearest}.values())

    routes = router.distances(home, [(s.lat, s.lon) for s in candidates])
    return _build_results(candidates, routes, fuel, fill_liters, consumption_l_per_100km)


def rank_along(
    stations: list[Station],
    start: tuple[float, float],
    end: tuple[float, float],
    line: list[tuple[float, float]],
    corridor_km: float,
    fuel: str,
    fill_liters: float,
    consumption_l_per_100km: float,
    router: Router,
    max_candidates: int = ALONG_CANDIDATES,
) -> list[Result]:
    """Zoals `rank`, maar voor een rit van `start` naar `end` met tanken onderweg.

    De omrit is het verschil met de directe route: (start -> station -> eind) min (start -> eind).
    `km_out` en `min_out` van elk resultaat zijn dus de extra kilometers en minuten. De referentie
    (`is_baseline`) is het station met de kleinste omweg. Alleen stations binnen `corridor_km`
    hemelsbreed van de route doen mee.
    """
    priced = [s for s in stations if fuel in s.prices and s.is_open is not False]
    off = {s.id: distance_to_polyline_km(s.lat, s.lon, line) for s in priced}
    priced = [s for s in priced if off[s.id] <= corridor_km]
    if not priced:
        return []

    # Voorselectie: een zijstap van d km hemelsbreed kost grofweg 2 x d km extra rijden.
    def estimate(s: Station) -> float:
        p = s.prices[fuel]
        return fill_liters * p + 2 * off[s.id] * consumption_l_per_100km / 100 * p

    by_bound = sorted(priced, key=estimate)[:max_candidates]
    closest = sorted(priced, key=lambda s: off[s.id])[:ALWAYS_INCLUDE_NEAREST]
    candidates = list({s.id: s for s in by_bound + closest}.values())

    routes = router.detours(start, end, [(s.lat, s.lon) for s in candidates])
    return _build_results(candidates, routes, fuel, fill_liters, consumption_l_per_100km)


def within_time_limit(results: list[Result], max_extra_min: float | None,
                      absolute: bool = False) -> list[Result]:
    """Houd stations over die hooguit `max_extra_min` extra rijtijd kosten. None = geen limiet.

    Standaard is dat t.o.v. het dichtstbijzijnde station (zoeken rondom een locatie). Met
    `absolute=True` telt de extra rijtijd zelf (zoeken langs een route: de omweg).
    De referentie blijft altijd staan.
    """
    if max_extra_min is None:
        return results
    key = (lambda r: r.min_round_trip) if absolute else (lambda r: r.extra_min_vs_baseline)
    return [r for r in results if r.is_baseline or key(r) <= max_extra_min]
