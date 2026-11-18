import gzip
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from edgar.base.errors import BlockedError, NotFoundError
from edgar.base.http import HttpClient


class Handler(BaseHTTPRequestHandler):
    hits = 0
    status = 200
    payload = b'{"ok": true}'

    def do_GET(self):
        type(self).hits += 1
        body = type(self).payload
        if self.path == "/notfound":
            self.send_response(404)
            self.end_headers()
            return
        if type(self).status != 200:
            self.send_response(type(self).status)
            self.end_headers()
            return
        encoding = self.headers.get("Accept-Encoding", "")
        if "gzip" in encoding and self.path != "/plain":
            body = gzip.compress(body)
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.hits = 0
        Handler.status = 200
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        return HttpClient(
            user_agent="edgar-test test@example.com",
            rate_limit=10,
            cache_dir=self.tmp.name,
        )

    def test_gzip_and_json(self):
        client = self.client()
        response = client.get(self.base + "/json", ttl=60)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(response.cache, "miss")
        self.assertEqual(len(client.source_list()), 1)

    def test_cache_hit(self):
        client = self.client()
        client.get(self.base + "/json", ttl=60)
        client.get(self.base + "/json", ttl=60)
        self.assertEqual(Handler.hits, 1)

    def test_refresh(self):
        client = self.client()
        client.get(self.base + "/json", ttl=60)
        client.get(self.base + "/json", ttl=60, refresh=True)
        self.assertEqual(Handler.hits, 2)

    def test_not_found(self):
        with self.assertRaises(NotFoundError):
            self.client().get(self.base + "/notfound", ttl=0)

    def test_contact_required_before_network(self):
        client = HttpClient(
            user_agent="edgar/0.1",
            rate_limit=10,
            cache_dir=self.tmp.name,
        )
        with self.assertRaises(BlockedError):
            client.get("https://www.sec.gov/Archives/edgar/data/1/x.htm", ttl=60)

    def test_cached_archive_needs_no_contact(self):
        url = "https://www.sec.gov/Archives/edgar/data/1/x.htm"
        client = self.client()
        with mock.patch.object(client, "_request_once", return_value=(200, {}, b"hello")):
            client.get(url, ttl=60)
        client = HttpClient(user_agent="edgar/0.1", rate_limit=10, cache_dir=self.tmp.name)
        response = client.get(url, ttl=60)
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.cache, "hit")

    def test_default_user_agent_has_no_placeholder_email(self):
        from edgar.base.env import default_user_agent

        self.assertNotIn("@", default_user_agent())

    def test_stale_cache_on_server_error(self):
        client = self.client()
        url = self.base + "/json"
        client.get(url, ttl=60)
        Handler.status = 500
        with mock.patch("edgar.base.http.time.sleep"):
            response = client.get(url, ttl=60, refresh=True)
        self.assertTrue(response.stale)
        self.assertEqual(response.json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
