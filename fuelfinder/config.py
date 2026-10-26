"""Configuratie: laden uit config.toml, omzetten van/naar een eenvoudige dict (voor de
webinterface) en opslaan. Python 3.11+ heeft tomllib ingebouwd om te lezen; schrijven doen
we zelf, het schema is klein genoeg."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .models import FUELS

KNOWN_PROVIDERS = ("tankerkoenig", "anwb")
DEFAULT_OSRM = "https://router.project-osrm.org"
DEFAULT_NOMINATIM = "https://nominatim.openstreetmap.org"


@dataclass
class Config:
    home_lat: float | None = None
    home_lon: float | None = None
    home_address: str | None = None
    # Vaste adressen (thuis/werk/vrij te kiezen) als bestemming voor zoeken langs een route:
    # [{"name": "Werk", "address": "...", "lat": 51.2 of None, "lon": 6.1 of None}]
    places: list = field(default_factory=list)
    plate: str | None = None
    fuel: str | None = None  # overschrijft de brandstof uit het kenteken
    consumption: float | None = None  # l/100km officieel; overschrijft het kenteken
    real_world_factor: float = 1.2  # praktijkverbruik = officieel x factor
    fill_liters: float = 40.0
    radius_km: float = 20.0
    max_results: int = 10
    max_extra_min: float | None = 30.0  # None = geen limiet
    providers: list[str] = field(default_factory=lambda: ["tankerkoenig", "anwb"])
    tankerkoenig_key: str | None = None  # in gebruik: omgevingsvariabele wint van het bestand
    tankerkoenig_key_file: str | None = None  # wat er in config.toml staat
    allow_e10: bool = True
    osrm_url: str = DEFAULT_OSRM
    use_routing: bool = True
    nominatim_url: str = DEFAULT_NOMINATIM
    ha_tracker: str | None = None  # device_tracker-entiteit in Home Assistant (alleen als add-on)
    cache_enabled: bool = True
    cache_max_age_hours: float = 12.0
    cache_dir: str = "cache"  # relatief aan de map van config.toml
    base_dir: str = "."       # map van config.toml (wordt bij laden ingevuld)

    def cache_path(self) -> Path:
        p = Path(self.cache_dir)
        return p if p.is_absolute() else Path(self.base_dir) / p


def load(path: str | None = None) -> Config:
    """Laad config.toml uit `path`, of uit de huidige map als die bestaat."""
    candidate = Path(path) if path else Path("config.toml")
    raw: dict = {}
    if candidate.exists():
        with open(candidate, "rb") as fh:
            raw = tomllib.load(fh)
    elif path:
        raise FileNotFoundError(f"Configbestand niet gevonden: {path}")

    home = raw.get("home", {})
    places = _places_from_toml(raw)
    vehicle = raw.get("vehicle", {})
    search = raw.get("search", {})
    prov = raw.get("providers", {})
    routing = raw.get("routing", {})
    cache = raw.get("cache", {})
    tk = prov.get("tankerkoenig", {})
    key_file = tk.get("api_key") or None

    return Config(
        home_lat=home.get("lat"),
        home_lon=home.get("lon"),
        home_address=home.get("address"),
        places=places,
        plate=vehicle.get("plate"),
        fuel=vehicle.get("fuel"),
        consumption=vehicle.get("consumption_l_per_100km"),
        real_world_factor=vehicle.get("real_world_factor", 1.2),
        fill_liters=search.get("fill_liters", 40.0),
        radius_km=search.get("radius_km", 20.0),
        max_results=search.get("max_results", 10),
        max_extra_min=search.get("max_extra_min", 30.0) or None,  # 0 = geen limiet
        providers=prov.get("enabled", ["tankerkoenig", "anwb"]),
        tankerkoenig_key=os.environ.get("TANKERKOENIG_API_KEY") or key_file,
        tankerkoenig_key_file=key_file,
        allow_e10=tk.get("allow_e10", True),
        osrm_url=routing.get("osrm_url", DEFAULT_OSRM),
        use_routing=routing.get("enabled", True),
        nominatim_url=raw.get("geocoding", {}).get("nominatim_url", DEFAULT_NOMINATIM),
        ha_tracker=raw.get("ha", {}).get("tracker") or None,
        cache_enabled=cache.get("enabled", True),
        cache_max_age_hours=cache.get("max_age_hours", 12.0),
        cache_dir=cache.get("dir", "cache"),
        base_dir=str(candidate.resolve().parent),
    )


# --- dict-vorm voor de webinterface -------------------------------------------------------

def key_source(cfg: Config) -> str:
    if os.environ.get("TANKERKOENIG_API_KEY"):
        return "env"
    return "config" if cfg.tankerkoenig_key_file else "none"


def to_dict(cfg: Config) -> dict:
    """Instellingen als dict. De API-key zelf staat er bewust niet in."""
    return {
        "home": {"lat": cfg.home_lat, "lon": cfg.home_lon, "address": cfg.home_address or ""},
        "places": [dict(p) for p in cfg.places],
        "vehicle": {"plate": cfg.plate or "", "fuel": cfg.fuel or "",
                    "consumption_l_per_100km": cfg.consumption,
                    "real_world_factor": cfg.real_world_factor},
        "search": {"fill_liters": cfg.fill_liters, "radius_km": cfg.radius_km,
                   "max_results": cfg.max_results, "max_extra_min": cfg.max_extra_min or 0},
        "providers": {"enabled": list(cfg.providers), "allow_e10": cfg.allow_e10,
                      "tankerkoenig_key_source": key_source(cfg)},
        "routing": {"enabled": cfg.use_routing, "osrm_url": cfg.osrm_url,
                    "nominatim_url": cfg.nominatim_url},
        "ha": {"tracker": cfg.ha_tracker or ""},
        "cache": {"enabled": cfg.cache_enabled, "max_age_hours": cfg.cache_max_age_hours},
    }


MAX_PLACES = 20


def clean_places(items, keep=None, drop=None) -> list:
    """Valideer de lijst vaste adressen. `keep`/`drop`: oude werkadres-vorm samenvoegen met bestaande lijst."""
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("Vaste adressen: lijst verwacht")
    out = [p for p in (keep or []) if drop is None or p["name"].lower() != drop.lower()]
    for i, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"Vast adres {i}: ongeldige invoer")
        name = str(raw.get("name") or "").strip()
        address = str(raw.get("address") or "").strip()
        label = f"Vast adres '{name}'" if name else f"Vast adres {i}"
        lat = _num(raw.get("lat"), f"{label}: breedtegraad", -90, 90, optional=True)
        lon = _num(raw.get("lon"), f"{label}: lengtegraad", -180, 180, optional=True)
        if (lat is None) != (lon is None):
            raise ValueError(f"{label}: vul zowel breedte- als lengtegraad in, of geen van beide")
        if not name and not address and lat is None:
            continue  # lege rij in het formulier
        if not name:
            raise ValueError(f"Vast adres {i}: geef het een naam")
        if len(name) > 40:
            raise ValueError(f"{label}: naam is te lang (maximaal 40 tekens)")
        if not address and lat is None:
            raise ValueError(f"{label}: vul een adres of coördinaten in")
        if any(p["name"].lower() == name.lower() for p in out):
            raise ValueError(f"Vast adres '{name}' staat er twee keer in")
        out.append({"name": name, "address": address, "lat": lat, "lon": lon})
    if len(out) > MAX_PLACES:
        raise ValueError(f"Vaste adressen: maximaal {MAX_PLACES}")
    return out


def _places_from_toml(raw: dict) -> list:
    items = list(raw.get("places") or [])
    work = raw.get("work") or {}  # oude configbestanden: [work] wordt het vaste adres "Werk"
    if (work.get("lat") is not None or work.get("address")) and not any(
            str(p.get("name", "")).lower() == "werk" for p in items):
        items.insert(0, {"name": "Werk", **work})
    return clean_places(items)


def find_place(cfg, name: str):
    for p in cfg.places:
        if p["name"].lower() == (name or "").strip().lower():
            return p
    return None


def _num(value, name, lo, hi, *, optional=False, integer=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError(f"{name}: waarde ontbreekt")
    try:
        number = float(str(value).replace(",", "."))
    except ValueError:
        raise ValueError(f"{name}: '{value}' is geen getal") from None
    if not lo <= number <= hi:
        raise ValueError(f"{name}: moet tussen {lo:g} en {hi:g} liggen")
    return int(number) if integer else number


def _url(value: str, name: str) -> str:
    value = str(value).strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"{name}: moet beginnen met http:// of https://")
    return value


def from_dict(d: dict, base: Config | None = None) -> Config:
    """Bouw een Config uit de dict-vorm, met validatie. Een lege API-key laat de bestaande staan."""
    base = base or Config()
    home, veh = d.get("home", {}), d.get("vehicle", {})
    srch, prov, rout = d.get("search", {}), d.get("providers", {}), d.get("routing", {})
    cch = d.get("cache", {})
    ha = d.get("ha", {})

    lat = _num(home.get("lat"), "Breedtegraad", -90, 90, optional=True)
    lon = _num(home.get("lon"), "Lengtegraad", -180, 180, optional=True)
    if (lat is None) != (lon is None):
        raise ValueError("Thuislocatie: vul zowel breedte- als lengtegraad in, of geen van beide")

    if "places" in d:
        places = clean_places(d.get("places"))
    else:  # een aanvraag zonder adressen laat de opgeslagen adressen staan
        places = base.places
    if "work" in d:  # oude vorm (één werkadres): wordt het vaste adres "Werk"
        w = d.get("work") or {}
        has = bool(str(w.get("lat") or "").strip() or str(w.get("address") or "").strip())
        places = clean_places([{"name": "Werk", **w}] if has else [], keep=places, drop="Werk")

    fuel = (veh.get("fuel") or "").strip() or None
    if fuel and fuel not in FUELS:
        raise ValueError(f"Brandstof: onbekende waarde '{fuel}'")

    enabled = prov.get("enabled", base.providers)
    if not isinstance(enabled, list) or not enabled:
        raise ValueError("Bronnen: kies minstens één bron")
    unknown = [p for p in enabled if p not in KNOWN_PROVIDERS]
    if unknown:
        raise ValueError(f"Bronnen: onbekend: {', '.join(unknown)}")

    new_key = (prov.get("tankerkoenig_api_key") or "").strip()
    cfg = replace(
        base,
        home_lat=lat, home_lon=lon,
        home_address=(home.get("address") or "").strip() or None,
        places=places,
        plate=(veh.get("plate") or "").strip() or None,
        fuel=fuel,
        consumption=_num(veh.get("consumption_l_per_100km"), "Verbruik", 0.5, 40, optional=True),
        real_world_factor=_num(veh.get("real_world_factor", base.real_world_factor),
                               "Praktijkfactor", 0.5, 3),
        fill_liters=_num(srch.get("fill_liters", base.fill_liters), "Liters tanken", 1, 500),
        radius_km=_num(srch.get("radius_km", base.radius_km), "Zoekstraal", 1, 100),
        max_results=_num(srch.get("max_results", base.max_results), "Aantal resultaten", 1, 100,
                         integer=True),
        max_extra_min=_num(srch.get("max_extra_min", base.max_extra_min or 0),
                           "Maximale extra tijd", 0, 600) or None,
        providers=list(enabled),
        allow_e10=bool(prov.get("allow_e10", base.allow_e10)),
        use_routing=bool(rout.get("enabled", base.use_routing)),
        osrm_url=(rout.get("osrm_url") or DEFAULT_OSRM).strip().rstrip("/"),
        nominatim_url=_url(rout.get("nominatim_url") or base.nominatim_url, "Nominatim-server"),
        ha_tracker=((ha.get("tracker") or "").strip() or None) if "ha" in d else base.ha_tracker,
        cache_enabled=bool(cch.get("enabled", base.cache_enabled)),
        cache_max_age_hours=_num(cch.get("max_age_hours", base.cache_max_age_hours),
                                 "Cache: maximale leeftijd (uur)", 0.1, 168),
    )
    if new_key:
        cfg.tankerkoenig_key = new_key
        cfg.tankerkoenig_key_file = new_key
    return cfg


# --- opslaan ------------------------------------------------------------------------------

def _s(value: str) -> str:  # TOML-tekenreeks (JSON-escaping is een geldige subset)
    return json.dumps(value)


def to_toml(cfg: Config) -> str:
    lines = ["# Opgeslagen door fuelfinder. Handmatig aanpassen mag; opmerkingen blijven niet",
             "# behouden zodra je opnieuw via de webinterface opslaat.", "", "[home]"]
    if cfg.home_lat is not None and cfg.home_lon is not None:
        lines += [f"lat = {cfg.home_lat!r}", f"lon = {cfg.home_lon!r}"]
    if cfg.home_address:
        lines.append(f"address = {_s(cfg.home_address)}")
    for p in cfg.places:
        lines += ["", "[[places]]", f"name = {_s(p['name'])}"]
        if p.get("lat") is not None and p.get("lon") is not None:
            lines += [f"lat = {p['lat']!r}", f"lon = {p['lon']!r}"]
        if p.get("address"):
            lines.append(f"address = {_s(p['address'])}")
    lines += ["", "[vehicle]"]
    if cfg.plate:
        lines.append(f"plate = {_s(cfg.plate)}")
    if cfg.fuel:
        lines.append(f"fuel = {_s(cfg.fuel)}")
    if cfg.consumption:
        lines.append(f"consumption_l_per_100km = {cfg.consumption!r}")
    lines.append(f"real_world_factor = {cfg.real_world_factor!r}")
    lines += ["", "[search]", f"fill_liters = {cfg.fill_liters!r}", f"radius_km = {cfg.radius_km!r}",
              f"max_results = {int(cfg.max_results)}", f"max_extra_min = {(cfg.max_extra_min or 0)!r}",
              "", "[providers]", "enabled = [" + ", ".join(_s(p) for p in cfg.providers) + "]",
              "", "[providers.tankerkoenig]", f"api_key = {_s(cfg.tankerkoenig_key_file or '')}",
              f"allow_e10 = {str(cfg.allow_e10).lower()}",
              "", "[routing]", f"enabled = {str(cfg.use_routing).lower()}",
              f"osrm_url = {_s(cfg.osrm_url)}",
              "", "[geocoding]", f"nominatim_url = {_s(cfg.nominatim_url)}",
              "", "[cache]", f"enabled = {str(cfg.cache_enabled).lower()}",
              f"max_age_hours = {cfg.cache_max_age_hours!r}"]
    if cfg.cache_dir != "cache":
        lines.append(f"dir = {_s(cfg.cache_dir)}")
    if cfg.ha_tracker:
        lines += ["", "[ha]", f"tracker = {_s(cfg.ha_tracker)}"]
    lines.append("")
    return "\n".join(lines)


def save(cfg: Config, path: str | None = None) -> Path:
    target = Path(path) if path else Path("config.toml")
    tmp = target.with_suffix(".toml.tmp")
    tmp.write_text(to_toml(cfg), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # bevat de API-key; niet leesbaar voor anderen
    except OSError:
        pass  # niet ondersteund (bijv. Windows)
    os.replace(tmp, target)  # atomisch: nooit een half geschreven bestand
    return target
