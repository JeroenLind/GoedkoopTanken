"""Tests voor de testknop per bron (offline, met nepantwoorden)."""

import unittest
from unittest import mock

from fuelfinder import config, service
from fuelfinder import http as fhttp
from test_all import TK_RESPONSE, anwb_station


def run(cfg, name, fake, key=None):
    with mock.patch.object(fhttp, "fetch_json", fake):
        return service.test_source(cfg, name, key)


class SourceTestTests(unittest.TestCase):
    def test_tankerkoenig_ok_and_key_not_leaked(self):
        out = run(config.Config(), "tankerkoenig", lambda url, headers=None, retries=2: TK_RESPONSE, key="geheim-1234")
        self.assertTrue(out["ok"], out)
        self.assertGreater(out["stations"], 0)
        self.assertNotIn("geheim-1234", str(out))

    def test_missing_key_gives_advice_without_network(self):
        def boom(*a, **k):
            raise AssertionError("geen netwerk verwacht")
        with mock.patch.dict("os.environ", {}, clear=False):
            out = run(config.Config(tankerkoenig_key=None), "tankerkoenig", boom)
        self.assertFalse(out["ok"])
        self.assertIn("key", out["detail"].lower())

    def test_rejected_key(self):
        bad = lambda url, headers=None, retries=2: {"ok": False, "message": "apikey nicht angegeben"}
        out = run(config.Config(), "tankerkoenig", bad, key="fout-key")
        self.assertFalse(out["ok"])
        self.assertIn("key", out["advice"].lower())
        self.assertNotIn("fout-key", str(out))

    def test_timeout_is_explained(self):
        def slow(url, headers=None, retries=2):
            raise fhttp.FetchError("creativecommons.tankerkoenig.de: The read operation timed out")
        out = run(config.Config(), "tankerkoenig", slow, key="k")
        self.assertFalse(out["ok"])
        self.assertIn("reageert niet", out["advice"])

    def test_network_block_is_not_blamed_on_key(self):
        def blocked(url, headers=None, retries=2):
            raise fhttp.FetchError("host: <urlopen error Tunnel connection failed: 403 Forbidden>")
        out = run(config.Config(), "tankerkoenig", blocked, key="k")
        self.assertIn("verbinding", out["advice"])

    def test_anwb_ok_and_empty(self):
        st = [anwb_station(1, 51.19, 5.99, diesel=1.9)]
        ok = run(config.Config(), "anwb", lambda url, headers=None, retries=2: {"value": st})
        self.assertTrue(ok["ok"], ok)
        empty = run(config.Config(), "anwb", lambda url, headers=None, retries=2: {"value": []})
        self.assertFalse(empty["ok"])
        self.assertIn("geen stations", empty["detail"])

    def test_unknown_source(self):
        with self.assertRaises(service.SearchError):
            service.test_source(config.Config(), "nepbron")

    def test_quick_mode_makes_single_attempt(self):
        calls = []

        class Boom(Exception):
            pass

        def opener(req, timeout=None):
            calls.append(timeout)
            raise OSError("timed out")
        with mock.patch("urllib.request.urlopen", opener), mock.patch("time.sleep"):
            with fhttp.quick(7):
                with self.assertRaises(fhttp.FetchError):
                    fhttp.fetch_json("https://example.org/x")
            self.assertEqual(calls, [7])
            calls.clear()
            with self.assertRaises(fhttp.FetchError):
                fhttp.fetch_json("https://example.org/x")
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
