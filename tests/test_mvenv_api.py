import os
import sys
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from auraseed.mvenv.manager import MvenvManager
from auraseed.api.server import create_api_server


class TestMvenvApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="auraseed_api_test_")
        cls.manager = MvenvManager(Path(cls.temp_dir))
        cls.server = create_api_server(host="127.0.0.1", port=0, manager=cls.manager)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _http_get(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _http_post(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _http_delete(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}", method="DELETE")
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health_endpoint(self):
        status, data = self._http_get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("service"), "auraseed")
        self.assertEqual(data.get("status"), "ok")

    def test_mvenv_crud_api(self):
        # 1. List initially empty
        status, data = self._http_get("/api/v1/mvenv")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("total"), 0)

        # 2. Create mvenv
        status, created = self._http_post("/api/v1/mvenv", {
            "name": "api-env",
            "base_python": sys.executable,
            "sovereign": False,
            "force": True
        })
        self.assertEqual(status, 201)
        self.assertEqual(created.get("name"), "api-env")

        # 3. Get mvenv info
        status, info = self._http_get("/api/v1/mvenv/api-env")
        self.assertEqual(status, 200)
        self.assertEqual(info.get("name"), "api-env")

        # 4. Verify mvenv
        status, verify = self._http_get("/api/v1/mvenv/api-env/verify")
        self.assertEqual(status, 200)
        self.assertTrue(verify.get("valid"))

        # 5. List now has 1
        status, data = self._http_get("/api/v1/mvenv")
        self.assertEqual(data.get("total"), 1)

        # 6. Delete mvenv
        status, deleted = self._http_delete("/api/v1/mvenv/api-env")
        self.assertEqual(status, 200)
        self.assertTrue(deleted.get("success"))

        # 7. List now empty again
        status, data = self._http_get("/api/v1/mvenv")
        self.assertEqual(data.get("total"), 0)


if __name__ == "__main__":
    unittest.main()
