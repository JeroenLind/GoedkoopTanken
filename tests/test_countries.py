"""Tests voor bronnen per land: validatie, opslag, filter op land en prioriteit."""

import tempfile
import unittest
from pathlib import Path

from goedkooptanken import config, countries, service
from goedkooptanken.models import PETROL95, Station
from goedkooptanken.providers import (PROVIDER_CLASSES, build_providers, catalog, clean_countries, collect_areas,
                                  default_countries, enabled_map)
from goedkooptanken.providers.base import Provider

NL = (51.19, 5.99)    # Roermond
DE = (51.79, 6.14)    # Kleve
BE = (51.2, 4.4)      # Antwerpen


class Fixed(Provider):
    def __init__(self, name, stations):
        self.name, self._stations = name, stations

    def fetch(self, lat, lon, radius_km):
        return list(self._stations)


def station(source, sid, point, price=2.0):
    return Station(id=str(sid), name=f"{source}-{sid}", address="", lat=point[0], lon=point[1],
                   prices={PETROL95: price}, source=source)


class CountryOf(unittest.TestCase):
    def test_known_countries(self):
        self.assertEqual((countries.country_of(*NL), countries.country_of(*DE), countries.country_of(*BE)),
                         ("NL", "DE", "BE"))
        self.assertIsNone(countries.country_of(48.8, 2.3))  # Parijs


class CatalogTests(unittest.TestCase):
    def test_default_puts_official_source_first(self):
        d = default_countries()
        self.assertEqual(d["DE"], ["tankerkoenig", "anwb"])
        self.assertEqual(d["NL"], ["anwb"])
        self.assertEqual(d["BE"], ["anwb"])

    def test_catalog_lists_every_source_and_country(self):
        c = catalog()
        self.assertEqual({s["name"] for s in c["sources"]}, set(PROVIDER_CLASSES))
        self.assertEqual([x["code"] for x in c["countries"]], list(countries.COUNTRIES))
        de = next(x for x in c["countries"] if x["code"] == "DE")
        self.assertEqual(set(de["sources"]), {"anwb", "tankerkoenig"})

    def test_every_source_has_label_and_covers_known_countries(self):
        for cls in PROVIDER_CLASSES.values():
            self.assertTrue(cls.label and cls.countries, cls.name)
            self.assertTrue(set(cls.countries) <= set(countries.COUNTRIES), cls.name)


class CleanTests(unittest.TestCase):
    def test_strict_errors(self):
        for raw, fragment in [({"NL": ["nep"]}, "onbekende bron"), ({"NL": ["tankerkoenig"]}, "dekt dit land niet"),
                              ({"XX": []}, "onbekend land"), ({"DE": ["anwb", "anwb"]}, "twee keer"),
                              ({"DE": "anwb"}, "lijst"), (["anwb"], "lijst per land")]:
            with self.assertRaises(ValueError, msg=str(raw)) as cm:
                clean_countries(raw)
            self.assertIn(fragment, str(cm.exception))

    def test_lenient_ignores_bad_entries_and_fills_missing(self):
        got = clean_countries({"NL": ["nep", "anwb", "anwb"], "XX": ["anwb"], "DE": ["anwb"]}, strict=False)
        self.assertEqual(got["NL"], ["anwb"])
        self.assertEqual(got["DE"], ["anwb"])          # volgorde van de gebruiker blijft
        self.assertEqual(got["BE"], ["anwb"])          # ontbrekend land: standaard
        self.assertNotIn("XX", got)

    def test_empty_list_means_country_off(self):
        self.assertEqual(clean_countries({"BE": []})["BE"], [])


