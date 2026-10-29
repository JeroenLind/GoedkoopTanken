"""Tests voor zoeken langs een route (A -> B met tanken onderweg)."""

import math
import random
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from fuelfinder import calc, config, geo, service
from fuelfinder import http as fhttp
from fuelfinder.models import PETROL95, Station
from fuelfinder.routing import Router
from test_all import FakeNet, anwb_station

A = (51.19, 5.99)     # Roermond
B = (51.19, 6.59)     # ca. 42 km oostwaarts
KM_LON = 111.2 * math.cos(math.radians(51.19))


class RouteNet(FakeNet):
    """FakeNet plus een OSRM die rijafstand = 1,2 x hemelsbreed en 60 km/u rekent."""

    def __init__(self):
        super().__init__()
        self.osrm_down = False

    def __call__(self, url, headers=None, retries=2):
        if "osrm" not in url:
            return super().__call__(url, headers, retries)
        self.calls.append(url)
        if self.osrm_down:
            raise fhttp.FetchError("OSRM offline")
        coords = [tuple(map(float, c.split(","))) for c in re.search(r"driving/([^?]+)", url).group(1).split(";")]
        if "/route/v1/" in url:
            km = sum(geo.haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:])) * 1.2
            return {"code": "Ok", "routes": [{"distance": km * 1000, "duration": km / 60 * 3600,
                                              "geometry": {"coordinates": [list(c) for c in coords]}}]}
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        d = lambda i, j: geo.haversine_km(coords[i][1], coords[i][0], coords[j][1], coords[j][0]) * 1200
        t = lambda i, j: d(i, j) / 1000 / 60 * 3600
        n = len(coords)
        if "sources" in q:
            return {"code": "Ok", "distances": [[d(0, j) for j in range(n)]], "durations": [[t(0, j) for j in range(n)]]}
        k = int(q["destinations"][0])
        return {"code": "Ok", "distances": [[d(i, k)] for i in range(n)], "durations": [[t(i, k)] for i in range(n)]}


def off_route(lon_frac, km_north, price, i):
    """Station op `lon_frac` van A naar B, `km_north` km noordelijk van de route."""
    return anwb_station(i, A[0] + km_north / 111.2, A[1] + lon_frac * (B[1] - A[1]), euro95=price)


class RouteServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.net = RouteNet()
        self.net.anwb_stations = [
            off_route(0.5, 0.0, 2.200, 1),   # precies op de route
            off_route(0.4, 8.0, 2.100, 2),   # 8 km ernaast, goedkoper
            off_route(0.6, 25.0, 1.700, 3),  # ver buiten de corridor
            off_route(0.1, 0.5, 2.150, 4),   # vlak bij het begin
        ]
        self.patch = mock.patch.object(fhttp, "fetch_json", self.net)
        self.patch.start()
        self.cfg = config.Config(home_lat=A[0], home_lon=A[1], fuel="petrol95", consumption=7.0,
                                 countries={"NL": ["anwb"], "DE": ["anwb"], "BE": ["anwb"]}, cache_dir=str(Path(self.tmp.name) / "c"),
                                 max_extra_min=None, fill_liters=40.0)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def go(self, **kw):
        params = service.SearchParams(route=True, dest_lat=B[0], dest_lon=B[1], **kw)
        return service.search(self.cfg, params)

    def test_picks_cheaper_station_off_route_when_detour_is_small(self):
        out = self.go()
        self.assertEqual(out.mode, "route")
        names = [r.station.name for r in out.results]
        self.assertNotIn("ANWB-3", names)               # 25 km ernaast: buiten de corridor
        self.assertEqual(out.results[0].station.name, "ANWB-2")
        base = out.baseline
        self.assertEqual(base.station.name, "ANWB-1")   # kleinste omweg
        self.assertLess(base.km_round_trip, 0.5)
        self.assertGreater(out.results[0].km_round_trip, 2.0)   # extra km t.o.v. de directe route
        self.assertEqual(out.results[0].saving_vs_baseline,
                         round(base.total - out.results[0].total, 2))

    def test_detour_is_difference_with_direct_route(self):
        out = self.go()
        r = next(x for x in out.results if x.station.name == "ANWB-2")
        s = r.station
        direct = geo.haversine_km(*A, *B) * 1.2
        via = (geo.haversine_km(*A, s.lat, s.lon) + geo.haversine_km(s.lat, s.lon, *B)) * 1.2
        self.assertAlmostEqual(r.km_round_trip, via - direct, places=2)
        self.assertEqual(r.min_round_trip, round((via - direct) / 60 * 60))
        self.assertEqual(r.detour_cost, round(r.km_round_trip * out.real_consumption / 100 * r.price, 2))

    def test_reference_is_the_fastest_route_and_all_extras_are_relative_to_it(self):
        out = self.go()
        direct = geo.haversine_km(*A, *B) * 1.2   # snelste route in de nep-OSRM
        self.assertAlmostEqual(out.route_km, direct, places=2)
        self.assertAlmostEqual(out.route_min, direct / 60 * 60, delta=0.5)
        for r in out.results:
            s = r.station
            via = (geo.haversine_km(*A, s.lat, s.lon) + geo.haversine_km(s.lat, s.lon, *B)) * 1.2
            self.assertAlmostEqual(out.route_km + r.km_round_trip, via, places=2)   # referentie + omweg = via station
            self.assertEqual(r.km_back, 0.0)

    def test_max_km_drops_stations_too_far_from_the_start(self):
        out = self.go(max_km=10, corridor_km=10)
        self.assertEqual([r.station.name for r in out.results], ["ANWB-4"])   # de rest ligt ruim 20 km weg
        self.assertTrue(out.baseline.station.name == "ANWB-4")                # referentie is haalbaar
        self.assertEqual({s.name for s in out.too_far}, {"ANWB-1", "ANWB-2"})
        self.assertLessEqual(out.results[0].km_to_station, 10)

    def test_max_km_is_driving_distance_from_start(self):
        out = self.go(max_km=500, corridor_km=10)
        r = next(x for x in out.results if x.station.name == "ANWB-1")
        self.assertAlmostEqual(r.km_to_station, geo.haversine_km(*A, r.station.lat, r.station.lon) * 1.2, places=2)
        self.assertEqual(out.too_far, [])

    def test_max_km_nothing_reachable_gives_notice(self):
        out = self.go(max_km=1, corridor_km=10)
        self.assertEqual(out.results, [])
        self.assertIn("Geen station binnen 1 km", out.notice)

    def test_max_km_ignored_when_searching_around(self):
        out = service.search(self.cfg, service.SearchParams(max_km=10))
        self.assertIsNone(out.max_km)
        self.assertTrue(any("alleen bij zoeken langs een route" in w for w in out.warnings))

    def test_max_km_status_in_export(self):
        out = self.go(max_km=10, corridor_km=10)
        rows = {r["name"]: r for r in service.export_data(out)["stations"]}
        self.assertIn("te ver weg", rows["ANWB-1"]["status"])
        self.assertEqual(service.export_data(out)["counts"]["too_far"], 2)

    def test_time_limit_applies_to_the_detour_itself(self):
        out = self.go(max_extra_min=2, corridor_km=10)
        names = [r.station.name for r in out.results]
        self.assertIn("ANWB-1", names)
        self.assertNotIn("ANWB-2", names)   # ca. 4 min omweg
        self.assertEqual(out.hidden_by_time_limit, 1)
        self.assertIn("ANWB-2", [r.station.name for r in self.go(max_extra_min=10, corridor_km=10).results])

    def test_each_station_once_despite_overlapping_circles(self):
        out = self.go()
        ids = [r.station.id for r in out.results]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(out.sources), 1)

    def test_second_route_search_uses_cache(self):
        self.go()
        before = sum("api.anwb.nl" in u for u in self.net.calls)
        out = self.go()
        self.assertEqual(sum("api.anwb.nl" in u for u in self.net.calls), before)
        self.assertEqual(out.sources["anwb"].origin, "cache")
        self.assertGreater(before, 0)

    def test_output_describes_route_and_corridor(self):
        out = self.go(max_extra_min=30)
        self.assertAlmostEqual(out.route_km, geo.haversine_km(*A, *B) * 1.2, places=1)
        self.assertEqual(out.corridor_km, 12.0)     # 0,4 km per toegestane minuut
        self.assertEqual(out.dest, B)

    def test_wider_corridor_override(self):
        self.assertEqual(self.go(corridor_km=5).corridor_km, 5)
        with self.assertRaises(service.SearchError):
            self.go(corridor_km=30)

    def test_osrm_down_falls_back_to_straight_line_with_warning(self):
        self.net.osrm_down = True
        out = self.go()
        self.assertTrue(any("rechte lijn" in w for w in out.warnings))
        self.assertTrue(all(r.estimated for r in out.results))
        self.assertGreater(len(out.results), 0)

    def test_work_address_as_destination(self):
        self.cfg.places = [{"name": "Werk", "address": "Werkstraat 1", "lat": B[0], "lon": B[1]}]
        out = service.search(self.cfg, service.SearchParams(route=True, dest_address="werk"))
        self.assertEqual((out.dest, out.dest_label), (B, "Werkstraat 1"))

    def test_any_saved_place_by_name(self):
        self.cfg.places = [{"name": "Oma", "address": "Omastraat 3", "lat": B[0], "lon": B[1]}]
        out = service.search(self.cfg, service.SearchParams(route=True, dest_address="  oma "))
        self.assertEqual((out.dest, out.dest_label), (B, "Omastraat 3"))

    def test_missing_destination_and_same_place(self):
        with self.assertRaises(service.SearchError):
            service.search(self.cfg, service.SearchParams(route=True))
        with self.assertRaises(service.SearchError):
            service.search(self.cfg, service.SearchParams(route=True, dest_lat=A[0], dest_lon=A[1] + 0.001))

    def test_too_long_route_is_refused(self):
        with self.assertRaises(service.SearchError):
            service.search(self.cfg, service.SearchParams(route=True, dest_lat=A[0], dest_lon=A[1] + 12))

    def test_around_mode_unchanged(self):
        out = service.search(self.cfg)
        self.assertEqual((out.mode, out.dest), ("around", None))


