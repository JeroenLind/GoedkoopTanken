"""De zoekopdracht als één functie, los van de interface.

De CLI, de webinterface (en later een app of Home Assistant) roepen allemaal `search()` aan
en krijgen een `SearchOutput` terug. Alle logica die niet met uiterlijk te maken heeft zit hier.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from . import calc, geo, http, vehicle
from .countries import COUNTRIES, country_of
from .cache import FetchInfo, StationCache, age_text
from . import config
from .config import Config
from .models import FUEL_LABELS, Result, Vehicle
from .providers import PROVIDER_CLASSES, SOURCE_LABELS, build_providers, collect_areas, collect_cached, enabled_map
from .routing import Router


# Zoeken langs een route: de stations worden opgehaald met cirkels van deze straal langs de route.
# 20 km blijft ruim onder de 25 km die Tankerkönig toestaat, ook na de marge van de cache.
ROUTE_CIRCLE_KM = 20.0
ROUTE_CIRCLE_SAFETY = 1.1   # marge voor bochten in de route
MAX_ROUTE_AREAS = 20        # dat is een route van ca. 600 km


class SearchError(Exception):
    """Een fout die de gebruiker kan oplossen (ontbrekende instelling, onbekend adres, ...)."""


@dataclass
class SearchParams:
    """Optionele overschrijvingen van de configuratie voor één zoekopdracht."""
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    plate: str | None = None
    fuel: str | None = None
    consumption: float | None = None  # l/100km
    fill: float | None = None
    radius: float | None = None
    providers: list[str] | None = None
    no_routing: bool = False
    max_extra_min: float | None = None
    max_km: float | None = None  # alleen bij een route: maximale rijafstand naar het station
    no_time_limit: bool = False
    refresh: bool = False      # cache negeren en alles opnieuw ophalen
    no_cache: bool = False     # voor deze zoekopdracht helemaal geen cache gebruiken
    # Zoeken langs een route van de locatie hierboven naar de bestemming:
    route: bool = False
    dest_lat: float | None = None
    dest_lon: float | None = None
    dest_address: str | None = None  # ook de naam van een vast adres (bijv. "werk")
    corridor_km: float | None = None  # hoe ver naast de route gezocht wordt (standaard afgeleid)


@dataclass
class SearchOutput:
    home: tuple[float, float]
    home_label: str
    vehicle: Vehicle | None
    fuel: str
    official_consumption: float
    real_consumption: float
    factor: float
    consumption_explicit: bool
    fill_liters: float
    radius_km: float
    max_extra_min: float | None
    provider_messages: dict[str, str] = field(default_factory=dict)
    results: list[Result] = field(default_factory=list)  # na tijdlimiet, gesorteerd op totaal
    hidden_by_time_limit: int = 0
    attributions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notice: str = ""  # reden waarom er geen resultaten zijn
    any_estimated: bool = False
    sources: dict[str, FetchInfo] = field(default_factory=dict)  # herkomst en leeftijd per bron
    mode: str = "around"  # "around" (rondom een locatie) of "route" (langs een route)
    dest: tuple[float, float] | None = None
    dest_label: str = ""
    route_km: float = 0.0     # lengte en rijtijd van de snelste route
    route_min: float = 0.0
    corridor_km: float = 0.0
    max_km: float | None = None   # maximale rijafstand naar het station (alleen bij een route)
    too_far: list = field(default_factory=list)  # stations die daarvoor te ver weg liggen
    # Alles wat bekeken is, voor de kaart en de export:
    stations: list = field(default_factory=list)   # alle stations na samenvoegen van de bronnen
    dropped: list = field(default_factory=list)    # (weggelaten dubbel, winnend station)
    ranked: list = field(default_factory=list)     # alle doorgerekende stations, vóór de tijdlimiet
    route_line: list = field(default_factory=list)  # [(lat, lon), ...] van de snelste route
    searched_areas: list = field(default_factory=list)  # [(lat, lon, straal_km), ...] bij de bronnen opgevraagd

    @property
    def baseline(self) -> Result | None:
        return next((r for r in self.results if r.is_baseline), None)


def resolve_home(cfg: Config, lat=None, lon=None, address=None) -> tuple[float, float, str]:
    if lat is not None and lon is not None:
        return lat, lon, f"{lat:.5f}, {lon:.5f}"
    address = address or (cfg.home_address if cfg.home_lat is None else None)
    if address:
        try:
            return geo.geocode(address, cfg.nominatim_url)
        except http.FetchError as e:
            raise SearchError(f"Adres opzoeken mislukt: {e}") from e
    if cfg.home_lat is not None and cfg.home_lon is not None:
        return cfg.home_lat, cfg.home_lon, cfg.home_address or f"{cfg.home_lat:.5f}, {cfg.home_lon:.5f}"
    raise SearchError("Geen locatie opgegeven. Vul een adres in of stel een thuisadres in.")


def resolve_destination(cfg: Config, lat=None, lon=None, address=None) -> tuple[float, float, str]:
    if lat is not None and lon is not None:
        return lat, lon, address or f"{lat:.5f}, {lon:.5f}"
    wanted = (address or "").strip()
    place = config.find_place(cfg, wanted) or (config.find_place(cfg, "werk") if wanted.lower() in ("", "work") else None)
    if place:
        if place["lat"] is not None:
            return place["lat"], place["lon"], place["address"] or place["name"]
        wanted = place["address"]
    elif not wanted:
        raise SearchError("Geen bestemming opgegeven. Vul een adres in of kies een vast adres.")
    coords = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*[,;]\s*(-?\d+(?:[.,]\d+)?)\s*", wanted)
    if coords:  # "51.19, 6.59" werkt ook zonder adres opzoeken
        lat, lon = (float(x.replace(",", ".")) for x in coords.groups())
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon, f"{lat:.5f}, {lon:.5f}"
    try:
        return geo.geocode(wanted, cfg.nominatim_url)
    except http.FetchError as e:
        raise SearchError(f"Bestemming opzoeken mislukt: {e}") from e


def default_corridor_km(max_extra_min: float | None) -> float:
    """Hoe ver naast de route we zoeken: een zijstap van d km kost zo'n 2d km rijden, dus bij
    een tijdlimiet heeft zoeken verder dan ongeveer 0,4 km per toegestane minuut geen zin."""
    if max_extra_min is None:
        return 10.0
    return min(15.0, max(3.0, 0.4 * max_extra_min))


def search(cfg: Config, params: SearchParams | None = None) -> SearchOutput:
    p = params or SearchParams()
    warnings: list[str] = []
    home_lat, home_lon, home_label = resolve_home(cfg, p.lat, p.lon, p.address)

    # Voertuig: kenteken -> brandstof en verbruik, met overrides
    plate = p.plate or cfg.plate
    veh = None
    if plate:
        try:
            veh, _ = vehicle.lookup(plate)
        except (http.FetchError, ValueError) as e:
            warnings.append(f"Kenteken opzoeken mislukt: {e}")
    fuel = p.fuel or cfg.fuel or (veh.fuel if veh else None)
    official = p.consumption or cfg.consumption or (veh.l_per_100km if veh else None)
    if fuel is None:
        raise SearchError("Brandstof onbekend. Kies een brandstof of geef een kenteken op.")
    if official is None:
        raise SearchError("Verbruik onbekend. Vul het verbruik (l/100 km) in, of gebruik een "
                          "kenteken waar de RDW het verbruik van kent.")
    explicit = bool(p.consumption or cfg.consumption)
    factor = 1.0 if explicit else cfg.real_world_factor
    real = official * factor
    fill = p.fill or cfg.fill_liters
    radius = p.radius or cfg.radius_km

    max_extra = None if p.no_time_limit else (
        p.max_extra_min if p.max_extra_min is not None else cfg.max_extra_min)
    if max_extra == 0:  # 0 = geen limiet
        max_extra = None

    dest = None
    if p.route:
        d_lat, d_lon, d_label = resolve_destination(cfg, p.dest_lat, p.dest_lon, p.dest_address)
        dest = (d_lat, d_lon, d_label)

    out = SearchOutput(
        home=(home_lat, home_lon), home_label=home_label, vehicle=veh, fuel=fuel,
        official_consumption=official, real_consumption=real, factor=factor,
        consumption_explicit=explicit, fill_liters=fill, radius_km=radius,
        max_extra_min=max_extra, warnings=warnings,
    )
    if dest:
        out.mode, out.dest, out.dest_label = "route", (dest[0], dest[1]), dest[2]
        out.max_km = p.max_km if p.max_km else None
    elif p.max_km:
        warnings.append("De maximale afstand geldt alleen bij zoeken langs een route en is genegeerd.")

    try:
        enabled = enabled_map(cfg, p.providers)
        providers = build_providers(cfg, p.providers)
    except ValueError as e:
        raise SearchError(str(e)) from e
    if not providers:
        raise SearchError("Er staat geen enkele bron aan. Zet bij de instellingen (Bronnen) in minstens één "
                          "land een bron aan.")
    cache = StationCache(cfg.cache_path()) if cfg.cache_enabled and not p.no_cache else None
    max_age_s = cfg.cache_max_age_hours * 3600
    router = Router(cfg.osrm_url, enabled=cfg.use_routing and not p.no_routing)

    if out.mode == "route":
        line, areas = _plan_route(out, router, p.corridor_km, warnings)
        out.route_line, out.searched_areas = line, areas
        stations, out.provider_messages, out.sources = collect_areas(
            providers, areas, cache=cache, max_age_s=max_age_s, refresh=p.refresh, dropped=out.dropped,
            enabled=enabled)
    else:
        out.searched_areas = [(home_lat, home_lon, radius)]
        stations, out.provider_messages, out.sources = collect_cached(
            providers, home_lat, home_lon, radius, cache=cache, max_age_s=max_age_s, refresh=p.refresh,
            dropped=out.dropped, enabled=enabled)
    warnings.extend(_countries_without_source(enabled, out.searched_areas))
    out.stations = stations
    for name, info in out.sources.items():
        if info.origin == "stale":
            warnings.append(f"Bron {name} was niet bereikbaar ({info.error}); "
                            f"gegevens van {age_text(info.age_s)} geleden gebruikt.")
    for name, msg in out.provider_messages.items():
        if "gebieden mislukt" in msg:
            warnings.append(f"Bron {name}: {msg.split('; let op: ', 1)[-1]}. Langs een deel van de route "
                            "kunnen stations ontbreken.")
    if not stations:
        out.notice = "Geen stations gevonden. Controleer de bronnen (zie meldingen hierboven)."
        return out

    if out.mode == "route":
        ranked = calc.rank_along(stations, out.home, out.dest, line, out.corridor_km, fuel, fill, real, router,
                                 max_km=out.max_km, too_far=out.too_far)
    else:
        ranked = calc.rank(stations, (home_lat, home_lon), fuel, fill, real, router)
    out.ranked = ranked
    if not ranked:
        where = f"binnen {out.corridor_km:.0f} km van de route " if out.mode == "route" else ""
        if out.too_far:
            out.notice = (f"Geen station binnen {out.max_km:g} km rijden gevonden "
                          f"({len(out.too_far)} liggen verder weg).")
            return out
        out.notice = f"Geen open stations {where}met {FUEL_LABELS[fuel]}-prijs gevonden."
        return out

    out.results = calc.within_time_limit(ranked, max_extra, absolute=out.mode == "route")
    out.hidden_by_time_limit = len(ranked) - len(out.results)
    out.any_estimated = any(r.estimated for r in out.results)
    out.attributions = [
        pr.attribution for pr in providers
        if pr.attribution and not out.provider_messages.get(pr.name, "mislukt").startswith("mislukt")
    ]
    return out


def _countries_without_source(enabled: dict[str, list[str]], areas) -> list[str]:
    """Waarschuwingen voor landen die in het zoekgebied liggen maar waar geen bron voor aan staat."""
    empty = [c for c in COUNTRIES if not enabled.get(c)]
    if not empty:
        return []
    seen: set[str] = set()
    for lat, lon, radius in areas:
        # het middelpunt en acht punten op de rand van de cirkel
        points = [(lat, lon)] + [
            (lat + radius * math.cos(a) / 110.57, lon + radius * math.sin(a) / (111.32 * math.cos(math.radians(lat))))
            for a in (i * math.pi / 4 for i in range(8))]
        seen.update(c for c in (country_of(la, lo) for la, lo in points) if c)
    return [f"Voor {COUNTRIES[c]} staat geen bron aan: stations daar worden overgeslagen."
            for c in empty if c in seen]


def _plan_route(out: SearchOutput, router: Router, corridor_override, warnings: list[str]):
    """De route A -> B bepalen en de cirkels waarmee we stations langs de route ophalen."""
    rl = router.route_line(out.home, out.dest)
    out.route_km, out.route_min = rl.km, rl.minutes
    if rl.km < 0.3:
        raise SearchError("Vertrek en bestemming liggen vrijwel op dezelfde plek. "
                          "Gebruik dan het zoeken rondom een locatie.")
    if rl.estimated:
        warnings.append("De route kon niet worden berekend (OSRM); er is een rechte lijn gebruikt. "
                        "Afstanden en tijden zijn schattingen en stations langs de werkelijke weg kunnen ontbreken.")
    out.corridor_km = corridor_override or default_corridor_km(out.max_extra_min)
    usable = ROUTE_CIRCLE_KM / ROUTE_CIRCLE_SAFETY
    if out.corridor_km >= usable - 1:
        raise SearchError(f"De zoekbreedte langs de route mag hooguit {usable - 1:.0f} km zijn.")
    step = 2 * math.sqrt(usable ** 2 - out.corridor_km ** 2)
    centers = geo.sample_along(rl.line, step)
    if len(centers) > MAX_ROUTE_AREAS:
        raise SearchError(f"Deze route is {rl.km:.0f} km; dat is te lang voor zoeken langs de route "
                          f"(maximaal ca. {MAX_ROUTE_AREAS * step:.0f} km).")
    return rl.line, [(lat, lon, ROUTE_CIRCLE_KM) for lat, lon in centers]


def _key(station) -> tuple[str, str]:
    return station.source, station.id


def export_data(out: SearchOutput, max_results: int | None = None) -> dict:
    """Alles wat deze zoekopdracht heeft bekeken, als gewone dict (voor een JSON-download).

    Per station: bron, prijzen, ligging, wat er met het station gebeurd is (`status`) en, als het is
    doorgerekend, de uitkomst. Zo is te controleren waar elk gegeven vandaan komt en waarom een
    station wel of niet in de uitkomst staat. `nr` is het nummer dat het station op het scherm
    heeft (de positie in de uitkomst); `on_screen` zegt of het in de tabel staat of alleen als
    grijs stipje op de kaart (dat laatste hangt af van `max_results`).
    """
    route = out.mode == "route"
    fuel_label = FUEL_LABELS[out.fuel]
    result_rank = {_key(r.station): i for i, r in enumerate(out.results, 1)}
    ranked = {_key(r.station): r for r in out.ranked}
    too_far = {_key(s) for s in out.too_far}
    unit = "omweg" if route else "extra rijtijd t.o.v. het dichtstbijzijnde station"

    def where(s) -> tuple[float, str]:
        if route and out.route_line:
            return geo.distance_to_polyline_km(s.lat, s.lon, out.route_line), "km_from_route"
        return geo.haversine_km(out.home[0], out.home[1], s.lat, s.lon), "km_from_start"

    rows = []
    for s in out.stations:
        dist, dist_name = where(s)
        k = _key(s)
        if out.fuel not in s.prices:
            status = f"geen {fuel_label}-prijs bij de bron"
        elif s.is_open is False:
            status = "gesloten"
        elif route and dist > out.corridor_km:
            status = f"buiten de zoekbreedte ({dist:.1f} km naast de route, maximaal {out.corridor_km:.0f})"
        elif k in too_far:
            status = f"te ver weg (meer dan {out.max_km:g} km rijden vanaf het vertrek)"
        elif k in result_rank:
            status = "getoond in de uitkomst"
        elif k in ranked:
            status = f"weggelaten door de tijdlimiet (meer dan {out.max_extra_min:g} min {unit})"
        else:
            status = "niet doorgerekend (voorselectie: op prijs en afstand niet bij de beste kandidaten)"
        nr = result_rank.get(k)
        if nr is None:
            screen = None
        elif max_results is None or nr <= max_results or (k in ranked and ranked[k].is_baseline):
            screen = "tabel en kaart"
        else:
            screen = "alleen kaart (grijs stipje)"
        row = {
            "nr": nr, "on_screen": screen,
            "source": s.source, "source_label": SOURCE_LABELS.get(s.source, s.source), "id": s.id,
            "name": s.name, "address": s.address, "lat": s.lat, "lon": s.lon,
            "prices": s.prices, "is_open": s.is_open, dist_name: round(dist, 2), "status": status,
        }
        r = ranked.get(k)
        if r is not None:
            row["result"] = {
                "rank": result_rank.get(k), "price": r.price, "fill_cost": r.fill_cost,
                "extra_km" if route else "km_round_trip": round(r.km_round_trip, 2),
                "extra_min" if route else "minutes_round_trip": r.min_round_trip,
                "extra_min_vs_nearest": None if route else r.extra_min_vs_baseline,
                "detour_cost": r.detour_cost, "total": r.total,
                "saving_vs_reference": r.saving_vs_baseline,
                "is_reference": r.is_baseline, "distance_estimated": r.estimated,
                **({"km_to_station": round(r.km_to_station, 2)} if route and r.km_to_station is not None else {}),
            }
        rows.append(row)
    for s, twin in out.dropped:
        dist, dist_name = where(s)
        rows.append({
            "nr": None, "on_screen": None,
            "source": s.source, "source_label": SOURCE_LABELS.get(s.source, s.source), "id": s.id,
            "name": s.name, "address": s.address, "lat": s.lat, "lon": s.lon, "prices": s.prices,
            "is_open": s.is_open, dist_name: round(dist, 2),
            "status": f"dubbel: {twin.name} ({SOURCE_LABELS.get(twin.source, twin.source)}) staat binnen 75 m en wint",
        })
    rows.sort(key=lambda r: (r["nr"] if r["nr"] else 10**6,
                             r.get("km_from_route", r.get("km_from_start", 0))))

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "program": "Goedkoop tanken",
        "query": {
            "mode": out.mode, "start": {"lat": out.home[0], "lon": out.home[1], "label": out.home_label},
            "destination": ({"lat": out.dest[0], "lon": out.dest[1], "label": out.dest_label} if out.dest else None),
            "fuel": out.fuel, "fill_liters": out.fill_liters,
            "consumption_l_per_100km": {"official": out.official_consumption, "used": out.real_consumption,
                                        "factor": out.factor, "explicit": out.consumption_explicit},
            "radius_km": None if route else out.radius_km,
            "corridor_km": out.corridor_km if route else None,
            "max_extra_min": out.max_extra_min,
            "max_km": out.max_km if route else None,
            "searched_areas": [{"lat": a, "lon": b, "radius_km": c} for a, b, c in out.searched_areas],
        },
        "sources": {name: {"label": SOURCE_LABELS.get(name, name), "message": msg,
                           "origin": out.sources[name].origin if name in out.sources else "failed",
                           "age_min": round(out.sources[name].age_s / 60) if name in out.sources else None}
                    for name, msg in out.provider_messages.items()},
        "warnings": out.warnings, "notice": out.notice,
        "route": ({"km": round(out.route_km, 2), "min": round(out.route_min, 1),
                   "line": [[round(a, 5), round(b, 5)] for a, b in out.route_line]} if route else None),
        "counts": {"stations_seen": len(out.stations), "duplicates_dropped": len(out.dropped),
                   "routed": len(out.ranked), "in_results": len(out.results),
                   "hidden_by_time_limit": out.hidden_by_time_limit, "too_far": len(out.too_far)},
        "stations": rows,
    }


def test_source(cfg: Config, name: str, api_key: str | None = None) -> dict:
    """Test één prijsbron: bereikbaar, sleutel geldig, levert data. Nooit de sleutel in het antwoord."""
    import time
    from .providers.base import ProviderError
    if name not in PROVIDER_CLASSES:
        raise SearchError(f"Onbekende bron '{name}'")
    key = (api_key or "").strip() or cfg.tankerkoenig_key
    cfg = replace(cfg, tankerkoenig_key=key)
    provider = build_providers(cfg, [name])[0]
    lat, lon, where = provider.test_point or (52.0, 5.0, "Nederland")
    out = {"source": name, "label": SOURCE_LABELS.get(name, name), "ok": False, "ms": None,
           "stations": 0, "priced": 0, "detail": "", "advice": ""}
    if provider.needs_key and not key:
        out["detail"] = "Geen API-key ingevuld."
        out["advice"] = "Vraag gratis een key aan op creativecommons.tankerkoenig.de en vul hem hierboven in."
        return out
    start = time.monotonic()
    try:
        with http.quick():
            stations = provider.fetch(lat, lon, 5.0)
    except (ProviderError, http.FetchError) as e:
        out["ms"] = round((time.monotonic() - start) * 1000)
        msg = str(e)
        low = msg.lower()
        out["detail"] = msg.replace(key, "***") if key else msg
        if "apikey" in low or "api-key" in low or "weigerde" in low or "http 401" in low or "http 403" in low:
            out["advice"] = "De server is bereikbaar, maar de key wordt niet geaccepteerd. Controleer de key."
        elif "timed out" in low or "time-out" in low or "timeout" in low:
            out["advice"] = "De server reageert niet op tijd. Dat is meestal tijdelijk; probeer het over een paar minuten opnieuw."
        else:
            out["advice"] = "De verbinding met de bron mislukt. Controleer je internetverbinding of probeer het later opnieuw."
        return out
    out["ms"] = round((time.monotonic() - start) * 1000)
    out["stations"] = len(stations)
    out["priced"] = sum(1 for s in stations if s.prices)
    out["ok"] = out["stations"] > 0
    if out["ok"]:
        out["detail"] = f"{out['stations']} stations bij {where}, {out['priced']} met prijs, antwoord in {out['ms']} ms."
    else:
        out["detail"] = f"Bereikbaar, maar geen stations teruggekregen bij {where}."
        out["advice"] = "De bron antwoordt wel. Probeer het later opnieuw; blijft dit zo, dan is de bron mogelijk gewijzigd."
    return out
