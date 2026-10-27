"""Tests voor config-omzetting, service en de lokale webserver (offline, met nepdata)."""

import http.client
import json
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from fuelfinder import config, service
from fuelfinder import http as fhttp
from fuelfinder import web
from test_all import FakeNet, anwb_station


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ConfigDictTests(unittest.TestCase):
    def test_roundtrip_through_toml_file(self):
        cfg = config.from_dict({
            "home": {"lat": "51,2", "lon": 6.1, "address": 'Straat "1"'},
            "vehicle": {"plate": "ab-12", "fuel": "diesel", "consumption_l_per_100km": "5,5"},
            "search": {"max_extra_min": "45"},
            "providers": {"enabled": ["anwb"], "tankerkoenig_api_key": "geheim"},
        })
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            config.save(cfg, str(path))
            with mock.patch.dict("os.environ", {}, clear=False):
                loaded = config.load(str(path))
        loaded.base_dir = cfg.base_dir  # waar het bestand stond staat niet in het bestand zelf
        self.assertEqual(loaded, cfg)
        self.assertEqual((loaded.home_lat, loaded.consumption, loaded.max_extra_min), (51.2, 5.5, 45.0))

    def test_zero_means_no_time_limit(self):
        cfg = config.from_dict({"search": {"max_extra_min": "0"}})
        self.assertIsNone(cfg.max_extra_min)

    def test_blank_key_keeps_existing_and_key_never_in_dict(self):
        base = config.Config(tankerkoenig_key="oud", tankerkoenig_key_file="oud")
        cfg = config.from_dict({"providers": {"enabled": ["anwb"], "tankerkoenig_api_key": ""}}, base)
        self.assertEqual(cfg.tankerkoenig_key_file, "oud")
        self.assertNotIn("oud", json.dumps(config.to_dict(cfg)))

    def test_validation_errors_are_readable(self):
        bad = [({"search": {"fill_liters": "abc"}}, "Liters tanken"),
               ({"search": {"radius_km": 5000}}, "Zoekstraal"),
               ({"home": {"lat": "51"}}, "Thuislocatie"),
               ({"vehicle": {"fuel": "stroom"}}, "Brandstof"),
               ({"providers": {"enabled": []}}, "Bronnen"),
               ({"providers": {"enabled": ["nepbron"]}}, "onbekend")]
        for data, fragment in bad:
            with self.assertRaises(ValueError, msg=str(data)) as cm:
                config.from_dict(data)
            self.assertIn(fragment, str(cm.exception))


