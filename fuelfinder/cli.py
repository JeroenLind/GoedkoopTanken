"""Commandoregel: `python -m fuelfinder find | vehicle | check`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, geo, http, service, vehicle
from .cache import StationCache, age_text
from .models import FUEL_LABELS, FUELS
from .providers import build_providers, collect, enabled_map
from .routing import Router


def eur(x: float, decimals: int = 2) -> str:
    return f"{x:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cmd_find(args, cfg) -> int:
    params = service.SearchParams(
        lat=args.lat, lon=args.lon, address=args.address, plate=args.plate, fuel=args.fuel,
        consumption=args.consumption, fill=args.fill, radius=args.radius,
        providers=args.providers.split(",") if args.providers else None,
        no_routing=args.no_routing, max_extra_min=args.max_extra_min,
        max_km=args.max_km, no_time_limit=args.no_time_limit, refresh=args.refresh, no_cache=args.no_cache,
        route=bool(args.to), dest_address=args.to, corridor_km=args.corridor)
    try:
        out = service.search(cfg, params)
    except service.SearchError as e:
        sys.exit(f"{e} (zie --help, of config.toml)")
    for w in out.warnings:
        print(f"Waarschuwing: {w}", file=sys.stderr)

    veh = out.vehicle
    route = out.mode == "route"
    print(f"{'Vertrek:  ' if route else 'Thuis:    '}  {out.home_label}")
    if route:
        print(f"Bestemming:  {out.dest_label}")
        print(f"Route:       {eur(out.route_km, 1)} km, {out.route_min:.0f} min direct; "
              f"zoeken tot {eur(out.corridor_km, 0)} km naast de route")
    if veh:
        print(f"Auto:       {veh.plate} {veh.description}".rstrip())
    print(f"Brandstof:  {FUEL_LABELS[out.fuel]}")
    src = f"{veh.consumption_source}, " if veh and not out.consumption_explicit and veh.consumption_source else ""
    note = (f"opgegeven {eur(out.official_consumption, 1)}" if out.consumption_explicit
            else f"{src}officieel {eur(out.official_consumption, 1)} x {eur(out.factor, 1)}")
    print(f"Verbruik:   {eur(out.real_consumption, 1)} l/100km ({note})")
    print(f"Tanken:     {eur(out.fill_liters, 0)} liter" + ("" if route else f", zoekstraal {eur(out.radius_km, 0)} km") + "\n")
    for name, msg in out.provider_messages.items():
        print(f"  bron {name}: {msg}")
    if out.notice:
        print(f"\n{out.notice} Draai `python -m fuelfinder check` om de bronnen te testen.")
        return 1

    results = out.results
    if out.max_km is not None:
        print(f"\nMaximale afstand: stations verder dan {eur(out.max_km, 0)} km rijden vanaf het vertrek "
              f"zijn weggelaten ({len(out.too_far)})")
    if out.max_extra_min is not None:
        what = "omweg" if route else "extra rijtijd t.o.v. het dichtstbijzijnde station"
        print(f"\nTijdlimiet: maximaal {eur(out.max_extra_min, 0)} min {what} "
              f"({out.hidden_by_time_limit} stations weggelaten)")

    print()
    header = (f"{'#':>2}  {'Station':<30} {'Prijs':>6} {'Tank':>7} {'Extra km' if route else 'Retour':>9} "
              f"{'Omweg' if route else 'Tijd':>7} {'Omrit':>6} {'Totaal':>7} "
              + ("" if route else f"{'Extra tijd':>10} ") + f"{'Besparing':>9}")
    print(header)
    print("-" * len(header))

    def row(i, r):
        name = (r.station.name[:29] + "…") if len(r.station.name) > 30 else r.station.name
        km = f"{eur(r.km_round_trip, 1)}{'~' if r.estimated else ' '}"
        mins = f"{r.min_round_trip} min"
        extra = "-" if r.is_baseline else f"{r.extra_min_vs_baseline:+d} min"
        tag = ("  <- minste omweg" if route else "  <- dichtstbij") if r.is_baseline else ""
        extra_col = "" if route else f"{extra:>10} "
        print(f"{i:>2}  {name:<30} {eur(r.price, 3):>6} {eur(r.fill_cost):>7} {km:>7}km {mins:>7} "
              f"{eur(r.detour_cost):>6} {eur(r.total):>7} {extra_col}{eur(r.saving_vs_baseline):>9}{tag}")
        if args.verbose:
            print(f"      {r.station.address}  [{r.station.source}]")

    shown = results[: args.top or cfg.max_results]
    for i, r in enumerate(shown, 1):
        row(i, r)
    baseline = out.baseline
    if baseline is not None and baseline not in shown:
        print("  ...")
        row(results.index(baseline) + 1, baseline)
    if route:
        print(f"\nPrijs = EUR/liter. Tank = {eur(out.fill_liters, 0)} liter tanken. Extra km/Omweg = extra afstand en "
              "tijd t.o.v. de directe route.\nOmrit = brandstofkosten van die omweg. Totaal = Tank + Omrit. "
              "Besparing = Totaal van het station met de kleinste omweg min dit Totaal.")
    else:
        print(f"\nPrijs = EUR/liter. Tank = {eur(out.fill_liters, 0)} liter tanken. Retour/Tijd = heen en terug naar huis. "
              "Omrit = brandstofkosten van die rit.\nTotaal = Tank + Omrit. "
              "Extra tijd = Tijd min de Tijd van het dichtstbijzijnde station. "
              "Besparing = Totaal van het dichtstbijzijnde station min dit Totaal.")
    if out.any_estimated:
        print("~ = geschatte afstand en tijd (route niet beschikbaar; 1,3 x hemelsbreed, 50 km/u).")
    for line in out.attributions:
        print(line)
    return 0


def cmd_stations(args, cfg) -> int:
    """Diagnose: toon de dichtstbijzijnde stations met hun ruwe prijzen (geen routering)."""
    try:
        lat, lon, label = service.resolve_home(cfg, args.lat, args.lon, args.address)
    except service.SearchError as e:
        sys.exit(str(e))
    names = args.providers.split(",") if args.providers else None
    providers = build_providers(cfg, names)
    stations, messages = collect(providers, lat, lon, args.radius or cfg.radius_km, enabled=enabled_map(cfg, names))
    print(f"Thuis: {label}")
    for name, msg in messages.items():
        print(f"  bron {name}: {msg}")
    by_fuel = {f: sum(1 for s in stations if f in s.prices) for f in FUELS}
    print("Stations per brandstof met prijs: "
          + ", ".join(f"{FUEL_LABELS[f]} {n}" for f, n in by_fuel.items()) + f" (totaal {len(stations)})")
    nearest = sorted(stations, key=lambda s: geo.haversine_km(lat, lon, s.lat, s.lon))
    print(f"\n{'km':>5}  {'Station':<26} {'Adres':<42} Prijzen")
    for s in nearest[: args.n]:
        km = geo.haversine_km(lat, lon, s.lat, s.lon)
        prices = " ".join(f"{f}={eur(p, 3)}" for f, p in s.prices.items()) or "GEEN PRIJS"
        print(f"{eur(km, 1):>5}  {s.name[:25]:<26} {s.address[:41]:<42} {prices}")
    return 0


def cmd_vehicle(args, cfg) -> int:
    veh, rows = vehicle.lookup(args.plate or cfg.plate or "")
    if args.raw:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"Kenteken:  {veh.plate}  {veh.description}")
    print(f"Brandstof: {FUEL_LABELS.get(veh.fuel, 'onbekend / niet ondersteund')}")
    if veh.l_per_100km:
        print(f"Verbruik:  {eur(veh.l_per_100km, 1)} l/100km ({veh.consumption_source}), "
              f"praktijk ca. {eur(veh.l_per_100km * cfg.real_world_factor, 1)}")
    else:
        print("Verbruik:  niet gevonden bij de RDW. Gebruik --consumption bij `find`.")
    return 0


def cmd_cache(args, cfg) -> int:
    cache = StationCache(cfg.cache_path())
    if args.action == "clear":
        print(f"{cache.clear()} cachebestand(en) verwijderd uit {cache.dir}")
        return 0
    info = cache.info()
    print(f"Map: {info['directory']}  (cache {'aan' if cfg.cache_enabled else 'UIT'}, "
          f"maximale leeftijd {eur(cfg.cache_max_age_hours, 1)} uur)")
    if not info["entries"]:
        print("Leeg.")
    for e in info["entries"]:
        print(f"  {e['provider']:<13} {e['stations']:>4} stations, straal {eur(e['radius_km'], 1)} km, "
              f"{age_text(e['age_s'])} oud")
    return 0


def cmd_web(args, cfg) -> int:
    from . import web
    config_path = args.config or "config.toml"
    if args.data_dir:  # als add-on: instellingen en cache in één map die bewaard blijft
        Path(args.data_dir).mkdir(parents=True, exist_ok=True)
        config_path = str(Path(args.data_dir) / "config.toml")
    web.serve(config_path, args.port, not args.no_browser and not args.ingress,
              host=args.host, ingress=args.ingress)
    return 0


def cmd_check(args, cfg) -> int:
    """Test alle externe bronnen en laat zien wat ze teruggeven."""
    lat, lon = (cfg.home_lat, cfg.home_lon) if cfg.home_lat is not None else (51.9244, 6.5776)
    ok = True

    def report(name, fn):
        nonlocal ok
        try:
            print(f"[ OK ] {name}: {fn()}")
        except Exception as e:
            ok = False
            print(f"[FAIL] {name}: {e}")

    def rdw():
        # De RDW laat lege velden weg uit een antwoord, dus één willekeurige regel zegt niets
        # over de dataset. De kolomlijst staat in de metadata van de dataset zelf.
        meta = http.fetch_json("https://opendata.rdw.nl/api/views/8ys7-d773.json")
        cols = sorted(c.get("fieldName", "") for c in meta.get("columns", []))
        usable = [c for c in cols if "verbruik" in c and "gecombineerd" in c]
        msg = f"{len(cols)} kolommen: {', '.join(cols)}"
        if not usable:
            raise RuntimeError(msg + " | GEEN verbruikskolom in deze dataset")
        msg += f" | verbruik: {usable}"
        plate = cfg.plate
        if plate:
            veh, _ = vehicle.lookup(plate)
            found = f"{veh.l_per_100km} l/100km ({veh.consumption_source})" if veh.l_per_100km else "geen verbruik"
            msg += f" | {plate}: {veh.fuel}, {found}"
        return msg

    def anwb():
        p = build_providers(cfg, ["anwb"])[0]
        stations = p.fetch(lat, lon, 8)
        priced = sum(1 for s in stations if s.prices)
        return (f"{len(stations)} stations, {priced} met prijs; "
                f"brandstoftypen gezien: {sorted(p.fuel_types_seen) or 'geen'}")

    def tk():
        p = build_providers(cfg, ["tankerkoenig"])[0]
        stations = p.fetch(lat, lon, 8)
        return f"{len(stations)} stations, {sum(1 for s in stations if s.prices)} met prijs"

    def osrm():
        r = Router(cfg.osrm_url).distances((lat, lon), [(lat + 0.05, lon + 0.05)])[0]
        if r.estimated:
            raise RuntimeError("OSRM onbereikbaar; afstanden worden geschat (1,3 x hemelsbreed)")
        return (f"{r.km_out:.1f} km / {r.min_out:.0f} min heen, "
                f"{r.km_back:.1f} km / {r.min_back:.0f} min terug")

    report("RDW kenteken-data", rdw)
    report("ANWB Onderweg", anwb)
    report("Tankerkönig", tk)
    report("OSRM routering", osrm)
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fuelfinder", description=__doc__)
    parser.add_argument("--config", help="pad naar config.toml (standaard: ./config.toml)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="zoek het goedkoopste station inclusief omrit")
    f.add_argument("--plate", help="kenteken, bv. AB-123-C")
    f.add_argument("--fuel", choices=FUELS)
    f.add_argument("--consumption", type=float, help="verbruik in l/100km (overschrijft kenteken)")
    f.add_argument("--fill", type=float, help="liters die je tankt")
    f.add_argument("--radius", type=float, help="zoekstraal in km")
    f.add_argument("--address", help="thuisadres (overschrijft config)")
    f.add_argument("--lat", type=float)
    f.add_argument("--lon", type=float)
    f.add_argument("--providers", help="kommagescheiden, bv. anwb,tankerkoenig")
    f.add_argument("--to", metavar="ADRES", help="zoek langs de route naar deze bestemming ('werk' = het "
                   "werkadres uit config.toml); het vertrek is --address/--lat/--lon of het thuisadres")
    f.add_argument("--corridor", type=float, metavar="KM",
                   help="alleen met --to: hoe ver naast de route gezocht wordt (standaard afgeleid van de tijdlimiet)")
    f.add_argument("--max-km", type=float, metavar="KM",
                   help="alleen met --to: maximale rijafstand van het vertrek naar het station (bijna lege tank)")
    f.add_argument("--top", type=int, help="aantal resultaten")
    f.add_argument("--max-extra-min", type=float, metavar="MIN",
                   help="maximaal aantal minuten extra rijtijd t.o.v. het dichtstbijzijnde station "
                        "(standaard 30, of de waarde uit config.toml)")
    f.add_argument("--no-time-limit", action="store_true", help="geen tijdlimiet")
    f.add_argument("--refresh", action="store_true", help="prijzen opnieuw ophalen, cache negeren")
    f.add_argument("--no-cache", action="store_true", help="cache niet gebruiken voor deze zoekopdracht")
    f.add_argument("--no-routing", action="store_true", help="schat afstanden, geen OSRM")
    f.add_argument("-v", "--verbose", action="store_true", help="toon adres en bron")

    st = sub.add_parser("stations", help="diagnose: dichtstbijzijnde stations met ruwe prijzen")
    st.add_argument("-n", type=int, default=15, help="aantal stations")
    st.add_argument("--radius", type=float)
    st.add_argument("--address")
    st.add_argument("--lat", type=float)
    st.add_argument("--lon", type=float)
    st.add_argument("--providers")

    v = sub.add_parser("vehicle", help="toon wat de RDW over een kenteken weet")
    v.add_argument("plate", nargs="?")
    v.add_argument("--raw", action="store_true", help="toon het ruwe RDW-antwoord")

    sub.add_parser("check", help="test alle externe bronnen")

    c = sub.add_parser("cache", help="bekijk of wis de lokale cache")
    c.add_argument("action", choices=["info", "clear"], nargs="?", default="info")

    w = sub.add_parser("web", help="start de lokale webinterface")
    w.add_argument("--port", type=int, default=8080)
    w.add_argument("--host", default="127.0.0.1",
                   help="luisteradres (standaard alleen deze computer; de add-on gebruikt 0.0.0.0)")
    w.add_argument("--data-dir", help="map voor instellingen en cache (voor gebruik als add-on)")
    w.add_argument("--ingress", action="store_true",
                   help="Home Assistant Ingress: alleen verkeer van de Supervisor toestaan")
    w.add_argument("--no-browser", action="store_true", help="open de browser niet automatisch")

    args = parser.parse_args(argv)
    try:
        cfg = config.load(args.config)
        return {"find": cmd_find, "stations": cmd_stations, "cache": cmd_cache, "web": cmd_web, "vehicle": cmd_vehicle, "check": cmd_check}[args.cmd](args, cfg)
    except (http.FetchError, ValueError, FileNotFoundError) as e:
        print(f"Fout: {e}", file=sys.stderr)
        return 2
