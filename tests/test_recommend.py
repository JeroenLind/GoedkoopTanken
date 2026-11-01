"""Tests voor de aanrader (tijdwaarde) en de referentie op de route (afstand of tijd)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from goedkooptanken import calc, config
from goedkooptanken.models import Result


def res(name, total, km, minutes):
    """Een doorgerekend station; `km` en `minutes` zijn de omweg (heen = omweg, terug = 0)."""
    r = Result(name, 2.0, km, 0.0, False, total, 0.0, total, minutes)
    r.name = name
    return r


class ReferenceTests(unittest.TestCase):
    def test_distance_picks_the_cheapest_station_within_the_limit(self):
        rs = [res("A", 90.0, 0.0, 5), res("B", 89.0, 0.3, 1), res("C", 85.0, 5.0, 8)]
        ref = calc.pick_reference(rs, calc.NearRule("distance", 0.5, 3), absolute=True)
        self.assertEqual(ref.name, "B")   # B is goedkoper dan A en valt binnen 0,5 km; C ligt te ver

    def test_time_mode_uses_minutes_not_km(self):
        rs = [res("A", 90.0, 0.0, 5), res("B", 91.0, 4.0, 2)]
        self.assertEqual(calc.pick_reference(rs, calc.NearRule("time", 0.5, 3), True).name, "B")
        self.assertEqual(calc.pick_reference(rs, calc.NearRule("distance", 0.5, 3), True).name, "A")

    def test_limits_are_inclusive(self):
        rs = [res("A", 90.0, 0.5, 3), res("B", 95.0, 0.0, 0)]
        self.assertEqual(calc.pick_reference(rs, calc.NearRule("distance", 0.5, 3), True).name, "A")
        self.assertEqual(calc.pick_reference(rs, calc.NearRule("time", 0.5, 3), True).name, "A")

    def test_nothing_within_the_limit_falls_back_to_the_smallest_detour(self):
        rs = [res("A", 90.0, 2.0, 4), res("B", 80.0, 1.2, 6), res("C", 70.0, 9.0, 9)]
        self.assertEqual(calc.pick_reference(rs, calc.NearRule("distance", 0.5, 3), True).name, "B")

    def test_around_search_measures_against_the_nearest_station(self):
        # rondom een locatie is de rit heen en terug nooit 0: het verschil met het dichtstbijzijnde telt
        rs = [res("dichtbij", 90.0, 2.0, 4), res("net ernaast", 89.0, 2.3, 5), res("ver", 80.0, 10.0, 15)]
        ref = calc.pick_reference(rs, calc.NearRule("distance", 0.5, 3), absolute=False)
        self.assertEqual(ref.name, "net ernaast")
        ref = calc.pick_reference(rs, calc.NearRule("time", 0.5, 3), absolute=False)
        self.assertEqual(ref.name, "net ernaast")


class RecommendedTests(unittest.TestCase):
    """De getallen komen uit de berekening van Roermond naar Venlo (31 oktober)."""

    def stations(self):
        return [res("Jet", 85.63, 4.88, 15), res("OIL", 85.66, 2.78, 10), res("Aral", 86.70, 6.33, 9),
                res("Total", 89.60, 0.19, 0)]

    def test_time_value_picks_the_station_that_is_worth_the_drive(self):
        rs = self.stations()
        calc.mark_recommended(rs, 15.0, absolute=True)
        rec = [r.name for r in rs if r.is_recommended]
        self.assertEqual(rec, ["OIL"])
        oil = rs[1]
        self.assertEqual((oil.time_min, oil.time_cost, oil.effective_total), (10, 2.5, 88.16))
        self.assertEqual(rs[0].effective_total, 89.38)   # 85,63 + 15 min x 15 euro per uur

    def test_zero_time_value_chooses_on_price_only(self):
        rs = self.stations()
        calc.mark_recommended(rs, 0.0, absolute=True)
        self.assertEqual([r.name for r in rs if r.is_recommended], ["Jet"])
        self.assertTrue(all(r.time_cost == 0 for r in rs))

    def test_high_time_value_prefers_not_detouring_at_all(self):
        rs = self.stations()
        calc.mark_recommended(rs, 30.0, absolute=True)
        self.assertEqual([r.name for r in rs if r.is_recommended], ["Total"])

    def test_exactly_one_recommended_and_rerun_resets(self):
        rs = self.stations()
        calc.mark_recommended(rs, 15.0, True)
        calc.mark_recommended(rs, 0.0, True)
        self.assertEqual(sum(r.is_recommended for r in rs), 1)

    def test_around_search_counts_time_against_the_quickest_station(self):
        rs = [res("dichtbij", 90.0, 2.0, 6), res("verder", 86.0, 6.0, 14)]
        calc.mark_recommended(rs, 15.0, absolute=False)
        self.assertEqual((rs[0].time_min, rs[1].time_min), (0, 8))
        self.assertEqual(rs[1].time_cost, 2.0)
        self.assertTrue(rs[1].is_recommended)   # 86 + 2 < 90

    def test_empty_list_is_fine(self):
        calc.mark_recommended([], 15.0, True)


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        cfg = config.Config()
        self.assertEqual((cfg.time_value, cfg.near_mode, cfg.near_max_km, cfg.near_max_min), (15.0, "distance", 0.5, 3.0))

    def test_roundtrip_through_dict_and_toml(self):
        cfg = config.from_dict({"search": {"time_value": "20,5", "near_mode": "time", "near_max_km": "0,8",
                                           "near_max_min": "4"}})
        self.assertEqual((cfg.time_value, cfg.near_mode, cfg.near_max_km, cfg.near_max_min), (20.5, "time", 0.8, 4.0))
        d = config.to_dict(cfg)["search"]
        self.assertEqual((d["time_value"], d["near_mode"], d["near_max_km"], d["near_max_min"]), (20.5, "time", 0.8, 4.0))
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            config.save(cfg, str(path))
            again = config.load(str(path))
        self.assertEqual((again.time_value, again.near_mode, again.near_max_km, again.near_max_min), (20.5, "time", 0.8, 4.0))

    def test_zero_time_value_is_allowed(self):
        self.assertEqual(config.from_dict({"search": {"time_value": "0"}}).time_value, 0.0)

    def test_invalid_values_are_refused_with_a_readable_message(self):
        for bad, text in (({"time_value": "-1"}, "Waarde van je tijd"), ({"time_value": "veel"}, "geen getal"),
                          ({"near_mode": "snel"}, "afstand of tijd"), ({"near_max_km": "-0,1"}, "Grens"),
                          ({"near_max_min": "500"}, "Grens")):
            with self.assertRaises(ValueError) as cm:
                config.from_dict({"search": bad})
            self.assertIn(text, str(cm.exception))

    def test_unknown_mode_in_an_old_file_falls_back_to_distance(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            path.write_text('[search]\nnear_mode = "iets"\n', encoding="utf-8")
            self.assertEqual(config.load(str(path)).near_mode, "distance")


if __name__ == "__main__":
    unittest.main()
