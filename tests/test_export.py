"""Tests voor de export van alle bekeken stations en de bron-informatie."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fuelfinder import config, service
from fuelfinder import http as fhttp
from fuelfinder.models import PETROL95, Station
from fuelfinder.providers import SOURCE_LABELS, collect_areas
from fuelfinder.providers.base import Provider
from test_all import anwb_station
from test_route import A, B, RouteNet, off_route


class Fixed(Provider):
    def __init__(self, name, stations):
        self.name, self._stations = name, stations

    def fetch(self, lat, lon, radius_km):
        return list(self._stations)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.net = RouteNet()
        diesel_only = anwb_station(5, A[0], 6.1, diesel=1.9)
        self.net.anwb_stations = [
            off_route(0.5, 0.0, 2.200, 1),     # op de route
            off_route(0.4, 8.0, 2.100, 2),     # 8 km ernaast, goedkoper
            off_route(0.6, 14.0, 1.700, 3),    # buiten de zoekbreedte van 10 km
            diesel_only,                       # geen benzineprijs
        ]
        self.patch = mock.patch.object(fhttp, "fetch_json", self.net)
        self.patch.start()
        self.cfg = config.Config(home_lat=A[0], home_lon=A[1], fuel="petrol95", consumption=7.0,
                                 countries={"NL": ["anwb"], "DE": ["anwb"], "BE": ["anwb"]}, cache_dir=str(Path(self.tmp.name) / "c"),
                                 max_extra_min=None)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def route(self, **kw):
        return service.search(self.cfg, service.SearchParams(route=True, dest_lat=B[0], dest_lon=B[1], **kw))

    def by_name(self, data):
        return {r["name"]: r for r in data["stations"]}

    def test_export_explains_what_happened_to_each_station(self):
        out = self.route()
        data = service.export_data(out)
        rows = self.by_name(data)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows["ANWB-2"]["status"], "getoond in de uitkomst")
        self.assertIn("buiten de zoekbreedte", rows["ANWB-3"]["status"])
        self.assertIn("geen Benzine 95-prijs", rows["ANWB-5"]["status"])
        self.assertEqual({r["source"] for r in data["stations"]}, {"anwb"})
        self.assertEqual({r["source_label"] for r in data["stations"]}, {"ANWB Onderweg"})
        self.assertEqual(data["counts"]["stations_seen"], 4)
        self.assertEqual(data["query"]["mode"], "route")
        self.assertGreater(len(data["route"]["line"]), 1)
        self.assertGreaterEqual(len(data["query"]["searched_areas"]), 2)

    def test_export_result_numbers_match_the_screen(self):
        out = self.route()
        rows = self.by_name(service.export_data(out))
        for r in out.results:
            res = rows[r.station.name]["result"]
            self.assertEqual((res["total"], res["fill_cost"], res["detour_cost"]), (r.total, r.fill_cost, r.detour_cost))
            self.assertEqual(res["extra_min"], r.min_round_trip)
            self.assertEqual(res["saving_vs_reference"], r.saving_vs_baseline)
        ranks = [row["result"]["rank"] for row in service.export_data(out)["stations"]
                 if row.get("result") and row["result"]["rank"]]
        self.assertEqual(ranks, sorted(ranks))   # de uitkomst staat bovenaan, op volgorde

    def test_nr_matches_the_number_on_screen(self):
        out = self.route()
        data = service.export_data(out, max_results=1)
        rows = self.by_name(data)
        for pos, r in enumerate(out.results, 1):
            self.assertEqual(rows[r.station.name]["nr"], pos)
            self.assertEqual(rows[r.station.name]["result"]["rank"], pos)
        screen = {n: r["on_screen"] for n, r in rows.items() if r["nr"]}
        self.assertEqual(screen[out.results[0].station.name], "tabel en kaart")
        base = out.baseline.station.name
        self.assertEqual(screen[base], "tabel en kaart")          # de referentie staat altijd in de tabel
        others = [n for n, v in screen.items() if v and v.startswith("alleen kaart")]
        self.assertTrue(others or len(out.results) <= 2)
        self.assertTrue(all(r["nr"] is None and r["on_screen"] is None for r in data["stations"] if "ANWB-3" == r["name"]))
        self.assertEqual([r["nr"] for r in data["stations"] if r["nr"]], sorted(r["nr"] for r in data["stations"] if r["nr"]))
        self.assertEqual(list(data["stations"][0])[:2], ["nr", "on_screen"])   # staat vooraan in elke regel

    def test_time_limit_is_named_in_the_status(self):
        out = self.route(max_extra_min=2, corridor_km=10)
        rows = self.by_name(service.export_data(out))
        self.assertIn("weggelaten door de tijdlimiet", rows["ANWB-2"]["status"])
        self.assertIn("2 min omweg", rows["ANWB-2"]["status"])
        self.assertEqual(rows["ANWB-2"]["result"]["rank"], None)   # wel doorgerekend, niet getoond

    def test_around_mode_export(self):
        out = service.search(self.cfg)
        data = service.export_data(out)
        self.assertEqual((data["query"]["mode"], data["route"]), ("around", None))
        self.assertTrue(all("km_from_start" in r for r in data["stations"]))
        self.assertIsNotNone(data["query"]["radius_km"])

    def test_sources_section_has_origin_and_message(self):
        data = service.export_data(self.route())
        self.assertEqual(data["sources"]["anwb"]["origin"], "live")
        self.assertIn("stations", data["sources"]["anwb"]["message"])
        data = service.export_data(self.route())      # tweede keer: uit de cache
        self.assertEqual(data["sources"]["anwb"]["origin"], "cache")

    def test_duplicates_between_sources_are_kept_in_the_export(self):
        a = Station("1", "Shell A", 51.2, 6.0, "anwb", prices={PETROL95: 2.0})
        b = Station("x", "Shell T", 51.2003, 6.0, "tankerkoenig", prices={PETROL95: 1.9})   # 33 m ernaast
        dropped = []
        stations, _, _ = collect_areas([Fixed("anwb", [a]), Fixed("tankerkoenig", [b])], [(51.2, 6.0, 5)], dropped=dropped)
        self.assertEqual(stations, [a])
        self.assertEqual(dropped, [(b, a)])
        out = service.SearchOutput(home=(51.2, 6.0), home_label="x", vehicle=None, fuel=PETROL95,
                                   official_consumption=7, real_consumption=8, factor=1.2,
                                   consumption_explicit=False, fill_liters=40, radius_km=5, max_extra_min=None,
                                   stations=stations, dropped=dropped)
        rows = service.export_data(out)["stations"]
        self.assertEqual(len(rows), 2)
        dup = next(r for r in rows if r["id"] == "x")
        self.assertIn("dubbel: Shell A (ANWB Onderweg)", dup["status"])

    def test_path_via_a_station_uses_all_waypoints(self):
        from fuelfinder.routing import Router
        with mock.patch.object(fhttp, "fetch_json", self.net):
            via = Router("https://osrm.example").path([A, (A[0] + 0.05, 6.2), B], overview="full")
        self.assertFalse(via.estimated)
        self.assertEqual(len(via.line), 3)
        direct = Router("https://osrm.example").route_line(A, B)
        self.assertGreater(via.km, direct.km)
        self.assertTrue(any("overview=full" in u for u in self.net.calls))

    def test_source_labels(self):
        self.assertEqual(SOURCE_LABELS["tankerkoenig"], "Tankerkönig")


if __name__ == "__main__":
    unittest.main()