class ServiceTests(unittest.TestCase):
    def test_home_label_prefers_address(self):
        cfg = config.Config(home_lat=51.9, home_lon=6.6, home_address="Mijn straat 1")
        self.assertEqual(service.resolve_home(cfg)[2], "Mijn straat 1")

    def test_no_home_is_a_search_error(self):
        with self.assertRaises(service.SearchError):
            service.search(config.Config(fuel="diesel", consumption=5))


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg_path = str(Path(cls.tmp.name) / "config.toml")
        cls.port = free_port()
        cls.app = web.App(cls.cfg_path)
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), web.make_handler(cls.app, cls.port))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.net = FakeNet()
        cls.net.anwb_stations = [anwb_station(1, 51.905, 6.60, diesel=2.05),
                                 anwb_station(2, 51.95, 6.55, diesel=1.90)]
        base = cls.net

        def fake(url, headers=None, retries=2):
            if "nominatim" in url and "/reverse" in url:
                return {"display_name": "lang adres", "address": {"road": "Teststraat", "house_number": "1", "town": "Plaats"}}
            if "nominatim" in url:
                return [{"lat": "51.9", "lon": "6.6", "display_name": "Teststraat 1, Plaats"}]
            return base(url, headers, retries)
        cls.patch = mock.patch.object(fhttp, "fetch_json", fake)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if body is not None:
            h["Content-Type"] = "application/json"
            body = json.dumps(body)
        h.update(headers or {})
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        if body is not None:
            conn.putheader("Content-Length", str(len(body.encode())))
        conn.endheaders(body.encode() if body is not None else None)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        ctype = resp.getheader("Content-Type", "")
        return resp.status, (json.loads(raw) if "json" in ctype else raw.decode(errors="replace")), resp

    SEARCH = {"settings": {
        "home": {"lat": "51.9", "lon": "6.6", "address": "Teststraat 1"},
        "vehicle": {"plate": "AB-123-C"}, "search": {"max_extra_min": "0"},
        "providers": {"enabled": ["anwb"]}, "routing": {"enabled": False}}}

    def test_serves_page_with_security_headers(self):
        status, body, resp = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("fuelfinder", body)
        self.assertIn("default-src 'self'", resp.getheader("Content-Security-Policy"))

    def test_settings_roundtrip_and_key_not_exposed(self):
        status, data, _ = self.call("GET", "/api/settings")
        self.assertEqual(status, 200)
        data["vehicle"]["plate"] = "ZZ-99-ZZ"
        data["providers"]["tankerkoenig_api_key"] = "TOPGEHEIM"
        status, saved, _ = self.call("POST", "/api/settings", data)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["vehicle"]["plate"], "ZZ-99-ZZ")
        self.assertNotIn("TOPGEHEIM", json.dumps(saved))
        self.assertIn("TOPGEHEIM", Path(self.cfg_path).read_text())
        # opnieuw opslaan met lege key behoudt de key
        saved["providers"]["tankerkoenig_api_key"] = ""
        self.call("POST", "/api/settings", saved)
        self.assertIn("TOPGEHEIM", Path(self.cfg_path).read_text())

    def test_invalid_settings_rejected_with_message(self):
        status, data, _ = self.call("POST", "/api/settings", {"search": {"fill_liters": "veel"}})
        self.assertEqual(status, 400)
        self.assertIn("Liters tanken", data["error"])

    def test_search_returns_consistent_rows(self):
        status, data, _ = self.call("POST", "/api/search", self.SEARCH)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["fuel"], "diesel")
        rows = data["results"]
        self.assertEqual(rows[0]["rank"], 1)
        base = next(r for r in rows if r["is_baseline"])
        for r in rows:
            self.assertEqual(r["total"], round(r["fill_cost"] + r["detour_cost"], 2))
            self.assertEqual(r["saving"], round(base["total"] - r["total"], 2))
            self.assertEqual(r["extra_min"], r["minutes"] - base["minutes"])
            lat, lon = r["lat"], r["lon"]
            self.assertEqual(r["nav"]["google"], "https://www.google.com/maps/dir/?api=1&travelmode=driving"
                                                  f"&destination={lat},{lon}")
            self.assertEqual(r["nav"]["apple"], f"https://maps.apple.com/?daddr={lat},{lon}&dirflg=d")
            self.assertEqual(r["nav"]["waze"], f"https://waze.com/ul?ll={lat},{lon}&navigate=yes")
        self.assertTrue(data["any_estimated"])  # routering stond uit

    def route_body(self, dest):
        return {**self.SEARCH, "mode": "route", "dest": dest}

    def test_route_search_with_max_km(self):
        status, data, _ = self.call("POST", "/api/search", {**self.route_body({"lat": "52.0", "lon": "6.6"}), "max_km": "0,5"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["max_km"], 0.5)
        self.assertEqual(data["results"], [])
        status, data, _ = self.call("POST", "/api/search", {**self.route_body({"lat": "52.0", "lon": "6.6"}), "max_km": "abc"})
        self.assertEqual(status, 400)
        status, data, _ = self.call("POST", "/api/search", {**self.route_body({"lat": "52.0", "lon": "6.6"}), "max_km": ""})
        self.assertEqual((status, data["max_km"]), (200, None))

    def test_route_search_through_api(self):
        status, data, _ = self.call("POST", "/api/search", self.route_body({"lat": "52.0", "lon": "6.6"}))
        self.assertEqual(status, 200, data)
        self.assertEqual((data["mode"], data["dest"]["lat"]), ("route", 52.0))
        self.assertGreater(data["route"]["km"], 10)
        self.assertEqual(data["corridor_km"], 10.0)   # geen tijdlimiet in SEARCH
        rows = data["results"]
        base = next(r for r in rows if r["is_baseline"])
        for r in rows:
            self.assertEqual(r["total"], round(r["fill_cost"] + r["detour_cost"], 2))
            self.assertEqual(r["saving"], round(base["total"] - r["total"], 2))
            lat, lon = r["lat"], r["lon"]
            self.assertEqual(r["nav"]["google"], "https://www.google.com/maps/dir/?api=1&travelmode=driving"
                                                  f"&destination=52.0,6.6&waypoints={lat},{lon}")
            self.assertEqual(r["nav"]["apple"], f"https://maps.apple.com/?daddr={lat},{lon}+to:52.0,6.6&dirflg=d")
            self.assertEqual(r["nav"]["waze"], f"https://waze.com/ul?ll={lat},{lon}&navigate=yes")

    def test_route_search_validates_destination(self):
        status, data, _ = self.call("POST", "/api/search", self.route_body({"lat": "52.0"}))
        self.assertEqual(status, 400)
        self.assertIn("Bestemming", data["error"])
        status, data, _ = self.call("POST", "/api/search", self.route_body({"lat": "99", "lon": "6"}))
        self.assertEqual(status, 400)
        status, data, _ = self.call("POST", "/api/search", self.route_body({}))   # geen bestemming en geen werk
        self.assertEqual(status, 400)
        self.assertIn("bestemming", data["error"].lower())

    def test_route_search_by_address_geocodes_destination(self):
        status, data, _ = self.call("POST", "/api/search", self.route_body({"address": "Werkstraat 1, Sittard"}))
        self.assertEqual(status, 400)   # de nagebootste geocoder geeft hetzelfde punt als het vertrek
        self.assertIn("dezelfde plek", data["error"])

    def test_places_are_saved_and_usable_as_destination(self):
        places = [{"name": "Werk", "address": "Werk 1", "lat": "52.0", "lon": "6.6"},
                  {"name": "Oma", "address": "Oma 2", "lat": "51.9", "lon": "6.9"}]
        status, data, _ = self.call("POST", "/api/settings", {"places": places})
        self.assertEqual(status, 200, data)
        self.assertEqual([p["name"] for p in data["places"]], ["Werk", "Oma"])
        status, data, _ = self.call("POST", "/api/search", {**self.SEARCH, "mode": "route", "dest": {"address": "Oma"}})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["dest"]["label"], "Oma 2")
        status, data, _ = self.call("POST", "/api/search", {**self.SEARCH, "mode": "route", "dest": {}})
        self.assertEqual((status, data["dest"]["label"]), (200, "Werk 1"))   # leeg = het adres "Werk"
        status, data, _ = self.call("POST", "/api/settings", {"places": [{"name": "X"}]})
        self.assertEqual(status, 400)
        self.call("POST", "/api/settings", {"places": []})

    def test_test_source_endpoint(self):
        status, data, _ = self.call("POST", "/api/test-source", {"source": "anwb"})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["source"], data["stations"]), ("anwb", 0))   # de nepstations liggen ver van Roermond
        self.assertIn("geen stations", data["detail"])
        status, data, _ = self.call("POST", "/api/test-source", {"source": "nepbron"})
        self.assertEqual(status, 400)

    def test_map_library_is_served_and_nothing_else_from_disk(self):
        status, body, resp = self.call("GET", "/vendor/leaflet/leaflet.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", resp.getheader("Content-Type"))
        self.assertIn("Leaflet", body)
        status, _, resp = self.call("GET", "/vendor/leaflet/images/marker-icon.png")
        self.assertEqual((status, resp.getheader("Content-Type")), (200, "image/png"))
        for path in ("/vendor/leaflet/../../web.py", "/vendor/../web.py", "/vendor/%2e%2e/web.py",
                     "/fuelfinder/web.py", "/vendor/leaflet/nope.js", "/vendor/leaflet/"):
            status, _, _ = self.call("GET", path)
            self.assertEqual(status, 404, path)
        self.assertEqual(self.call("GET", "/vendor/leaflet/leaflet.js", host="evil.example:80")[0], 403)

    def test_csp_allows_only_the_map_tile_host_for_images(self):
        _, _, resp = self.call("GET", "/")
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("img-src 'self' data: https://tile.openstreetmap.org", csp)
        self.assertNotIn("connect-src", csp)   # default-src 'self': de pagina mag verder alleen naar zichzelf

    def test_export_needs_a_search_first_then_downloads_everything(self):
        fresh = web.App(str(Path(self.tmp.name) / "other.toml"))
        with self.assertRaises(ValueError):
            fresh.export()
        self.call("POST", "/api/search", self.SEARCH)
        status, body, resp = self.call("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment; filename=\"fuelfinder-data-", resp.getheader("Content-Disposition"))
        self.assertEqual(body["counts"]["stations_seen"], 2)
        _, screen, _ = self.call("POST", "/api/search", self.SEARCH)
        self.assertEqual([r["nr"] for r in body["stations"]], [r["rank"] for r in screen["results"]])
        self.assertEqual({r["source_label"] for r in body["stations"]}, {"ANWB Onderweg"})
        self.assertEqual(self.call("GET", "/api/export", host="evil.example:80")[0], 403)

    def test_search_rows_carry_their_source(self):
        _, data, _ = self.call("POST", "/api/search", self.SEARCH)
        for r in data["results"]:
            self.assertEqual((r["source"], r["source_label"]), ("anwb", "ANWB Onderweg"))
            self.assertIn(r["source_origin"], ("live", "cache"))
        self.assertIsInstance(data["others"], list)

    def test_via_route_endpoint(self):
        self.call("POST", "/api/settings", {"routing": {"enabled": False}})
        try:
            status, data, _ = self.call("GET", "/api/via?a=51.9,6.6&s=51.95,6.55&b=51.9,6.6")
            self.assertEqual(status, 200, data)
            self.assertTrue(data["estimated"])
            self.assertEqual(len(data["line"]), 3)
            self.assertGreater(data["km"], 5)
            for bad in ("a=x&s=1,1&b=1,1", "a=1,1&s=1,1", "a=1,1&s=99,1&b=1,1"):
                self.assertEqual(self.call("GET", "/api/via?" + bad)[0], 400, bad)
        finally:
            self.call("POST", "/api/settings", {"routing": {"enabled": True}})

    def test_search_without_home_gives_400(self):
        status, data, _ = self.call("POST", "/api/search", {"settings": {"vehicle": {"fuel": "diesel", "consumption_l_per_100km": "5"}}})
        self.assertEqual(status, 400)
        self.assertIn("locatie", data["error"].lower())

    def test_geocode_and_vehicle(self):
        status, data, _ = self.call("GET", "/api/geocode?q=Teststraat+1")
        self.assertEqual((status, data["lat"]), (200, 51.9))
        status, data, _ = self.call("GET", "/api/vehicle?plate=ab-123-c")
        self.assertEqual(status, 200)
        self.assertEqual((data["fuel"], data["l_per_100km"], data["source"]), ("diesel", 6.0, "WLTP"))
        self.assertEqual(self.call("GET", "/api/geocode?q=")[0], 400)

    def test_reverse_geocode(self):
        status, data, _ = self.call("GET", "/api/reverse?lat=51.9&lon=6.6")
        self.assertEqual((status, data["label"]), (200, "Teststraat 1, Plaats"))
        self.assertEqual(self.call("GET", "/api/reverse?lat=abc&lon=6.6")[0], 400)
        self.assertEqual(self.call("GET", "/api/reverse?lat=95&lon=6.6")[0], 400)

    def test_reverse_geocode_falls_back_to_coordinates(self):
        def boom(*a, **k):
            raise fhttp.FetchError("offline")
        with mock.patch.object(fhttp, "fetch_json", boom):
            self.assertEqual(web.App("x").reverse("51.9", "6.6")["label"], "51.90000, 6.60000")

    def test_wrong_host_header_rejected(self):  # DNS-rebinding
        self.assertEqual(self.call("GET", "/api/settings", host="evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/", host=f"evil.example:{self.port}")[0], 403)

    def test_cross_site_post_rejected(self):
        status, _, _ = self.call("POST", "/api/settings", {}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.call("POST", "/api/settings", {}, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)  # 'simple' cross-site formulierposts worden geweigerd

    def test_unknown_path_and_bad_json(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/search", body="{kapot", headers={"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 400)


if __name__ == "__main__":
    unittest.main()
