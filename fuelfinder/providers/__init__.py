"""Register van prijsbronnen en samenvoegen van hun resultaten.

Een nieuwe grens/bron toevoegen:
  1. maak providers/<naam>.py met een `Provider`-subklasse;
  2. voeg hem toe aan `build_providers` hieronder;
  3. zet de naam in `enabled` in config.toml.
"""

from __future__ import annotations

from ..config import Config
from ..cache import FetchInfo, StationCache, fetch_cached
from ..geo import haversine_km
from ..models import Station
from .anwb import AnwbProvider
from .base import Provider, ProviderError
from .tankerkoenig import TankerkoenigProvider

DEDUPE_METERS = 75
# Leesbare namen van de bronnen (voor de interface en de export)
SOURCE_LABELS = {"anwb": "ANWB Onderweg", "tankerkoenig": "Tankerkönig"}


def build_providers(cfg: Config, names: list[str] | None = None) -> list[Provider]:
    factories = {
        "anwb": lambda: AnwbProvider(),
        "tankerkoenig": lambda: TankerkoenigProvider(cfg.tankerkoenig_key, cfg.allow_e10),
    }
    out = []
    for name in names or cfg.providers:
        if name not in factories:
            raise ValueError(f"Onbekende provider {name!r}. Beschikbaar: {', '.join(factories)}")
        out.append(factories[name]())
    return out


def _combine(infos: list[FetchInfo]) -> FetchInfo:
    """Eén herkomst voor meerdere gebieden: vers als er iets vers is opgehaald, 'stale' als
    een bron daarvoor op oude gegevens terugviel, anders cache. De leeftijd is die van het oudste."""
    origin = "stale" if any(i.origin == "stale" for i in infos) else (
        "live" if any(i.origin == "live" for i in infos) else "cache")
    errors = [i.error for i in infos if i.error]
    return FetchInfo(origin, max(i.age_s for i in infos), errors[0] if errors else "")


def collect_areas(providers: list[Provider], areas: list[tuple[float, float, float]],
                  cache: StationCache | None = None, max_age_s: float = 0.0, refresh: bool = False,
                  dropped: list | None = None
                  ) -> tuple[list[Station], dict[str, str], dict[str, FetchInfo]]:
    """Haal stations op voor een of meer cirkels (lat, lon, straal) bij alle providers.

    Een falende bron stopt de rest niet; een gebied dat mislukt terwijl andere lukken geeft een
    melding maar behoudt de rest. Een station dat in meerdere cirkels valt telt eenmaal. Staan
    twee bronnen voor hetzelfde station in de lijst (binnen 75 m), dan wint de bron die eerder
    in `providers` staat. Retourneert (stations, meldingen, herkomst per bron). Is `dropped` een
    lijst, dan komen de weggelaten dubbelen daar als (station, winnend station) in.
    """
    stations: list[Station] = []
    messages: dict[str, str] = {}
    infos: dict[str, FetchInfo] = {}
    for provider in providers:
        got: dict[str, Station] = {}
        ok_infos: list[FetchInfo] = []
        errors: list[str] = []
        for lat, lon, radius in areas:
            try:
                fetched, info = fetch_cached(provider, lat, lon, radius, cache, max_age_s, refresh)
            except Exception as e:  # netwerk, ontbrekende sleutel, gewijzigde API, ...
                errors.append(str(e))
                continue
            ok_infos.append(info)
            for s in fetched:
                got.setdefault(s.id, s)
        if not ok_infos:
            messages[provider.name] = f"mislukt: {errors[0]}"
            continue
        info = _combine(ok_infos)
        infos[provider.name] = info
        added = 0
        for s in got.values():
            twin = next((k for k in stations if haversine_km(s.lat, s.lon, k.lat, k.lon) * 1000 < DEDUPE_METERS
                         and k.source != s.source), None)
            if twin is not None:
                if dropped is not None:
                    dropped.append((s, twin))
                continue
            stations.append(s)
            added += 1
        text = f"{len(got)} stations ({added} toegevoegd), {info.describe()}"
        if errors:
            text += f"; let op: {len(errors)} van {len(areas)} gebieden mislukt ({errors[0]})"
        messages[provider.name] = text
    return stations, messages, infos


def collect_cached(providers: list[Provider], lat: float, lon: float, radius_km: float,
                   cache: StationCache | None = None, max_age_s: float = 0.0, refresh: bool = False,
                   dropped: list | None = None
                   ) -> tuple[list[Station], dict[str, str], dict[str, FetchInfo]]:
    """Zoals `collect_areas`, voor één cirkel."""
    return collect_areas(providers, [(lat, lon, radius_km)], cache, max_age_s, refresh, dropped)


def collect(providers: list[Provider], lat: float, lon: float, radius_km: float
            ) -> tuple[list[Station], dict[str, str]]:
    """Zoals `collect_cached`, maar zonder cache."""
    stations, messages, _ = collect_cached(providers, lat, lon, radius_km)
    return stations, messages


__all__ = ["SOURCE_LABELS", "Provider", "ProviderError", "build_providers", "collect", "collect_areas", "collect_cached"]
