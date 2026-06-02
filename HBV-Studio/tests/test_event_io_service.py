from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.event_io import read_csv_flexible, read_event_table_file  # noqa: E402


class EventIoServiceTests(unittest.TestCase):
    def test_read_event_table_file_extracts_events_from_json_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.json"
            path.write_text(
                json.dumps({"events": [{"event_id": "E1"}, "skip", {"id": "E2"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            events = read_event_table_file(path)

        self.assertEqual(events, [{"event_id": "E1"}, {"id": "E2"}])

    def test_read_event_table_file_accepts_chinese_event_table_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.geojson"
            path.write_text(
                json.dumps({"\u4e8b\u4ef6\u8868": [{"event_id": "E1"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            events = read_event_table_file(path)

        self.assertEqual(events, [{"event_id": "E1"}])

    def test_read_event_table_file_cleans_csv_column_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.csv"
            path.write_text(" event_id , score_start \nE1,2026-01-01\n", encoding="utf-8")

            events = read_event_table_file(path)

        self.assertEqual(events, [{"event_id": "E1", "score_start": "2026-01-01"}])

    def test_read_csv_flexible_falls_back_to_gbk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.csv"
            path.write_text("\u4e8b\u4ef6\u7f16\u53f7\nE1\n", encoding="gbk")

            frame = read_csv_flexible(path)

        self.assertEqual(frame.columns.tolist(), ["\u4e8b\u4ef6\u7f16\u53f7"])
        self.assertEqual(frame.iloc[0, 0], "E1")


if __name__ == "__main__":
    unittest.main()
