"""Tests voor de Home Assistant-koppeling en de Ingress-modus (met een nep-Supervisor)."""

import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
from unittest import mock

from goedkooptanken import ha, web
from test_web import free_port

STATES = [
    {"entity_id": "device_tracker.oppo", "attributes": {"latitude": 51.19, "longitude": 5.99,
                                                        "gps_accuracy": 12, "friendly_name": "Oppo Jeroen"}},
    {"entity_id": "device_tracker.zonder", "attributes": {}},
    {"entity_id": "light.lamp", "attributes": {"latitude": 1, "longitude": 1}},
]
SEEN = []


class FakeSupervisor(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append((self.path, self.headers.get("Authorization")))
        if self.path == "/states":
            body = STATES
        elif self.path == "/states/device_tracker.oppo":
            body = STATES[0]
        else:
            self.send_response(404); self.end_headers(); return
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class HATests(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeSupervisor)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        SEEN.clear()
        patches = [mock.patch.object(ha, "API", f"http://127.0.0.1:{self.srv.server_address[1]}"),
                   mock.patch.dict("os.environ", {"SUPERVISOR_TOKEN": "geheim-token"})]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def test_location_and_trackers(self):
        self.assertEqual(ha.location("device_tracker.oppo"), (51.19, 5.99, 12.0))
        self.assertEqual(ha.trackers(), [{"entity_id": "device_tracker.oppo", "name": "Oppo Jeroen"}])
        self.assertTrue(all(auth == "Bearer geheim-token" for _, auth in SEEN))

    def test_errors_are_readable_and_hide_token(self):
        for entity in ("device_tracker.bestaat_niet", "light.lamp", ""):
            with self.assertRaises(ha.HAError) as cm:
                ha.location(entity)
            self.assertNotIn("geheim-token", str(cm.exception))

    def test_not_available_without_token(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(ha.available())
            with self.assertRaises(ha.HAError):
                ha.trackers()


class IngressTests(unittest.TestCase):
    def serve(self, ingress):
        d = tempfile.mkdtemp()
        app = web.App(str(Path(d) / "config.toml"))
        port = free_port()
        srv = ThreadingHTTPServer(("127.0.0.1", port), web.make_handler(app, port, ingress))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        return port

    def get(self, port, path, host):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", path, headers={"Host": host})
        r = c.getresponse(); r.read()
        return r.status

    def test_ingress_accepts_any_host_from_supervisor_ip(self):
        port = self.serve(True)
        self.assertEqual(self.get(port, "/api/settings", "homeassistant.local:8123"), 200)

    def test_laptop_mode_still_checks_host(self):
        port = self.serve(False)
        self.assertEqual(self.get(port, "/api/settings", "evil.example"), 403)
        self.assertEqual(self.get(port, "/api/settings", f"127.0.0.1:{port}"), 200)

    def test_ingress_rejects_other_sources(self):
        port = self.serve(True)
        with mock.patch.object(web, "INGRESS_PROXY_IPS", {"172.30.32.2"}):
            self.assertEqual(self.get(port, "/api/settings", "x"), 403)


if __name__ == "__main__":
    unittest.main()
