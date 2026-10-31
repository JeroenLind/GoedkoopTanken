"""Tests voor de lokale cache: hergebruik, verlopen, terugval en afscherming van oude data."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from goedkooptanken import cache as cachemod
from goedkooptanken import config, service, web
from goedkooptanken import http as fhttp
from goedkooptanken.cache import FetchInfo, StationCache, fetch_cached, plan_fetch
from goedkooptanken.geo import haversine_km
from goedkooptanken.models import PETROL95, Station
from goedkooptanken.providers.base import Provider
from test_all import FakeNet, anwb_station

HOME = (51.19, 5.99)
HOUR = 3600


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeProvider(Provider):
    """Levert stations binnen de gevraagde cirkel, net als een echte bron, en telt de aanroepen."""

    def __init__(self, name="fake", max_radius_km=None, open_flag=True):
        self.name = name
        self.max_radius_km = max_radius_km
        self.calls = []
        self.fail = None
        self.stations = [Station(f"s{i}", f"Station {i}", HOME[0] + dlat, HOME[1] + dlon, name,
                                 prices={PETROL95: 2.0 + i / 100}, is_open=open_flag)
                         for i, (dlat, dlon) in enumerate([(0.01, 0.0), (0.05, 0.02), (0.12, 0.05),
                                                           (0.2, 0.1), (-0.15, -0.1), (0.4, 0.3)])]

    def fetch(self, lat, lon, radius_km):
        self.calls.append((lat, lon, radius_km))
        if self.fail:
            raise fhttp.FetchError(self.fail)
        return [s for s in self.stations if haversine_km(lat, lon, s.lat, s.lon) <= radius_km]


class CacheCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.cache = StationCache(self.tmp.name, clock=self.clock)
        self.p = FakeProvider()

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, lat=HOME[0], lon=HOME[1], r=10, refresh=False, max_age=12 * HOUR, provider=None):
        return fetch_cached(provider or self.p, lat, lon, r, self.cache, max_age, refresh)

    def test_second_request_comes_from_cache(self):
        s1, i1 = self.get()
        s2, i2 = self.get()
        self.assertEqual((i1.origin, i2.origin), ("live", "cache"))
        self.assertEqual(len(self.p.calls), 1)
        self.assertEqual([s.id for s in s1], [s.id for s in s2])

    def test_nearby_position_still_hits_and_is_filtered_on_true_position(self):
        self.get()
        lat, lon = HOME[0] + 0.02, HOME[1] + 0.02  # ca. 2,5 km verderop
        stations, info = self.get(lat, lon, r=10)
        self.assertEqual(info.origin, "cache")
        self.assertEqual(len(self.p.calls), 1)
        for s in stations:
            self.assertLessEqual(haversine_km(lat, lon, s.lat, s.lon), 10)
        expected = {s.id for s in self.p.stations if haversine_km(lat, lon, s.lat, s.lon) <= 10}
        self.assertEqual({s.id for s in stations}, expected)  # niets gemist, niets teveel

    def test_far_position_misses(self):
        self.get()
        self.get(HOME[0] + 0.3, HOME[1], r=10)
        self.assertEqual(len(self.p.calls), 2)

    def test_larger_radius_than_cached_misses(self):
        self.get(r=5)
        self.get(r=25)
        self.assertEqual(len(self.p.calls), 2)

    def test_expired_entry_is_refetched(self):
        self.get()
        self.clock.t += 12 * HOUR + 1
        _, info = self.get()
        self.assertEqual(info.origin, "live")
        self.assertEqual(len(self.p.calls), 2)

    def test_refresh_bypasses_cache(self):
        self.get()
        _, info = self.get(refresh=True)
        self.assertEqual((info.origin, len(self.p.calls)), ("live", 2))

    def test_failure_falls_back_to_stale_data_with_message(self):
        self.get()
        self.clock.t += 20 * HOUR
        self.p.fail = "HTTP 503"
        stations, info = self.get()
        self.assertEqual(info.origin, "stale")
        self.assertIn("503", info.error)
        self.assertGreater(len(stations), 0)
        self.assertIn("cache van 20 uur geleden", info.describe())

    def test_failure_without_cache_raises(self):
        self.p.fail = "offline"
        with self.assertRaises(fhttp.FetchError):
            self.get()

    def test_very_old_entry_is_not_used_as_fallback(self):
        self.get()
        self.clock.t += 8 * 24 * HOUR
        self.p.fail = "offline"
        with self.assertRaises(fhttp.FetchError):
            self.get()

    def test_capped_provider_never_loses_stations_at_the_edge(self):
        capped = FakeProvider("capped", max_radius_km=25)
        # straal 25 + marge past niet onder de limiet: exact deze zoekopdracht opslaan
        self.assertEqual(plan_fetch(*HOME, 25, 25), (HOME[0], HOME[1], 25))
        stations, _ = self.get(r=25, provider=capped)
        self.assertEqual(capped.calls[0][2], 25)
        self.assertEqual({s.id for s in stations},
                         {s.id for s in capped.stations if haversine_km(*HOME, s.lat, s.lon) <= 25})
        self.get(r=25, provider=capped)                 # dezelfde positie: treffer
        self.assertEqual(len(capped.calls), 1)
        self.get(HOME[0] + 0.02, HOME[1], r=25, provider=capped)   # iets verschoven: misser, geen verkeerde treffer
        self.assertEqual(len(capped.calls), 2)

    def test_request_larger_than_provider_cap_is_clamped_consistently(self):
        capped = FakeProvider("capped", max_radius_km=25)
        self.get(r=40, provider=capped)
        self.get(r=40, provider=capped)
        self.assertEqual(len(capped.calls), 1)
        self.assertEqual(capped.calls[0][2], 25)

    def test_capped_provider_small_radius_uses_tiles(self):
        capped = FakeProvider("capped", max_radius_km=25)
        self.get(r=10, provider=capped)
        self.get(HOME[0] + 0.02, HOME[1] + 0.02, r=10, provider=capped)
        self.assertEqual(len(capped.calls), 1)

    def test_open_flag_dropped_for_old_cache_but_kept_when_fresh(self):
        self.get()
        fresh, _ = self.get()
        self.assertTrue(all(s.is_open is True for s in fresh))
        self.clock.t += HOUR
        old, info = self.get()
        self.assertEqual(info.origin, "cache")
        self.assertTrue(all(s.is_open is None for s in old))
        self.assertTrue(all(s.is_open is True for s in self.cache.load("fake")[0].stations))  # opslag blijft heel

    def test_corrupt_file_is_ignored_and_overwritten(self):
        Path(self.tmp.name, "fake.json").write_text("{kapot", encoding="utf-8")
        _, info = self.get()
        self.assertEqual(info.origin, "live")
        _, info = self.get()
        self.assertEqual(info.origin, "cache")

    def test_wrong_schema_is_ignored(self):
        Path(self.tmp.name, "fake.json").write_text(json.dumps({"schema": 99, "entries": []}), encoding="utf-8")
        self.assertEqual(self.cache.load("fake"), [])

    def test_unwritable_cache_dir_does_not_break_search(self):
        blocker = Path(self.tmp.name, "bestand")
        blocker.write_text("x")
        broken = StationCache(blocker / "submap", clock=self.clock)   # map kan niet worden aangemaakt
        stations, info = fetch_cached(self.p, *HOME, 10, broken, 12 * HOUR)
        self.assertEqual(info.origin, "live")
        self.assertGreater(len(stations), 0)

    def test_newer_larger_entry_replaces_covered_older_one(self):
        self.get(r=3)
        self.clock.t += 60
        self.get(r=10, refresh=True)
        self.assertEqual(len(self.cache.load("fake")), 1)

    def test_clear_and_info(self):
        self.get()
        self.clock.t += 600
        info = self.cache.info()
        self.assertEqual((info["areas"], round(info["newest_age_s"])), (1, 600))
        self.assertEqual(self.cache.clear(), 1)
        self.assertEqual(self.cache.info()["areas"], 0)

    def test_no_cache_object_means_always_live(self):
        for _ in range(2):
            _, info = fetch_cached(self.p, *HOME, 10, None, 0)
            self.assertEqual(info.origin, "live")
        self.assertEqual(len(self.p.calls), 2)

    def test_age_text(self):
        self.assertEqual(cachemod.age_text(20), "minder dan 1 minuut")
        self.assertEqual(cachemod.age_text(25 * 60), "25 min")
        self.assertEqual(cachemod.age_text(5 * HOUR), "5 uur")
        self.assertEqual(cachemod.age_text(72 * HOUR), "3 dagen")


class ServiceCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.net = FakeNet()
        self.net.anwb_stations = [anwb_station(1, 51.195, 5.99, euro95=2.2), anwb_station(2, 51.25, 6.05, euro95=1.95)]
        self.patch = mock.patch.object(fhttp, "fetch_json", self.net)
        self.patch.start()
        self.cfg = config.Config(home_lat=HOME[0], home_lon=HOME[1], fuel="petrol95", consumption=7.0,
                                 countries={"NL": ["anwb"], "DE": ["anwb"], "BE": ["anwb"]}, use_routing=False, cache_dir=str(Path(self.tmp.name) / "c"),
                                 max_extra_min=None)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def anwb_calls(self):
        return sum("api.anwb.nl" in u for u in self.net.calls)

    def test_second_search_makes_no_price_requests(self):
        service.search(self.cfg)
        first = self.anwb_calls()
        out = service.search(self.cfg)
        self.assertGreater(first, 0)
        self.assertEqual(self.anwb_calls(), first)
        self.assertEqual(out.sources["anwb"].origin, "cache")
        self.assertIn("uit cache", out.provider_messages["anwb"])
        self.assertGreater(len(out.results), 0)

    def test_refresh_and_disabled_cache_fetch_again(self):
        service.search(self.cfg)
        n = self.anwb_calls()
        service.search(self.cfg, service.SearchParams(refresh=True))
        self.assertEqual(self.anwb_calls(), 2 * n)
        self.cfg.cache_enabled = False
        service.search(self.cfg)
        service.search(self.cfg)
        self.assertEqual(self.anwb_calls(), 4 * n)

    def test_results_identical_from_cache_and_live(self):
        live = service.search(self.cfg)
        cached = service.search(self.cfg)
        key = lambda o: [(r.station.id, r.price, r.total) for r in o.results]
        self.assertEqual(key(live), key(cached))

    def test_outage_uses_old_cache_and_warns(self):
        service.search(self.cfg)
        path = Path(self.cfg.cache_dir) / "anwb.json"
        raw = json.loads(path.read_text())
        for e in raw["entries"]:
            e["fetched_at"] -= 20 * HOUR          # 20 uur oud: te oud voor 12 uur, bruikbaar als terugval
        path.write_text(json.dumps(raw))
        self.net.anwb_stations = None             # laat de bron falen
        real = self.net.__call__

        def failing(url, headers=None, retries=2):
            if "api.anwb.nl" in url:
                raise fhttp.FetchError("HTTP 503")
            return real(url, headers, retries)
        with mock.patch.object(fhttp, "fetch_json", failing):
            out = service.search(self.cfg)
        self.assertEqual(out.sources["anwb"].origin, "stale")
        self.assertTrue(any("niet bereikbaar" in w and "20 uur" in w for w in out.warnings), out.warnings)
        self.assertGreater(len(out.results), 0)


class CacheConfigAndWebTests(unittest.TestCase):
    def test_config_roundtrip_and_validation(self):
        cfg = config.from_dict({"cache": {"enabled": False, "max_age_hours": "6,5"}})
        self.assertEqual((cfg.cache_enabled, cfg.cache_max_age_hours), (False, 6.5))
        with tempfile.TemporaryDirectory() as d:
            config.save(cfg, str(Path(d) / "c.toml"))
            loaded = config.load(str(Path(d) / "c.toml"))
            self.assertEqual((loaded.cache_enabled, loaded.cache_max_age_hours), (False, 6.5))
            self.assertEqual(loaded.cache_path(), Path(d).resolve() / "cache")
        for bad in ("0", "abc", "1000"):
            with self.assertRaises(ValueError):
                config.from_dict({"cache": {"max_age_hours": bad}})
        self.assertEqual(config.Config().cache_max_age_hours, 12.0)  # standaard: een halve dag

    def test_web_cache_endpoints(self):
        with tempfile.TemporaryDirectory() as d:
            app = web.App(str(Path(d) / "config.toml"))
            self.assertEqual(app.cache_info()["areas"], 0)
            StationCache(app.current().cache_path()).store(
                "anwb", cachemod.Entry((51.0, 6.0), 10.0, __import__("time").time(), []))
            info = app.cache_info()
            self.assertEqual(info["areas"], 1)
            self.assertLess(info["newest_age_min"], 1)
            self.assertEqual(app.cache_clear(), {"cleared": 1})
            self.assertEqual(app.cache_info()["areas"], 0)


if __name__ == "__main__":
    unittest.main()
