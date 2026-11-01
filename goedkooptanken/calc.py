"""De rekenkern: welk station is, alles meegerekend, het goedkoopst?

Model per station:
    vulkosten   = liters x prijs
    omrit       = (km heen + km terug) x verbruik/100 x prijs
    totaal      = vulkosten + omrit

De besparing wordt uitgedrukt ten opzichte van de referentie: het goedkoopste station dat "op de
route" ligt (zoeken langs een route) of vlak bij het dichtstbijzijnde station (zoeken rondom een
locatie). Wat "op de route" is, bepaalt `NearRule`: een grens in extra km of in extra minuten. Ligt er
geen station binnen die grens, dan is de referentie het station met de kleinste omweg.

De aanrader is het station met het laagste totaal inclusief tijd: extra rijtijd x waarde van je tijd
(euro per uur) wordt bij het totaal opgeteld. Met een tijdwaarde van 0 is dat het goedkoopste station.
De brandstof voor de rit wordt gewaardeerd tegen de prijs van het station zelf; het verschil met je
eigen tankinhoud is verwaarloosbaar.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geo import distance_to_polyline_km, haversine_km
from .models import Result, Station
from .routing import Router

# Hoeveel stations we daadwerkelijk laten routeren (de rest valt eerder af).
DEFAULT_CANDIDATES = 40
ALWAYS_INCLUDE_NEAREST = 3
ALONG_CANDIDATES = 60  # langs een route zijn er meer serieuze kandidaten


@dataclass(frozen=True)
class NearRule:
    """Wanneer telt een station als "op de route" (of vlak bij het dichtstbijzijnde station)?"""
    mode: str = "distance"   # "distance": extra km, "time": extra minuten
    max_km: float = 0.5
    max_min: float = 3.0


def pick_reference(results: list[Result], rule: NearRule, absolute: bool) -> Result:
    """Het goedkoopste station dat binnen de grens van `rule` valt; zonder zo'n station het station
    met de kleinste omweg. `absolute`: de omweg is al een verschil met de route (zoeken langs een route);
    anders telt het verschil met het dichtstbijzijnde station (zoeken rondom een locatie)."""
    km0 = 0.0 if absolute else min(r.km_round_trip for r in results)
    min0 = 0 if absolute else min(r.min_round_trip for r in results)
    if rule.mode == "time":
        near = [r for r in results if r.min_round_trip - min0 <= rule.max_min]
    else:
        near = [r for r in results if r.km_round_trip - km0 <= rule.max_km + 1e-9]
    if near:
        return min(near, key=lambda r: (r.total, r.km_round_trip))
    return min(results, key=lambda r: (r.km_round_trip, r.total))


def mark_recommended(results: list[Result], time_value: float, absolute: bool) -> None:
    """Zet `time_cost`, `effective_total` en `is_recommended` (de aanrader) op de resultaten.
    De extra tijd is de omweg (langs een route) of het verschil met het snelst bereikbare station."""
    if not results:
        return
    min0 = 0 if absolute else min(r.min_round_trip for r in results)
    for r in results:
        r.time_min = r.min_round_trip - min0
        r.time_cost = round(r.time_min * max(time_value, 0.0) / 60, 2)
        r.effective_total = round(r.total + r.time_cost, 2)
        r.is_recommended = False
    min(results, key=lambda r: (r.effective_total, r.total)).is_recommended = True


def _build_results(candidates: list[Station], routes, fuel: str, fill_liters: float,
                   consumption_l_per_100km: float, rule: NearRule = NearRule(),
                   absolute: bool = False) -> list[Result]:
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
                              round(route.min_out + route.min_back), km_to_station=route.km_to))

    baseline = pick_reference(results, rule, absolute)
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
    rule: NearRule = NearRule(),
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
    return _build_results(candidates, routes, fuel, fill_liters, consumption_l_per_100km, rule, absolute=False)


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
    max_km: float | None = None,
    too_far: list | None = None,
    rule: NearRule = NearRule(),
) -> list[Result]:
    """Zoals `rank`, maar voor een rit van `start` naar `end` met tanken onderweg.

    De omrit is het verschil met de snelste route: (start -> station -> eind) min (start -> eind).
    `km_out` en `min_out` van elk resultaat zijn dus de extra kilometers en minuten. De referentie
    (`is_baseline`) is het goedkoopste station op de route, zie `NearRule`. Alleen stations binnen `corridor_km`
    hemelsbreed van de route doen mee.

    Met `max_km` vallen stations af waarvan de rijafstand vanaf `start` groter is (bijna lege tank);
    die komen in `too_far` te staan. Dat gebeurt vóór het bepalen van de referentie, zodat die
    altijd haalbaar is.
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
    if max_km is not None:
        reachable = [r.km_to is None or r.km_to <= max_km for r in routes]
        if too_far is not None:
            too_far.extend(s for s, ok in zip(candidates, reachable) if not ok)
        candidates = [s for s, ok in zip(candidates, reachable) if ok]
        routes = [r for r, ok in zip(routes, reachable) if ok]
        if not candidates:
            return []
    return _build_results(candidates, routes, fuel, fill_liters, consumption_l_per_100km, rule, absolute=True)


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
