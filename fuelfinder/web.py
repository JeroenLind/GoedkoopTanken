"""Lokale webinterface: instellingen aanpassen en een berekening starten.

Alleen standaardbibliotheek. De server luistert uitsluitend op 127.0.0.1 (jouw eigen computer),
want hij bewaart je API-key en heeft geen inlog. Extra beveiliging tegen andere websites in je
browser: de Host-header moet kloppen (tegen DNS-rebinding) en schrijvende aanvragen moeten
JSON zijn met een Origin die bij deze server hoort (tegen cross-site aanvragen).
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, geo, ha, service, vehicle
from .cache import StationCache
from . import http as fhttp
from .models import FUEL_LABELS
from .providers import SOURCE_LABELS
from .routing import Router

STATIC = Path(__file__).parent / "static"
# Meegeleverde bestanden (Leaflet voor de kaart). Alleen wat hier bij het starten in de map staat
# kan worden opgevraagd, op exact deze namen: er is geen pad om uit de map te ontsnappen.
CONTENT_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".png": "image/png", ".txt": "text/plain; charset=utf-8"}
VENDOR = {p.relative_to(STATIC).as_posix(): p for p in (STATIC / "vendor").rglob("*")
          if p.is_file() and p.suffix in CONTENT_TYPES}
MAX_BODY = 100_000


def serialize(out: service.SearchOutput, max_results: int) -> dict:
    """SearchOutput als JSON-vriendelijke dict. Toont de top N plus altijd het dichtstbijzijnde."""
    def row(rank: int, r) -> dict:
        s = r.station
        # Bestemming op coördinaten (nauwkeuriger dan adrestekst). Het vertrekpunt laten we aan de
        # navigatie-app over: die gebruikt je huidige locatie.
        nav = {
            "google": f"https://www.google.com/maps/dir/?api=1&travelmode=driving&destination={s.lat},{s.lon}",
            "apple": f"https://maps.apple.com/?daddr={s.lat},{s.lon}&dirflg=d",
            "waze": f"https://waze.com/ul?ll={s.lat},{s.lon}&navigate=yes",
        }
        if out.mode == "route" and out.dest:
            # Eerst tanken, dan door naar de bestemming. Waze kent geen tussenstop: alleen het station.
            d_lat, d_lon = out.dest
            nav["google"] = ("https://www.google.com/maps/dir/?api=1&travelmode=driving"
                             f"&destination={d_lat},{d_lon}&waypoints={s.lat},{s.lon}")
            nav["apple"] = f"https://maps.apple.com/?daddr={s.lat},{s.lon}+to:{d_lat},{d_lon}&dirflg=d"
        info = out.sources.get(s.source)
        return {
            "rank": rank, "name": s.name, "address": s.address, "source": s.source, "id": s.id,
            "source_label": SOURCE_LABELS.get(s.source, s.source),
            "source_origin": info.origin if info else "live",
            "source_age_min": round(info.age_s / 60) if info else 0,
            "price": r.price, "fill_cost": r.fill_cost, "detour_cost": r.detour_cost,
            "total": r.total, "km_round_trip": round(r.km_round_trip, 1),
            "km_out": round(r.km_out, 2), "km_back": round(r.km_back, 2), "km_exact": round(r.km_round_trip, 2),
            "detour_liters": round(r.km_round_trip * out.real_consumption / 100, 2),
            "km_to_station": round(r.km_to_station, 1) if r.km_to_station is not None else None,
            "minutes": r.min_round_trip, "extra_min": r.extra_min_vs_baseline,
            "saving": r.saving_vs_baseline, "is_baseline": r.is_baseline,
            "estimated": r.estimated, "lat": s.lat, "lon": s.lon, "nav": nav,
        }

    shown = [row(i, r) for i, r in enumerate(out.results[:max_results], 1)]
    baseline = out.baseline
    if baseline is not None and not any(x["is_baseline"] for x in shown):
        shown.append(row(out.results.index(baseline) + 1, baseline))
    shown_ranks = {x["rank"] for x in shown}
    # De overige doorgerekende stations: alleen voor als stipjes op de kaart.
    others = [row(i, r) for i, r in enumerate(out.results, 1) if i not in shown_ranks]
    veh = out.vehicle
    return {
        "mode": out.mode,
        "home": {"lat": out.home[0], "lon": out.home[1], "label": out.home_label},
        "dest": ({"lat": out.dest[0], "lon": out.dest[1], "label": out.dest_label} if out.dest else None),
        "route": ({"km": round(out.route_km, 1), "min": round(out.route_min),
                   "line": [[round(a, 5), round(b, 5)] for a, b in out.route_line]} if out.mode == "route" else None),
        "others": others,
        "corridor_km": out.corridor_km if out.mode == "route" else None,
        "max_km": out.max_km, "too_far": len(out.too_far),
        "vehicle": ({"plate": veh.plate, "description": veh.description} if veh else None),
        "fuel": out.fuel, "fuel_label": FUEL_LABELS[out.fuel],
        "consumption": {"official": out.official_consumption, "real": out.real_consumption,
                        "factor": out.factor, "explicit": out.consumption_explicit,
                        "source": veh.consumption_source if veh and not out.consumption_explicit else ""},
        "fill_liters": out.fill_liters, "radius_km": out.radius_km,
        "max_extra_min": out.max_extra_min, "hidden_by_time_limit": out.hidden_by_time_limit,
        "total_found": len(out.results), "results": shown,
        "provider_messages": out.provider_messages, "attributions": out.attributions,
        "warnings": out.warnings, "notice": out.notice, "any_estimated": out.any_estimated,
        "sources": {n: {"origin": i.origin, "age_min": round(i.age_s / 60)} for n, i in out.sources.items()},
    }


class App:
    """Houdt het pad van config.toml vast en voert de acties uit (los van HTTP, dus testbaar)."""

    def __init__(self, config_path: str = "config.toml"):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._last: tuple[service.SearchOutput, int] | None = None  # voor de download van alle bekeken data

    def current(self) -> config.Config:
        exists = Path(self.config_path).exists()
        cfg = config.load(self.config_path if exists else None)
        if not exists:  # de cache hoort naast het (toekomstige) configbestand te staan
            cfg.base_dir = str(Path(self.config_path).resolve().parent)
        return cfg

    def get_settings(self) -> dict:
        d = config.to_dict(self.current())
        d["meta"] = {"config_path": str(Path(self.config_path).resolve()), "ha_available": ha.available()}
        return d

    def save_settings(self, d: dict) -> dict:
        with self._lock:
            cfg = config.from_dict(d, self.current())
            config.save(cfg, self.config_path)
        return self.get_settings()

    def search(self, body: dict) -> dict:
        cfg = config.from_dict(body.get("settings") or config.to_dict(self.current()), self.current())
        params = service.SearchParams(refresh=bool(body.get("refresh")))
        if body.get("mode") == "route":
            dest = body.get("dest") or {}
            lat = config._num(dest.get("lat"), "Bestemming: breedtegraad", -90, 90, optional=True)
            lon = config._num(dest.get("lon"), "Bestemming: lengtegraad", -180, 180, optional=True)
            if (lat is None) != (lon is None):
                raise ValueError("Bestemming: vul zowel breedte- als lengtegraad in, of geen van beide")
            params.route, params.dest_lat, params.dest_lon = True, lat, lon
            params.dest_address = str(dest.get("address") or "").strip() or None
            params.max_km = config._num(body.get("max_km"), "Maximale afstand", 0, 2000, optional=True) or None
        out = service.search(cfg, params)
        with self._lock:
            self._last = (out, cfg.max_results)
        return serialize(out, cfg.max_results)

    def export(self) -> dict:
        with self._lock:
            last = self._last
        if last is None:
            raise ValueError("Er is nog geen berekening gedaan, dus er is niets om te downloaden.")
        return service.export_data(*last)

    def via(self, a: str, s: str, b: str) -> dict:
        """De route van a via station s naar b (voor het tonen van de omweg op de kaart)."""
        def point(text: str) -> tuple[float, float]:
            try:
                lat, lon = (float(x) for x in text.split(","))
            except ValueError:
                raise ValueError("Ongeldige coördinaten") from None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Coördinaten liggen buiten het bereik")
            return lat, lon
        cfg = self.current()
        path = Router(cfg.osrm_url, enabled=cfg.use_routing).path([point(a), point(s), point(b)], overview="full")
        return {"line": [[round(la, 5), round(lo, 5)] for la, lo in path.line],
                "km": round(path.km, 1), "min": round(path.minutes), "estimated": path.estimated}

    def cache_info(self) -> dict:
        info = StationCache(self.current().cache_path()).info()
        return {"areas": info["areas"], "newest_age_min": None if info["newest_age_s"] is None
                else round(info["newest_age_s"] / 60), "directory": info["directory"]}

    def cache_clear(self) -> dict:
        cleared = StationCache(self.current().cache_path()).clear()
        return {"cleared": cleared}

    def geocode(self, q: str) -> dict:
        if not q.strip():
            raise ValueError("Geen adres opgegeven")
        lat, lon, label = geo.geocode(q, self.current().nominatim_url)
        return {"lat": round(lat, 6), "lon": round(lon, 6), "label": label}

    def reverse(self, lat: str, lon: str) -> dict:
        try:
            la, lo = float(lat), float(lon)
        except ValueError:
            raise ValueError("Ongeldige coördinaten") from None
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            raise ValueError("Coördinaten liggen buiten het bereik")
        return {"label": geo.reverse_geocode(la, lo, self.current().nominatim_url)}

    def test_source(self, body: dict) -> dict:
        key = ((body.get("providers") or {}).get("tankerkoenig_api_key") or "")
        return service.test_source(self.current(), str(body.get("source") or ""), key)

    def ha_trackers(self) -> dict:
        try:
            return {"trackers": ha.trackers()}
        except ha.HAError as e:
            raise ValueError(str(e)) from None

    def ha_location(self) -> dict:
        try:
            lat, lon, acc = ha.location(self.current().ha_tracker or "")
        except ha.HAError as e:
            raise ValueError(str(e)) from None
        return {"lat": lat, "lon": lon, "accuracy_m": acc,
                "label": geo.reverse_geocode(lat, lon, self.current().nominatim_url)}

    def lookup_vehicle(self, plate: str) -> dict:
        veh, _ = vehicle.lookup(plate)
        return {"plate": veh.plate, "description": veh.description, "fuel": veh.fuel or "",
                "fuel_label": FUEL_LABELS.get(veh.fuel, "onbekend"),
                "l_per_100km": veh.l_per_100km, "source": veh.consumption_source}


# De Supervisor van Home Assistant zet verkeer uit Ingress door vanaf dit adres.
INGRESS_PROXY_IPS = {"172.30.32.2", "127.0.0.1"}


def make_handler(app: App, port: int, ingress: bool = False):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "fuelfinder"

        # -- helpers
        def _send(self, status: int, payload, content_type="application/json; charset=utf-8", headers=None):
            body = payload if isinstance(payload, bytes) else json.dumps(
                payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "origin")   # kaarttegels van OpenStreetMap eisen een Referer
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str):
            self._send(status, {"error": message})

        def _host_ok(self) -> bool:
            if ingress:  # Host en Origin zijn die van Home Assistant; de bron van het verkeer telt
                return self.client_address[0] in INGRESS_PROXY_IPS
            return self.headers.get("Host", "") in allowed_hosts

        def _read_json(self) -> dict | None:
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._error(415, "Alleen application/json toegestaan")
                return None
            origin = self.headers.get("Origin")
            if origin and not ingress and origin.split("://", 1)[-1] not in allowed_hosts:
                self._error(403, "Aanvraag van een andere herkomst geweigerd")
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self._error(413, "Aanvraag te groot of ongeldig")
                return None
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._error(400, "Ongeldige JSON")
                return None
            if not isinstance(data, dict):
                self._error(400, "JSON-object verwacht")
                return None
            return data

        def _run(self, fn):
            try:
                self._send(200, fn())
            except (service.SearchError, ValueError) as e:
                self._error(400, str(e))
            except fhttp.FetchError as e:
                self._error(502, str(e))
            except Exception:  # onverwacht: log volledig in de terminal, toon kort in de browser
                traceback.print_exc()
                self._error(500, "Onverwachte fout; zie het terminalvenster voor details")

        # -- routes
        def do_GET(self):
            if not self._host_ok():
                return self._error(403, "Ongeldige Host-header")
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path.lstrip("/") in VENDOR:
                file = VENDOR[url.path.lstrip("/")]
                return self._send(200, file.read_bytes(), CONTENT_TYPES[file.suffix])
            if url.path == "/api/settings":
                return self._run(app.get_settings)
            if url.path == "/api/cache":
                return self._run(app.cache_info)
            if url.path == "/api/export":
                try:
                    data = app.export()
                except ValueError as e:
                    return self._error(404, str(e))
                name = "fuelfinder-data-" + data["generated_at"][:16].replace(":", "").replace("-", "").replace("T", "-") + ".json"
                return self._send(200, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"),
                                  headers={"Content-Disposition": f'attachment; filename="{name}"'})
            if url.path == "/api/ha/trackers":
                return self._run(app.ha_trackers)
            if url.path == "/api/ha/location":
                return self._run(app.ha_location)
            if url.path == "/api/via":
                return self._run(lambda: app.via(query.get("a", [""])[0], query.get("s", [""])[0], query.get("b", [""])[0]))
            if url.path == "/api/geocode":
                return self._run(lambda: app.geocode(query.get("q", [""])[0]))
            if url.path == "/api/reverse":
                return self._run(lambda: app.reverse(query.get("lat", [""])[0], query.get("lon", [""])[0]))
            if url.path == "/api/vehicle":
                return self._run(lambda: app.lookup_vehicle(query.get("plate", [""])[0]))
            self._error(404, "Niet gevonden")

        def do_POST(self):
            if not self._host_ok():
                return self._error(403, "Ongeldige Host-header")
            path = urllib.parse.urlparse(self.path).path
            if path not in ("/api/settings", "/api/search", "/api/cache/clear", "/api/test-source"):
                return self._error(404, "Niet gevonden")
            data = self._read_json()
            if data is None:
                return
            if path == "/api/settings":
                return self._run(lambda: app.save_settings(data))
            if path == "/api/cache/clear":
                return self._run(app.cache_clear)
            if path == "/api/test-source":
                return self._run(lambda: app.test_source(data))
            return self._run(lambda: app.search(data))

        def log_message(self, fmt, *args):  # korte log in de terminal
            sys.stderr.write(f"[web] {self.address_string()} {fmt % args}\n")

    return Handler


def serve(config_path: str = "config.toml", port: int = 8080, open_browser: bool = True,
          host: str = "127.0.0.1", ingress: bool = False) -> None:
    app = App(config_path)
    server = ThreadingHTTPServer((host, port), make_handler(app, port, ingress))
    url = f"http://127.0.0.1:{port}/"
    print(f"fuelfinder draait op {url}  (stoppen met Ctrl+C)")
    print(f"Instellingen worden opgeslagen in {Path(config_path).resolve()}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        server.server_close()