class ConfigTests(unittest.TestCase):
    def test_toml_roundtrip_keeps_priority_order(self):
        cfg = config.from_dict({"providers": {"countries": {"DE": ["anwb", "tankerkoenig"], "BE": []}}})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            config.save(cfg, str(path))
            loaded = config.load(str(path))
        self.assertEqual(loaded.countries["DE"], ["anwb", "tankerkoenig"])
        self.assertEqual(loaded.countries["BE"], [])

    def test_old_config_with_enabled_list_loads_with_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            path.write_text('[providers]\nenabled = ["anwb"]\n', encoding="utf-8")
            self.assertEqual(config.load(str(path)).countries, default_countries())

    def test_to_dict_has_catalog_and_countries(self):
        d = config.to_dict(config.Config())["providers"]
        self.assertEqual(d["countries"]["DE"], ["tankerkoenig", "anwb"])
        self.assertIn("catalog", d)

    def test_request_without_countries_keeps_saved_choice(self):
        base = config.Config(countries={"NL": [], "DE": ["anwb"], "BE": ["anwb"]})
        self.assertEqual(config.from_dict({}, base).countries["NL"], [])

    def test_enabled_map_with_explicit_names_uses_that_order(self):
        m = enabled_map(config.Config(), ["anwb", "tankerkoenig"])
        self.assertEqual(m["DE"], ["anwb", "tankerkoenig"])
        self.assertEqual(m["NL"], ["anwb"])
        with self.assertRaises(ValueError):
            enabled_map(config.Config(), ["nep"])

    def test_build_providers_only_those_switched_on(self):
        cfg = config.Config(countries={"NL": ["anwb"], "DE": [], "BE": []})
        self.assertEqual([p.name for p in build_providers(cfg)], ["anwb"])
        cfg = config.Config(countries={"NL": [], "DE": [], "BE": []})
        self.assertEqual(build_providers(cfg), [])


class CollectTests(unittest.TestCase):
    AREAS = [(51.5, 5.5, 60.0)]

    def test_station_only_counts_where_its_source_is_on(self):
        tk = Fixed("tankerkoenig", [station("tankerkoenig", 1, DE), station("tankerkoenig", 2, NL)])
        anwb = Fixed("anwb", [station("anwb", 3, NL), station("anwb", 4, DE), station("anwb", 5, BE)])
        enabled = {"NL": ["anwb"], "DE": ["tankerkoenig"], "BE": []}
        stations, msgs, _ = collect_areas([tk, anwb], self.AREAS, enabled=enabled)
        self.assertEqual(sorted(s.name for s in stations), ["anwb-3", "tankerkoenig-1"])
        self.assertIn("buiten de landen", msgs["anwb"])

    def test_priority_decides_duplicate_per_country(self):
        near = (DE[0] + 0.0002, DE[1])  # ca. 22 m verderop
        tk = Fixed("tankerkoenig", [station("tankerkoenig", 1, DE, 2.0)])
        anwb = Fixed("anwb", [station("anwb", 2, near, 1.9)])
        for order, winner in ((["tankerkoenig", "anwb"], "tankerkoenig"), (["anwb", "tankerkoenig"], "anwb")):
            dropped = []
            stations, _, _ = collect_areas([anwb, tk], self.AREAS, dropped=dropped,
                                           enabled={"NL": ["anwb"], "DE": order, "BE": ["anwb"]})
            self.assertEqual([s.source for s in stations], [winner], order)
            self.assertEqual(len(dropped), 1)

    def test_source_off_in_country_does_not_block_duplicate_elsewhere(self):
        anwb = Fixed("anwb", [station("anwb", 1, DE)])
        stations, _, _ = collect_areas([anwb], self.AREAS, enabled={"NL": ["anwb"], "DE": [], "BE": []})
        self.assertEqual(stations, [])

    def test_without_enabled_nothing_is_filtered(self):
        anwb = Fixed("anwb", [station("anwb", 1, (48.8, 2.3))])
        self.assertEqual(len(collect_areas([anwb], self.AREAS)[0]), 1)


class ServiceWarningTests(unittest.TestCase):
    def test_warns_for_country_without_source_in_search_area(self):
        enabled = {"NL": ["anwb"], "DE": [], "BE": ["anwb"]}
        w = service._countries_without_source(enabled, [(NL[0], NL[1], 20.0)])   # Roermond, 20 km reikt tot DE
        self.assertEqual(len(w), 1)
        self.assertIn("Duitsland", w[0])

    def test_no_warning_when_country_far_away(self):
        enabled = {"NL": ["anwb"], "DE": [], "BE": ["anwb"]}
        self.assertEqual(service._countries_without_source(enabled, [(52.37, 4.9, 20.0)]), [])  # Amsterdam

    def test_search_without_any_source_is_an_error(self):
        cfg = config.Config(home_lat=NL[0], home_lon=NL[1], fuel="petrol95", consumption=7.0,
                            countries={"NL": [], "DE": [], "BE": []})
        with self.assertRaises(service.SearchError) as cm:
            service.search(cfg)
        self.assertIn("geen enkele bron", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