class RouteMathTests(unittest.TestCase):
    def test_distance_to_polyline(self):
        line = [(51.0, 5.0), (51.0, 5.3)]
        self.assertAlmostEqual(geo.distance_to_polyline_km(51.05, 5.15, line), 5.56, delta=0.05)
        self.assertAlmostEqual(geo.distance_to_polyline_km(51.0, 5.5, line),
                               geo.haversine_km(51.0, 5.5, 51.0, 5.3), delta=0.05)   # voorbij het eind
        self.assertEqual(geo.distance_to_polyline_km(51.0, 5.1, [(51.0, 5.1)]), 0)

    def test_sampling_spacing_and_endpoints(self):
        line = [(51.0, 5.0), (51.0, 5.3), (51.1, 5.6)]
        for step in (5, 12, 30, 200):
            pts = geo.sample_along(line, step)
            self.assertEqual((pts[0], pts[-1]), (line[0], line[-1]))
            gaps = [geo.haversine_km(*a, *b) for a, b in zip(pts, pts[1:])]
            self.assertLessEqual(max(gaps), step + 0.01)

    def test_circles_cover_the_whole_corridor_even_on_a_bend(self):
        line = [(51.0, 5.0), (51.0, 5.35), (51.15, 5.45), (51.2, 5.8)]
        corridor = 12.0
        usable = service.ROUTE_CIRCLE_KM / service.ROUTE_CIRCLE_SAFETY
        centers = geo.sample_along(line, 2 * math.sqrt(usable ** 2 - corridor ** 2))
        rnd = random.Random(7)
        checked = 0
        for _ in range(4000):
            lat, lon = 50.8 + rnd.random() * 0.6, 4.9 + rnd.random() * 1.1
            if geo.distance_to_polyline_km(lat, lon, line) <= corridor:
                checked += 1
                self.assertTrue(any(geo.haversine_km(lat, lon, *c) <= service.ROUTE_CIRCLE_KM for c in centers),
                                (lat, lon))
        self.assertGreater(checked, 300)

    def test_default_corridor(self):
        self.assertEqual(service.default_corridor_km(None), 10.0)
        self.assertEqual(service.default_corridor_km(30), 12.0)
        self.assertEqual(service.default_corridor_km(5), 3.0)
        self.assertEqual(service.default_corridor_km(120), 15.0)

    def test_estimated_detour_without_osrm(self):
        r = Router(enabled=False).detours(A, B, [(A[0] + 0.05, (A[1] + B[1]) / 2)])[0]
        self.assertTrue(r.estimated)
        self.assertGreater(r.km_out, 0)
        self.assertEqual(r.km_back, 0)

    def test_rank_along_ignores_stations_outside_corridor(self):
        stations = [Station("a", "Dichtbij", A[0] + 0.01, 6.2, "t", prices={PETROL95: 2.0}),
                    Station("b", "Ver", A[0] + 0.3, 6.2, "t", prices={PETROL95: 1.0})]
        res = calc.rank_along(stations, A, B, [A, B], 10, PETROL95, 40, 8.0, Router(enabled=False))
        self.assertEqual([r.station.id for r in res], ["a"])


