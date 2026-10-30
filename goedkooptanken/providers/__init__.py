"""Register van prijsbronnen en samenvoegen van hun resultaten.

Een nieuwe bron toevoegen:
  1. maak providers/<naam>.py met een `Provider`-subklasse (naam, label, landen, ...);
  2. voeg de klasse toe aan `PROVIDER_CLASSES` hieronder.
De instellingen en de interface tonen de bron dan vanzelf bij elk land dat hij dekt.
Een nieuw land staat in `countries.COUNTRIES`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..cache import FetchInfo, StationCache, fetch_cached
from ..countries import COUNTRIES, country_of
from ..geo import haversine_km
from ..models import Station
from .anwb import AnwbProvider
from .base import Provider, ProviderError
from .tankerkoenig import TankerkoenigProvider

if TYPE_CHECKING:
    from ..config import Config

DEDUPE_METERS = 75
# Alle bronnen die de app kent. De volgorde is die in de interface.
PROVIDER_CLASSES: dict[str, type[Provider]] = {c.name: c for c in (AnwbProvider, TankerkoenigProvider)}
# Leesbare namen van de bronnen (voor de interface en de export)
SOURCE_LABELS = {name: c.label for name, c in PROVIDER_CLASSES.items()}


def default_countries() -> dict[str, list[str]]:
    """Standaard per land: alle bronnen die het land dekken, officiële bronnen eerst (hoogste prioriteit)."""
    out = {}
    for code in COUNTRIES:
        covering = [c for c in PROVIDER_CLASSES.values() if code in c.countries]
        covering.sort(key=lambda c: not c.official)   # stabiel: de rest houdt de volgorde van het register
        out[code] = [c.name for c in covering]
    return out


def clean_countries(raw, strict: bool = True) -> dict[str, list[str]]:
    """Valideer de keuze per land: {landcode: [bronnen in volgorde van prioriteit]}.

    Strikt (een aanvraag van de interface): een fout geeft een ValueError. Niet strikt (een config.toml die
    met de hand is aangepast of door een oudere versie is gemaakt): wat niet klopt wordt genegeerd.
    Een land dat ontbreekt krijgt de standaard.
    """
    out = default_countries()
    if raw is None:
        return out
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("Landen: verwacht een lijst per land")
        return out
    for code, names in raw.items():
        if code not in COUNTRIES:
            if strict:
                raise ValueError(f"Landen: onbekend land {code!r}")
            continue
        if not isinstance(names, list):
            if strict:
                raise ValueError(f"{COUNTRIES[code]}: verwacht een lijst met bronnen")
            continue
        clean: list[str] = []
        for n in names:
            cls = PROVIDER_CLASSES.get(n)
            if cls is None or code not in cls.countries:
                if strict:
                    why = "onbekende bron" if cls is None else f"{cls.label} dekt dit land niet"
                    raise ValueError(f"{COUNTRIES[code]}: {why} ({n})")
                continue
            if n in clean:
                if strict:
                    raise ValueError(f"{COUNTRIES[code]}: {cls.label} staat er twee keer in")
                continue
            clean.append(n)
        out[code] = clean
    return out


def catalog() -> dict:
    """Bronnen en landen voor de interface. Een nieuwe bron of een nieuw land verschijnt hier vanzelf."""
    return {
        "sources": [{"name": c.name, "label": c.label, "countries": list(c.countries), "official": c.official,
                     "needs_key": c.needs_key, "note": c.note, "attribution": c.attribution}
                    for c in PROVIDER_CLASSES.values()],
        "countries": [{"code": code, "name": name,
                       "sources": [c.name for c in PROVIDER_CLASSES.values() if code in c.countries]}
                      for code, name in COUNTRIES.items()],
    }


def enabled_map(cfg: "Config", names: list[str] | None = None) -> dict[str, list[str]]:
    """Welke bronnen per land gebruikt worden, in volgorde van prioriteit. Met `names` (bijv. --providers
    in de CLI) geldt precies die lijst, in die volgorde, voor elk land dat de bron dekt."""
    if not names:
        return {code: list(v) for code, v in cfg.countries.items()}
    unknown = [n for n in names if n not in PROVIDER_CLASSES]
    if unknown:
        raise ValueError(f"Onbekende bron {unknown[0]!r}. Beschikbaar: {', '.join(PROVIDER_CLASSES)}")
    return {code: [n for n in names if code in PROVIDER_CLASSES[n].countries] for code in COUNTRIES}


def build_providers(cfg: "Config", names: list[str] | None = None) -> list[Provider]:
    """De bronnen die ergens aan staan (of precies `names`), in volgorde van eerste gebruik."""
    if names:
        wanted = list(dict.fromkeys(names))
    else:
        wanted = list(dict.fromkeys(n for v in enabled_map(cfg).values() for n in v))
    out = []
    for name in wanted:
        if name not in PROVIDER_CLASSES:
            raise ValueError(f"Onbekende bron {name!r}. Beschikbaar: {', '.join(PROVIDER_CLASSES)}")
        out.append(PROVIDER_CLASSES[name].from_config(cfg))
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
                  dropped: list | None = None, enabled: dict[str, list[str]] | None = None
                  ) -> tuple[list[Station], dict[str, str], dict[str, FetchInfo]]:
    """Haal stations op voor een of meer cirkels (lat, lon, straal) bij alle providers.

    Een falende bron stopt de rest niet; een gebied dat mislukt terwijl andere lukken geeft een
    melding maar behoudt de rest. Een station dat in meerdere cirkels valt telt eenmaal.

    `enabled` zegt per land welke bronnen gebruikt mogen worden, in volgorde van prioriteit. Een station
    telt alleen mee als zijn bron voor het land waarin het ligt aan staat. Staan twee bronnen voor
    hetzelfde station in de lijst (binnen 75 m), dan wint de bron met de hoogste prioriteit in dat land.
    Zonder `enabled` geldt geen landfilter en wint de bron die eerder in `providers` staat.
    Retourneert (stations, meldingen, herkomst per bron). Is `dropped` een lijst, dan komen de weggelaten
    dubbelen daar als (station, winnend station) in.
    """
    messages: dict[str, str] = {}
    infos: dict[str, FetchInfo] = {}
    fetched_by: dict[str, dict[str, Station]] = {}
    errors_by: dict[str, list[str]] = {}
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
        infos[provider.name] = _combine(ok_infos)
        fetched_by[provider.name] = got
        errors_by[provider.name] = errors

    # Welke stations komen in aanmerking, en met welke prioriteit?
    order = {p.name: i for i, p in enumerate(providers)}
    candidates: list[tuple[int, int, Station]] = []
    outside: dict[str, int] = {}
    for name, got in fetched_by.items():
        for s in got.values():
            if enabled is None:
                candidates.append((order[name], order[name], s))
                continue
            wanted = enabled.get(country_of(s.lat, s.lon) or "", [])
            if name not in wanted:
                outside[name] = outside.get(name, 0) + 1
                continue
            candidates.append((wanted.index(name), order[name], s))
    candidates.sort(key=lambda c: c[:2])   # stabiel: binnen een bron blijft de volgorde van ophalen

    stations: list[Station] = []
    added: dict[str, int] = {}
    for _, _, s in candidates:
        twin = next((k for k in stations if haversine_km(s.lat, s.lon, k.lat, k.lon) * 1000 < DEDUPE_METERS
                     and k.source != s.source), None)
        if twin is not None:
            if dropped is not None:
                dropped.append((s, twin))
            continue
        stations.append(s)
        added[s.source] = added.get(s.source, 0) + 1

    for name, got in fetched_by.items():
        text = f"{len(got)} stations ({added.get(name, 0)} toegevoegd), {infos[name].describe()}"
        if outside.get(name):
            text += f"; {outside[name]} buiten de landen waarvoor deze bron aan staat"
        errors = errors_by[name]
        if errors:
            text += f"; let op: {len(errors)} van {len(areas)} gebieden mislukt ({errors[0]})"
        messages[name] = text
    return stations, messages, infos


def collect_cached(providers: list[Provider], lat: float, lon: float, radius_km: float,
                   cache: StationCache | None = None, max_age_s: float = 0.0, refresh: bool = False,
                   dropped: list | None = None, enabled: dict[str, list[str]] | None = None
                   ) -> tuple[list[Station], dict[str, str], dict[str, FetchInfo]]:
    """Zoals `collect_areas`, voor één cirkel."""
    return collect_areas(providers, [(lat, lon, radius_km)], cache, max_age_s, refresh, dropped, enabled)


def collect(providers: list[Provider], lat: float, lon: float, radius_km: float,
            enabled: dict[str, list[str]] | None = None) -> tuple[list[Station], dict[str, str]]:
    """Zoals `collect_cached`, maar zonder cache."""
    stations, messages, _ = collect_cached(providers, lat, lon, radius_km, enabled=enabled)
    return stations, messages


__all__ = ["PROVIDER_CLASSES", "SOURCE_LABELS", "Provider", "ProviderError", "build_providers", "catalog",
           "clean_countries", "collect", "collect_areas", "collect_cached", "default_countries", "enabled_map"]
