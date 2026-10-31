"""Lokale cache voor stationsgegevens (locaties en prijzen).

Waarom per gebied en niet per zoekopdracht: je positie verschilt bij elke berekening een
beetje (zeker bij een apparaatlocatie). Daarom halen we bij een misser een iets groter gebied
op rond een rasterpunt en slaan dat op. Een volgende zoekopdracht is een treffer als haar
cirkel volledig binnen een nog verse opgeslagen cirkel past. De stations worden daarna op
jouw werkelijke positie en straal gefilterd.

Bij een onbereikbare bron wordt een oudere opslag (tot 7 dagen) gebruikt, mits die het gebied
dekt, met een duidelijke melding.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .geo import haversine_km
from .models import Station

SCHEMA = 1
GRID_DEG = 0.05              # ca. 5,5 km in noord-zuid; het opgehaalde gebied krijgt daarom extra marge
MARGIN_KM = 4.0              # >= afstand van rasterpunt tot de verste hoek van een rastercel
KEEP_STALE_SECONDS = 7 * 24 * 3600
MAX_ENTRIES_PER_PROVIDER = 12
# De 'open'-vlag van een station is momentopname-informatie. Bij oudere cachegegevens negeren
# we hem: een station dat 's middags open was kan nu dicht zijn en andersom.
OPEN_FLAG_MAX_AGE_S = 30 * 60

_lock = threading.RLock()


@dataclass
class Entry:
    center: tuple[float, float]
    radius_km: float
    fetched_at: float
    stations: list[Station]


@dataclass
class FetchInfo:
    origin: str                  # "live" | "cache" | "stale"
    age_s: float = 0.0           # hoe oud de gebruikte gegevens zijn
    error: str = ""              # bij "stale": waarom live ophalen mislukte

    def describe(self) -> str:
        if self.origin == "cache":
            return f"uit cache, {age_text(self.age_s)} oud"
        if self.origin == "stale":
            return f"bron niet bereikbaar ({self.error}); cache van {age_text(self.age_s)} geleden gebruikt"
        return "vers opgehaald"


def age_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "minder dan 1 minuut"
    if minutes < 90:
        return f"{minutes} min"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.0f} uur"
    return f"{hours / 24:.0f} dagen"


def _to_dict(e: Entry) -> dict:
    return {"center": list(e.center), "radius_km": e.radius_km, "fetched_at": e.fetched_at,
            "stations": [asdict(s) for s in e.stations]}


def _from_dict(d: dict) -> Entry:
    return Entry((float(d["center"][0]), float(d["center"][1])), float(d["radius_km"]),
                 float(d["fetched_at"]), [Station(**s) for s in d["stations"]])


class StationCache:
    def __init__(self, directory: str | os.PathLike, clock=time.time):
        self.dir = Path(directory)
        self.clock = clock

    def _path(self, provider: str) -> Path:
        return self.dir / f"{provider}.json"

    def load(self, provider: str) -> list[Entry]:
        """Alle opslagen van een bron. Een kapot of verouderd bestand telt als leeg."""
        try:
            raw = json.loads(self._path(provider).read_text(encoding="utf-8"))
            if raw.get("schema") != SCHEMA:
                return []
            return [_from_dict(d) for d in raw["entries"]]
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return []

    def _save(self, provider: str, entries: list[Entry]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(provider)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"schema": SCHEMA, "entries": [_to_dict(e) for e in entries]}),
                       encoding="utf-8")
        os.replace(tmp, path)  # atomisch

    def lookup(self, provider: str, lat: float, lon: float, radius_km: float,
               max_age_s: float) -> Entry | None:
        """Nieuwste opslag die de hele zoekcirkel dekt en niet ouder is dan `max_age_s`."""
        now = self.clock()
        with _lock:
            covering = [e for e in self.load(provider)
                        if now - e.fetched_at <= max_age_s
                        and haversine_km(e.center[0], e.center[1], lat, lon) + radius_km <= e.radius_km + 1e-6]
        return max(covering, key=lambda e: e.fetched_at, default=None)

    def store(self, provider: str, entry: Entry) -> None:
        now = self.clock()
        with _lock:
            keep = [e for e in self.load(provider)
                    if now - e.fetched_at <= KEEP_STALE_SECONDS
                    # een oudere opslag die volledig in de nieuwe past is overbodig
                    and not (e.fetched_at < entry.fetched_at and haversine_km(
                        e.center[0], e.center[1], entry.center[0], entry.center[1]) + e.radius_km
                        <= entry.radius_km + 1e-6)]
            keep.append(entry)
            keep.sort(key=lambda e: e.fetched_at, reverse=True)
            self._save(provider, keep[:MAX_ENTRIES_PER_PROVIDER])

    def clear(self) -> int:
        """Verwijder alle opslagen; geeft het aantal verwijderde bestanden."""
        count = 0
        with _lock:
            for path in self.dir.glob("*.json"):
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    pass
        return count

    def info(self) -> dict:
        now = self.clock()
        entries = []
        with _lock:
            for path in sorted(self.dir.glob("*.json")) if self.dir.exists() else []:
                provider = path.stem
                for e in self.load(provider):
                    entries.append({"provider": provider, "stations": len(e.stations),
                                    "radius_km": round(e.radius_km, 1), "age_s": now - e.fetched_at})
        return {"directory": str(self.dir), "areas": len(entries),
                "newest_age_s": min((e["age_s"] for e in entries), default=None), "entries": entries}


def plan_fetch(lat: float, lon: float, radius_km: float, max_radius_km: float | None):
    """Welk gebied we ophalen bij een misser: (midden_lat, midden_lon, straal)."""
    c_lat = round(lat / GRID_DEG) * GRID_DEG
    c_lon = round(lon / GRID_DEG) * GRID_DEG
    wanted = radius_km + MARGIN_KM
    if max_radius_km is not None and wanted > max_radius_km:
        # Dit gebied zou groter zijn dan de bron toestaat; een afgekapt gebied dekt de hoeken
        # van de zoekcirkel niet. Dan liever exact deze zoekopdracht opslaan.
        return lat, lon, radius_km
    return c_lat, c_lon, wanted


def fetch_cached(provider, lat: float, lon: float, radius_km: float,
                 cache: StationCache | None, max_age_s: float, refresh: bool = False
                 ) -> tuple[list[Station], FetchInfo]:
    """Stations binnen `radius_km` van (lat, lon), uit de cache als die vers genoeg is."""
    cap = getattr(provider, "max_radius_km", None)
    radius = min(radius_km, cap) if cap else radius_km   # wat de bron maximaal kan leveren

    if cache is None:
        return provider.fetch(lat, lon, radius), FetchInfo("live")

    entry = None if refresh else cache.lookup(provider.name, lat, lon, radius, max_age_s)
    info = FetchInfo("cache")
    if entry is None:
        c_lat, c_lon, c_radius = plan_fetch(lat, lon, radius, cap)
        try:
            fetched = provider.fetch(c_lat, c_lon, c_radius)
        except Exception as e:
            # Terugval: een oudere opslag die dit gebied dekt (tot 7 dagen), met melding.
            entry = cache.lookup(provider.name, lat, lon, radius, KEEP_STALE_SECONDS)
            if entry is None:
                raise
            info = FetchInfo("stale", error=str(e)[:120])
        else:
            entry = Entry((c_lat, c_lon), c_radius, cache.clock(), fetched)
            try:
                cache.store(provider.name, entry)
            except OSError:
                pass  # schijf vol of niet schrijfbaar: werken zonder cache is prima
            info = FetchInfo("live")

    info.age_s = max(0.0, cache.clock() - entry.fetched_at)
    stations = [s for s in entry.stations if haversine_km(lat, lon, s.lat, s.lon) <= radius]
    if info.origin != "live" and info.age_s > OPEN_FLAG_MAX_AGE_S:
        stations = [replace(s, is_open=None) for s in stations]
    return stations, info