class PlacesConfigTests(unittest.TestCase):
    def test_roundtrip_and_validation(self):
        cfg = config.from_dict({"places": [
            {"name": " Werk ", "lat": "51,2", "lon": "6.1", "address": " Werkweg 2, Sittard "},
            {"name": "Oma", "address": "Dorpsstraat 1"}, {"name": "", "address": ""}]})   # lege rij vervalt
        self.assertEqual(cfg.places, [
            {"name": "Werk", "address": "Werkweg 2, Sittard", "lat": 51.2, "lon": 6.1},
            {"name": "Oma", "address": "Dorpsstraat 1", "lat": None, "lon": None}])
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "c.toml")
            config.save(cfg, path)
            self.assertEqual(config.load(path).places, cfg.places)
        self.assertEqual(config.to_dict(config.Config())["places"], [])

    def test_validation_errors(self):
        bad = [[{"name": "X", "lat": "51.2"}], [{"name": "", "address": "Straat 1"}],
               [{"name": "X"}], [{"name": "A", "address": "a"}, {"name": "a", "address": "b"}],
               [{"name": "X" * 41, "address": "a"}], [{"name": f"p{i}", "address": "a"} for i in range(21)],
               [{"name": "X", "lat": "99", "lon": "1"}]]
        for places in bad:
            with self.assertRaises(ValueError, msg=str(places)):
                config.from_dict({"places": places})

    def test_request_without_places_keeps_saved_ones(self):
        base = config.from_dict({"places": [{"name": "Werk", "address": "W 1"}]})
        self.assertEqual(config.from_dict({"home": {}}, base).places, base.places)

    def test_old_work_section_becomes_place_werk(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            path.write_text('[work]\nlat = 51.2\nlon = 6.1\naddress = "Oud 1"\n', encoding="utf-8")
            self.assertEqual(config.load(str(path)).places,
                             [{"name": "Werk", "address": "Oud 1", "lat": 51.2, "lon": 6.1}])
        cfg = config.from_dict({"work": {"address": "Nieuw 2"}})
        self.assertEqual([p["name"] for p in cfg.places], ["Werk"])
        self.assertEqual(config.from_dict({"work": {}}, cfg).places, [])


if __name__ == "__main__":
    unittest.main()
