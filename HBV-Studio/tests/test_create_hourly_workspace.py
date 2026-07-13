from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from create_hourly_workspace import build_hourly_workspace, load_json  # noqa: E402


class CreateHourlyWorkspaceTests(unittest.TestCase):
    def test_load_json_accepts_utf8_bom_and_expands_hydrological_hours(self) -> None:
        config = {
            "流域编号": "demo",
            "时间": {
                "预热开始": "2025-01-01",
                "预热结束": "2025-05-31",
                "率定开始": "2025-06-01",
                "率定结束": "2025-09-10",
                "验证开始": "2025-09-11",
                "验证结束": "2025-10-30",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workspace.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8-sig")
            hourly = build_hourly_workspace(load_json(path))
        self.assertEqual(hourly["时间步长_小时"], 1.0)
        self.assertEqual(hourly["时间"]["预热开始"], "2025-01-01 08:00")
        self.assertEqual(hourly["时间"]["验证结束"], "2025-10-31 07:00")


if __name__ == "__main__":
    unittest.main()
