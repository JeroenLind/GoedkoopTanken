"""Offline tests: alle netwerkverkeer wordt vervangen door voorbeelddata."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from fuelfinder import calc, cli, http, vehicle
from fuelfinder.config import Config
from fuelfinder.geo import bounding_box, haversine_km
from fuelfinder.models import DIESEL, PETROL95, Station
from fuelfinder.providers import build_providers, collect
from fuelfinder.providers.anwb import AnwbProvider
from fuelfinder.providers.tankerkoenig import TankerkoenigProvider
from fuelfinder.routing import Router

HOME = (51.90, 6.60)


def anwb_station(i, lat, lon, euro95=None, diesel=None):
    prices = []
    if euro95:
        prices.append({"fuelType": "EURO95", "value": euro95})
    if diesel:
        prices.append({"fuelType": "DIESEL", "value": diesel})
    prices.append({"fuelType": "SOMETHING_ELSE", "value": 9.99})
    return {"id": f"{i}", "title": f"ANWB-{i}", "coordinates": {"latitude": lat, "longitude": lon},
            "address": {"streetAddress": "Weg 1", "city": "Plaats", "postalCode": "1234AB"},
            "prices": prices}


TK_RESPONSE = {"ok": True, "stations": [
    {"id": "t1", "name": "Aral", "brand": "ARAL", "street": "Str", "houseNumber": "1",
     "postCode": 46399, "place": "Bocholt", "lat": 51.84, "lng": 6.61, "dist": 6.7,
     "diesel": 1.689, "e5": 1.829, "e10": 1.769, "isOpen": True},
    {"id": "t2", "name": "Dicht", "brand": "X", "lat": 51.85, "lng": 6.62,
     "diesel": 1.5, "e5": 1.5, "e10": 1.5, "isOpen": False},
    {"id": "t3", "name": "Geen prijs", "brand": "Y", "lat": 51.86, "lng": 6.60,
     "diesel": None, "e5": False, "e10": None, "isOpen": True},
]}


class FakeNet:
    """Vervangt http.fetch_json en beantwoordt per URL."""

    def __init__(self):
        self.calls = []
        self.anwb_limit_first = False
        self.anwb_stations = []

    def __call__(self, url, headers=None, retries=2):
        self.calls.append(url)
        if "api.anwb.nl" in url:
            if self.anwb_limit_first and sum("api.anwb.nl" in c for c in self.calls) == 1:
                return {"error": {"code": "limit_exceeded"}}
            return {"value": self.anwb_stations}
        if "tankerkoenig" in url:
            return TK_RESPONSE
        if "8ys7-d773" in url:
            return [{"kenteken": "AB123C", "brandstof_omschrijving": "Diesel",
                     "brandstofverbruik_gecombineerd": "5.1",
                     "brandstofverbruik_gecombineerd_wltp": "6.0"}]
        if "m9d7-ebf2" in url:
            return [{"merk": "VOLKSWAGEN", "handelsbenaming": "GOLF"}]
        raise AssertionError(f"onverwachte URL: {url}")


class GeoTests(unittest.TestCase):
    def test_haversine_known_distance(self):
        # Amsterdam CS - Utrecht CS is ongeveer 35 km hemelsbreed
        self.assertAlmostEqual(haversine_km(52.3789, 4.9003, 52.0894, 5.1101), 35.0, delta=2.0)

    def test_bounding_box_contains_circle(self):
        min_lat, min_lon, max_lat, max_lon = bounding_box(*HOME, 10)
        self.assertLess(min_lat, HOME[0]); self.assertGreater(max_lat, HOME[0])
        self.assertAlmostEqual(haversine_km(HOME[0], HOME[1], max_lat, HOME[1]), 10, delta=0.1)
        self.assertAlmostEqual(haversine_km(HOME[0], HOME[1], HOME[0], max_lon), 10, delta=0.1)


class VehicleTests(unittest.TestCase):
    def test_plate_normalised(self):
        self.assertEqual(vehicle.normalize_plate("ab-123-c "), "AB123C")

    def test_prefers_wltp(self):
        with mock.patch.object(http, "fetch_json", FakeNet()):
            veh, rows = vehicle.lookup("ab-123-c")
        self.assertEqual(veh.fuel, DIESEL)
        self.assertEqual(veh.l_per_100km, 6.0)
        self.assertEqual(veh.consumption_source, "WLTP")
        self.assertEqual(veh.description, "VOLKSWAGEN GOLF")

    def test_falls_back_to_nedc_and_decimal_comma(self):
        v = vehicle.parse_fuel_rows("X", [{"brandstof_omschrijving": "Benzine",
                                           "brandstofverbruik_gecombineerd": "5,4"}])
        self.assertEqual((v.fuel, v.l_per_100km, v.consumption_source), (PETROL95, 5.4, "NEDC"))

    def test_hybrid_skips_electric_row(self):
        v = vehicle.parse_fuel_rows("X", [
            {"brandstof_omschrijving": "Elektriciteit"},
            {"brandstof_omschrijving": "Benzine", "brandstofverbruik_gecombineerd_wltp": "1.1"}])
        self.assertEqual(v.fuel, PETROL95)

    def test_no_consumption_known(self):
        v = vehicle.parse_fuel_rows("X", [{"brandstof_omschrijving": "Benzine"}])
        self.assertEqual((v.fuel, v.l_per_100km), (PETROL95, None))

    def test_unknown_plate(self):
        with mock.patch.object(http, "fetch_json", lambda *a, **k: []):
            with self.assertRaises(http.FetchError):
                vehicle.lookup("ZZ999Z")


class ProviderTests(unittest.TestCase):
    def test_anwb_parses_and_ignores_unknown_fuels(self):
        net = FakeNet()
        net.anwb_stations = [anwb_station(1, 51.91, 6.60, euro95=2.0, diesel=1.9),
                             {"id": "x"}]  # kapot record wordt overgeslagen
        p = AnwbProvider()
        with mock.patch.object(http, "fetch_json", net):
            stations = p.fetch(*HOME, 10)
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].prices, {PETROL95: 2.0, DIESEL: 1.9})
        self.assertIn("SOMETHING_ELSE", p.fuel_types_seen)

    def test_anwb_splits_box_on_limit_exceeded(self):
        net = FakeNet(); net.anwb_limit_first = True
        net.anwb_stations = [anwb_station(1, 51.91, 6.60, euro95=2.0)]
        with mock.patch.object(http, "fetch_json", net):
            stations = AnwbProvider().fetch(*HOME, 10)
        anwb_calls = [c for c in net.calls if "api.anwb.nl" in c]
        self.assertEqual(len(anwb_calls), 5)  # 1 mislukte + 4 deelvakken
        self.assertEqual(len(stations), 1)  # dubbele ids worden samengevoegd

    def test_anwb_returns_belgian_station_near_the_border(self):
        # Maaseik (België), ca. 17 km van Roermond: FR-29, België komt via ANWB binnen
        net = FakeNet(); net.anwb_stations = [anwb_station(7, 51.0969, 5.7933, euro95=2.05, diesel=1.95)]
        with mock.patch.object(http, "fetch_json", net):
            stations = AnwbProvider().fetch(51.1942, 5.9876, 25)
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].prices, {PETROL95: 2.05, DIESEL: 1.95})
        self.assertEqual(stations[0].source, "anwb")

    def test_anwb_drops_stations_outside_radius(self):
        net = FakeNet(); net.anwb_stations = [anwb_station(1, 52.5, 6.6, euro95=2.0)]
        with mock.patch.object(http, "fetch_json", net):
            self.assertEqual(AnwbProvider().fetch(*HOME, 10), [])

    def test_tankerkoenig_prices_and_open_flag(self):
        with mock.patch.object(http, "fetch_json", FakeNet()):
            st = {s.id: s for s in TankerkoenigProvider("key").fetch(*HOME, 25)}
        self.assertEqual(st["tk:t1"].prices, {PETROL95: 1.769, DIESEL: 1.689})  # E10 is goedkoopst
        self.assertFalse(st["tk:t2"].is_open)
        self.assertEqual(st["tk:t3"].prices, {})  # null/false = geen prijs

    def test_tankerkoenig_without_e10(self):
        with mock.patch.object(http, "fetch_json", FakeNet()):
            st = {s.id: s for s in TankerkoenigProvider("key", allow_e10=False).fetch(*HOME, 25)}
        self.assertEqual(st["tk:t1"].prices[PETROL95], 1.829)

    def test_tankerkoenig_needs_key(self):
        from fuelfinder.providers.base import ProviderError
        with self.assertRaises(ProviderError):
            TankerkoenigProvider(None).fetch(*HOME, 10)

    def test_failing_provider_does_not_stop_others(self):
        net = FakeNet(); net.anwb_stations = [anwb_station(1, 51.91, 6.60, euro95=2.0)]
        cfg = Config(tankerkoenig_key=None)
        with mock.patch.object(http, "fetch_json", net):
            stations, msgs = collect(build_providers(cfg, ["tankerkoenig", "anwb"]), *HOME, 25)
        self.assertTrue(msgs["tankerkoenig"].startswith("mislukt"))
        self.assertEqual(len(stations), 1)

    def test_dedupe_prefers_first_provider(self):
        net = FakeNet()
        net.anwb_stations = [anwb_station(9, 51.84, 6.61, euro95=1.99)]  # zelfde plek als tk:t1
        cfg = Config(tankerkoenig_key="k")
        with mock.patch.object(http, "fetch_json", net):
            stations, _ = collect(build_providers(cfg, ["tankerkoenig", "anwb"]), *HOME, 25)
        near = [s for s in stations if haversine_km(s.lat, s.lon, 51.84, 6.61) < 0.1]
        self.assertEqual([s.source for s in near], ["tankerkoenig"])


class CalcTests(unittest.TestCase):
    def setUp(self):
        self.router = Router(enabled=False)  # geschatte afstand = 1,3 x hemelsbreed

    def mk(self, sid, lat, lon, price):
        return Station(sid, sid, lat, lon, "test", prices={PETROL95: price})

    def test_math_for_single_station(self):
        s = self.mk("a", HOME[0] + 0.09, HOME[1], 1.80)  # ~10 km noord
        (r,) = calc.rank([s], HOME, PETROL95, 40, 7.0, self.router)
        km = haversine_km(*HOME, s.lat, s.lon) * 1.3
        self.assertAlmostEqual(r.km_round_trip, 2 * km, places=6)
        self.assertAlmostEqual(r.fill_cost, 72.0)
        self.assertEqual(r.detour_cost, round(2 * km * 7 / 100 * 1.80, 2))
        self.assertAlmostEqual(r.total, r.fill_cost + r.detour_cost)
        self.assertEqual(r.min_round_trip, round(2 * km / 50 * 60))
        self.assertTrue(r.is_baseline)
        self.assertEqual(r.saving_vs_baseline, 0)

    def test_far_cheap_station_loses_when_detour_costs_more(self):
        near = self.mk("near", HOME[0] + 0.01, HOME[1], 1.95)
        far = self.mk("far", HOME[0] + 0.45, HOME[1], 1.90)  # ~50 km, maar maar 5 ct goedkoper
        res = calc.rank([near, far], HOME, PETROL95, 40, 7.0, self.router)
        self.assertEqual(res[0].station.id, "near")
        by_id = {r.station.id: r for r in res}
        self.assertLess(by_id["far"].saving_vs_baseline, 0)

    def test_far_station_wins_when_saving_is_large(self):
        near = self.mk("near", HOME[0] + 0.01, HOME[1], 2.10)
        far = self.mk("far", HOME[0] + 0.18, HOME[1], 1.80)  # ~20 km, 30 ct goedkoper
        res = calc.rank([near, far], HOME, PETROL95, 40, 7.0, self.router)
        self.assertEqual(res[0].station.id, "far")
        self.assertGreater(res[0].saving_vs_baseline, 5.0)
        self.assertGreater(res[0].extra_min_vs_baseline, 20)  # ~20 km verder = ruim 20 min extra
        self.assertEqual(res[1].extra_min_vs_baseline, 0)  # baseline t.o.v. zichzelf

    def test_closed_and_priceless_stations_excluded(self):
        a = self.mk("a", 51.91, 6.6, 1.9)
        closed = self.mk("closed", 51.91, 6.6, 1.0); closed.is_open = False
        diesel_only = Station("d", "d", 51.91, 6.6, "test", prices={DIESEL: 1.5})
        res = calc.rank([a, closed, diesel_only], HOME, PETROL95, 40, 7.0, self.router)
        self.assertEqual([r.station.id for r in res], ["a"])

    def test_displayed_numbers_are_internally_consistent(self):
        import random
        rnd = random.Random(7)
        stations = [self.mk(f"s{i}", HOME[0] + rnd.uniform(0.005, 0.2), HOME[1] + rnd.uniform(-0.1, 0.1),
                            round(rnd.uniform(1.7, 2.4), 3)) for i in range(60)]
        res = calc.rank(stations, HOME, PETROL95, 37.5, 8.4, self.router)
        base = next(r for r in res if r.is_baseline)
        for r in res:
            self.assertEqual(r.total, round(r.fill_cost + r.detour_cost, 2))
            self.assertEqual(r.saving_vs_baseline, round(base.total - r.total, 2))
            self.assertEqual(r.extra_min_vs_baseline, r.min_round_trip - base.min_round_trip)
            self.assertIsInstance(r.min_round_trip, int)

    def test_time_limit_filters_but_keeps_baseline(self):
        near = self.mk("near", HOME[0] + 0.01, HOME[1], 2.10)
        mid = self.mk("mid", HOME[0] + 0.12, HOME[1], 1.95)   # ~13 km, ~30 min extra
        far = self.mk("far", HOME[0] + 0.45, HOME[1], 1.70)   # ~50 km, ruim 90 min extra
        res = calc.rank([near, mid, far], HOME, PETROL95, 40, 7.0, self.router)
        ids = lambda rs: {r.station.id for r in rs}
        self.assertEqual(ids(calc.within_time_limit(res, None)), {"near", "mid", "far"})
        self.assertEqual(ids(calc.within_time_limit(res, 60)), {"near", "mid"})
        self.assertEqual(ids(calc.within_time_limit(res, 1)), {"near"})  # baseline blijft altijd

    def test_empty(self):
        self.assertEqual(calc.rank([], HOME, PETROL95, 40, 7, self.router), [])

    def test_candidate_limit_still_includes_nearest(self):
        stations = [self.mk(f"s{i}", HOME[0] + 0.005 * i, HOME[1], 1.9 - 0.001 * i) for i in range(1, 60)]
        res = calc.rank(stations, HOME, PETROL95, 40, 7, self.router, max_candidates=5)
        ids = {r.station.id for r in res}
        self.assertIn("s1", ids)  # dichtstbij hoort er altijd bij (baseline)
        self.assertLessEqual(len(ids), 8)


class RoutingTests(unittest.TestCase):
    def test_osrm_parsing_both_directions(self):
        def fake(url, headers=None, retries=2):
            if "sources=0" in url:
                return {"code": "Ok", "distances": [[0, 1000, 20000]],
                        "durations": [[0, 120, 1500]]}
            if "destinations=0" in url:
                return {"code": "Ok", "distances": [[0], [1500], [None]],
                        "durations": [[0], [180], [None]]}
            raise AssertionError(url)
        with mock.patch.object(http, "fetch_json", fake):
            out = Router().distances(HOME, [(51.91, 6.6), (51.99, 6.6)])
        self.assertEqual(tuple(out[0])[:5], (1.0, 1.5, 2.0, 3.0, False))
        self.assertTrue(out[1].estimated)  # terugweg onbekend -> geschat

    def test_osrm_failure_falls_back_to_estimate(self):
        def boom(*a, **k):
            raise http.FetchError("offline")
        with mock.patch.object(http, "fetch_json", boom):
            out = Router().distances(HOME, [(51.91, 6.6)])
        self.assertTrue(out[0].estimated)
        self.assertGreater(out[0].min_out, 0)  # ook de tijd wordt geschat


class CliTests(unittest.TestCase):
    def run_cli(self, argv, net):
        buf = io.StringIO()
        from fuelfinder import config as cfgmod
        real_load = cfgmod.load

        def load_without_cache(path=None):  # tests mogen elkaars data niet hergebruiken
            c = real_load(path)
            c.cache_enabled = False
            return c
        with mock.patch.object(http, "fetch_json", net), mock.patch.object(cfgmod, "load", load_without_cache), \
                redirect_stdout(buf):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_end_to_end_find_with_plate(self):
        net = FakeNet()
        net.anwb_stations = [anwb_station(1, 51.905, 6.60, diesel=1.95),
                             anwb_station(2, 51.92, 6.61, diesel=1.99)]
        with mock.patch.dict("os.environ", {"TANKERKOENIG_API_KEY": "k"}):
            code, out = self.run_cli(["find", "--plate", "AB-123-C", "--lat", "51.9", "--lon", "6.6",
                                      "--no-routing", "--radius", "25"], net)
        self.assertEqual(code, 0, out)
        self.assertIn("Diesel", out)
        self.assertIn("WLTP", out)
        self.assertIn("<- dichtstbij", out)
        self.assertIn("Tankerkönig", out)  # bronvermelding
        self.assertIn("~", out)  # geschatte afstanden gemeld
        self.assertIn("Tank", out)
        self.assertIn(" min", out)
        self.assertIn("Extra tijd", out)

    def test_cli_time_limit_default_and_override(self):
        net = FakeNet()
        net.anwb_stations = [anwb_station(1, 51.905, 6.60, diesel=2.05),
                             anwb_station(2, 52.30, 6.60, diesel=1.60)]  # ~45 km weg
        base = ["find", "--fuel", "diesel", "--consumption", "6", "--lat", "51.9", "--lon", "6.6",
                "--no-routing", "--providers", "anwb", "--radius", "60"]
        _, out = self.run_cli(base, net)
        self.assertIn("1 stations weggelaten", out)
        self.assertNotIn("ANWB-2", out)
        _, out = self.run_cli(base + ["--no-time-limit"], net)
        self.assertIn("ANWB-2", out)
        self.assertNotIn("Tijdlimiet", out)
        _, out = self.run_cli(base + ["--max-extra-min", "200"], net)
        self.assertIn("ANWB-2", out)

    def test_find_requires_fuel_and_consumption(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["find", "--lat", "51.9", "--lon", "6.6", "--providers", "anwb"], FakeNet())

    def test_vehicle_command(self):
        code, out = self.run_cli(["vehicle", "AB-123-C"], FakeNet())
        self.assertEqual(code, 0)
        self.assertIn("GOLF", out)
        self.assertIn("6,0", out)

    def test_euro_format(self):
        self.assertEqual(cli.eur(1234.5), "1.234,50")
        self.assertEqual(cli.eur(1.859, 3), "1,859")


if __name__ == "__main__":
    unittest.main()
