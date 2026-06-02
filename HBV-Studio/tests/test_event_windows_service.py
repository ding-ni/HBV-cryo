from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.event_windows import EventWindowContext, normalized_flood_events  # noqa: E402


class EventWindowsServiceTests(unittest.TestCase):
    def _context(self, root: Path | None = None) -> EventWindowContext:
        def resolve_config_related_path(config: dict, raw: object) -> Path | None:
            if not raw:
                return None
            path = Path(str(raw))
            if path.is_absolute() or root is None:
                return path
            return root / path

        return EventWindowContext(resolve_config_related_path=resolve_config_related_path)

    def test_normalized_flood_events_counts_valid_purposes_and_sorts_by_run_start(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u542f\u7528": True,
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "E2",
                        "purpose": "\u9a8c\u8bc1",
                        "run_start": "2026-07-01",
                        "score_start": "2026-07-02",
                        "score_end": "2026-07-04",
                        "run_end": "2026-07-05",
                    },
                    {
                        "event_id": "E1",
                        "purpose": "calibration",
                        "run_start": "2026-06-01",
                        "score_start": "2026-06-02",
                        "score_end": "2026-06-04",
                        "run_end": "2026-06-05",
                    },
                ],
            },
        }

        result = normalized_flood_events(config, self._context())

        self.assertTrue(result["enabled"])
        self.assertEqual(result["valid_event_count"], 2)
        self.assertEqual([event["event_id"] for event in result["valid_events"]], ["E1", "E2"])
        self.assertEqual(result["purpose_counts"], {"calibration": 1, "validation": 1, "diagnostic": 0})
        self.assertEqual(result["valid_events"][0]["time_steps_score"], 3)

    def test_normalized_flood_events_reports_duplicate_unknown_and_short_event(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u521d\u59cb\u6761\u4ef6\u7b56\u7565": "\u56fa\u5b9a\u521d\u503c",
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "E1",
                        "purpose": "unknown",
                        "run_start": "2026-06-01",
                        "score_start": "2026-06-02",
                        "score_end": "2026-06-02",
                        "run_end": "2026-06-03",
                    },
                    {
                        "event_id": "E1",
                        "run_start": "2026-07-01",
                        "score_start": "2026-07-02",
                        "score_end": "2026-07-04",
                        "run_end": "2026-07-05",
                    },
                    "skip",
                ],
            },
        }

        result = normalized_flood_events(config, self._context())

        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["valid_event_count"], 1)
        self.assertEqual(result["purpose_counts"]["diagnostic"], 0)
        self.assertTrue(result["initial_state_warning"])
        self.assertTrue(any("diagnostic" in item for item in result["warnings"]))
        self.assertTrue(any("E1" in item for item in result["errors"]))
        self.assertTrue(any("event_id" in item for item in result["warnings"]) is False)
        self.assertTrue(any("\u4e0d\u662f\u5bf9\u8c61" in item for item in result["warnings"]))

    def test_normalized_flood_events_reads_relative_event_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            event_file = root / "events.json"
            event_file.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "event_id": "E1",
                                "run_start": "2026-06-01",
                                "score_start": "2026-06-02",
                                "score_end": "2026-06-04",
                                "run_end": "2026-06-05",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = {"\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {"\u4e8b\u4ef6\u8868\u8def\u5f84": "events.json"}}

            result = normalized_flood_events(config, self._context(root))

        self.assertEqual(result["valid_event_count"], 1)
        self.assertTrue(result["source_file"].endswith("events.json"))

    def test_normalized_flood_events_reports_missing_event_file(self) -> None:
        config = {"\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {"events_file": "missing.json"}}

        result = normalized_flood_events(config, self._context())

        self.assertEqual(result["valid_event_count"], 0)
        self.assertTrue(any("missing.json" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
