from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.json_utils import (  # noqa: E402
    json_dumps_safe,
    json_safe_value,
    read_json_file,
    write_json_file,
)


class JsonUtilsServiceTests(unittest.TestCase):
    def test_json_safe_value_replaces_non_finite_floats_recursively(self) -> None:
        payload = {
            "ok": 1.25,
            "nan": float("nan"),
            "items": [float("inf"), {"nested": -float("inf")}],
            "pair": (1.0, float("nan")),
        }

        safe = json_safe_value(payload)

        self.assertEqual(
            safe,
            {
                "ok": 1.25,
                "nan": None,
                "items": [None, {"nested": None}],
                "pair": [1.0, None],
            },
        )

    def test_json_dumps_safe_rejects_raw_non_finite_json_output(self) -> None:
        text = json_dumps_safe({"value": math.nan, "label": "\u6cb1\u6cb1\u6cb3"}, indent=2)

        self.assertIn('"value": null', text)
        self.assertIn('"label": "\u6cb1\u6cb1\u6cb3"', text)
        self.assertNotIn("NaN", text)

    def test_read_json_file_accepts_utf8_sig(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("\ufeff" + json.dumps({"name": "test"}, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(read_json_file(path), {"name": "test"})

    def test_write_json_file_removes_runtime_config_path_and_creates_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "config.json"

            write_json_file(path, {"_config_path": "runtime-only", "value": float("inf")})
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data, {"value": None})


if __name__ == "__main__":
    unittest.main()
