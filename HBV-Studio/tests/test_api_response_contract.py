import json
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import studio_service as svc  # noqa: E402
from services import api_routes  # noqa: E402

SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "api_response_shape_snapshot.json"


def response_shape(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return {key: response_shape(value[key]) for key in sorted(value)}
    return type(value).__name__


class ApiResponseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = svc.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), svc.StudioHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get_json(self, endpoint: str) -> dict:
        url = f"http://127.0.0.1:{self.port}{endpoint}"
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_smoke_response_shapes_match_snapshot(self) -> None:
        expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        actual = {
            endpoint: response_shape(self.get_json(endpoint))
            for endpoint in sorted(expected)
        }
        self.assertEqual(actual, expected)

    def test_snapshot_endpoints_are_registered_get_routes(self) -> None:
        expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        registered_get_paths = {
            spec.path
            for spec in api_routes.API_ROUTE_SPECS
            if spec.method == "GET"
        }
        snapshot_paths = {urlsplit(endpoint).path for endpoint in expected}
        self.assertTrue(snapshot_paths <= registered_get_paths)


if __name__ == "__main__":
    unittest.main()
