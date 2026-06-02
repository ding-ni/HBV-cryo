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

from services.event_windows import (  # noqa: E402
    EventWindowContext,
    build_expected_forcing_index,
    build_expected_observation_index,
    build_expected_time_index,
    event_forcing_coverage_summary,
    event_observation_coverage_messages,
    event_observation_coverage_summary,
    event_windows_ui_summary,
    input_time_basis_ui_summary,
    normalized_flood_events,
)


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

    def test_build_expected_time_index_uses_continuous_period(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u65f6\u95f4": {
                "\u9884\u70ed\u5f00\u59cb": "2026-01-01",
                "\u7387\u5b9a\u5f00\u59cb": "2026-01-03",
                "\u7387\u5b9a\u7ed3\u675f": "2026-01-05",
                "\u9a8c\u8bc1\u7ed3\u675f": "2026-01-07",
            },
        }

        index = build_expected_time_index(config)
        observation_index = build_expected_observation_index(config, self._context())

        self.assertIsNotNone(index)
        self.assertEqual(len(index), 7)
        self.assertEqual(index[0], pd.Timestamp("2026-01-01"))
        self.assertEqual(index[-1], pd.Timestamp("2026-01-07"))
        self.assertIsNotNone(observation_index)
        self.assertEqual(len(observation_index), 5)
        self.assertEqual(observation_index[0], pd.Timestamp("2026-01-03"))

    def test_build_expected_time_index_expands_hourly_date_only_end(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 1,
            "\u65f6\u95f4": {
                "\u9884\u70ed\u5f00\u59cb": "2026-01-01",
                "\u7387\u5b9a\u7ed3\u675f": "2026-01-02",
            },
        }

        index = build_expected_time_index(config)

        self.assertIsNotNone(index)
        self.assertEqual(len(index), 48)
        self.assertEqual(index[-1], pd.Timestamp("2026-01-02 23:00"))

    def test_expected_indexes_use_valid_event_windows(self) -> None:
        config = {
            "\u4efb\u52a1\u65f6\u6bb5\u6a21\u5f0f": "event_windows",
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u65f6\u95f4": {
                "\u9884\u70ed\u5f00\u59cb": "2026-01-01",
                "\u7387\u5b9a\u5f00\u59cb": "2026-01-02",
                "\u7387\u5b9a\u7ed3\u675f": "2026-12-31",
            },
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u542f\u7528": True,
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "E1",
                        "run_start": "2026-06-01",
                        "score_start": "2026-06-02",
                        "score_end": "2026-06-04",
                        "run_end": "2026-06-05",
                    },
                    {
                        "event_id": "E2",
                        "run_start": "2026-07-10",
                        "score_start": "2026-07-11",
                        "score_end": "2026-07-13",
                        "run_end": "2026-07-14",
                    },
                ],
            },
        }

        forcing_index = build_expected_forcing_index(config, self._context())
        observation_index = build_expected_observation_index(config, self._context())

        self.assertIsNotNone(forcing_index)
        self.assertIsNotNone(observation_index)
        self.assertEqual(len(forcing_index), 10)
        self.assertEqual(len(observation_index), 6)
        self.assertIn(pd.Timestamp("2026-06-01"), set(forcing_index))
        self.assertIn(pd.Timestamp("2026-06-02"), set(observation_index))
        self.assertNotIn(pd.Timestamp("2026-06-15"), set(forcing_index))

    def test_expected_indexes_fall_back_when_event_mode_has_no_valid_index(self) -> None:
        config = {
            "\u4efb\u52a1\u65f6\u6bb5\u6a21\u5f0f": "event_windows",
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u65f6\u95f4": {
                "\u9884\u70ed\u5f00\u59cb": "2026-01-01",
                "\u7387\u5b9a\u5f00\u59cb": "2026-01-02",
                "\u7387\u5b9a\u7ed3\u675f": "2026-01-05",
            },
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u542f\u7528": True,
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "SHORT",
                        "run_start": "2026-06-01",
                        "score_start": "2026-06-02",
                        "score_end": "2026-06-02",
                        "run_end": "2026-06-03",
                    }
                ],
            },
        }

        forcing_index = build_expected_forcing_index(config, self._context())
        observation_index = build_expected_observation_index(config, self._context())

        self.assertIsNotNone(forcing_index)
        self.assertIsNotNone(observation_index)
        self.assertEqual(len(forcing_index), 5)
        self.assertEqual(forcing_index[0], pd.Timestamp("2026-01-01"))
        self.assertEqual(len(observation_index), 4)
        self.assertEqual(observation_index[0], pd.Timestamp("2026-01-02"))

    def test_event_forcing_coverage_summary_reports_variable_gaps(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u542f\u7528": True,
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "E1",
                        "run_start": "2026-06-01",
                        "score_start": "2026-06-02",
                        "score_end": "2026-06-04",
                        "run_end": "2026-06-05",
                    }
                ],
            },
        }
        event_info = normalized_flood_events(config, self._context())
        full_index = list(pd.date_range("2026-06-01", "2026-06-05", freq="1D"))
        directories = {
            "prec": {"timestamps": full_index},
            "temp": {"timestamps": [ts for ts in full_index if ts != pd.Timestamp("2026-06-03")]},
            "evap": {"timestamps": full_index},
        }

        coverage = event_forcing_coverage_summary(event_info, directories, 24)

        self.assertIsNotNone(coverage)
        self.assertEqual(coverage["status"], "fail")
        self.assertEqual(coverage["event_count"], 1)
        event = coverage["events"][0]
        self.assertEqual(event["variables"]["prec"]["status"], "ok")
        self.assertEqual(event["variables"]["temp"]["missing_steps"], 1)
        self.assertEqual(event["variables"]["temp"]["missing_preview"], ["2026-06-03"])

    def test_event_observation_coverage_messages_split_required_and_diagnostic(self) -> None:
        event_info = {
            "valid_events": [
                {
                    "event_id": "REQ",
                    "name": "\u7387\u5b9a\u4e8b\u4ef6",
                    "purpose": "calibration",
                    "score_start": pd.Timestamp("2026-06-02"),
                    "score_end": pd.Timestamp("2026-06-04"),
                },
                {
                    "event_id": "DIAG",
                    "name": "\u8bca\u65ad\u4e8b\u4ef6",
                    "purpose": "diagnostic",
                    "score_start": pd.Timestamp("2026-07-02"),
                    "score_end": pd.Timestamp("2026-07-04"),
                },
            ],
        }
        observed = pd.Series(
            [1.0, 1.0, 1.0, 1.0, None],
            index=pd.DatetimeIndex(
                [
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                    "2026-07-02",
                    "2026-07-03",
                ]
            ),
        )

        coverage = event_observation_coverage_summary(event_info, observed, 24)
        issues, warnings = event_observation_coverage_messages(coverage)

        self.assertIsNotNone(coverage)
        self.assertEqual(coverage["status"], "warn")
        self.assertEqual(coverage["required_complete_event_count"], 1)
        self.assertEqual(coverage["events"][1]["status"], "warn")
        self.assertEqual(coverage["events"][1]["missing_preview"], ["2026-07-03", "2026-07-04"])
        self.assertEqual(issues, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("\u8bca\u65ad\u4e8b\u4ef6", warnings[0])

    def test_event_windows_ui_summary_formats_event_rows_and_policy(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 1,
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u521d\u59cb\u6761\u4ef6\u7b56\u7565": "\u4e8b\u4ef6\u9884\u70ed",
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "E1",
                        "run_start": "2026-06-01 00:00",
                        "score_start": "2026-06-01 01:00",
                        "score_end": "2026-06-01 06:00",
                        "run_end": "2026-06-01 07:00",
                    }
                ],
            },
        }
        event_info = normalized_flood_events(config, self._context())

        summary = event_windows_ui_summary(event_info, 1)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["valid_event_count"], 1)
        self.assertEqual(summary["time_basis"], "event_windows")
        self.assertEqual(summary["initial_state_policy"], "event_warmup")
        self.assertEqual(summary["valid_events"][0]["score_end"], "2026-06-01 06:00")

    def test_input_time_basis_ui_summary_describes_event_windows(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u542f\u7528": True,
                "\u4e8b\u4ef6\u8868": [
                    {
                        "event_id": "E1",
                        "run_start": "2026-06-01",
                        "score_start": "2026-06-02",
                        "score_end": "2026-06-04",
                        "run_end": "2026-06-05",
                    }
                ],
            },
        }
        event_info = normalized_flood_events(config, self._context())

        summary = input_time_basis_ui_summary(
            config,
            self._context(),
            time_basis="event_windows",
            step_hours=24,
            event_info=event_info,
        )

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["start"], "2026-06-01")
        self.assertEqual(summary["end"], "2026-06-05")
        self.assertEqual(summary["expected_steps"], 5)
        self.assertEqual(summary["valid_event_count"], 1)
        self.assertIn("1 \u573a\u6d2a\u6c34\u4e8b\u4ef6", summary["headline"])

    def test_input_time_basis_ui_summary_describes_continuous_period(self) -> None:
        config = {
            "\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6": 24,
            "\u65f6\u95f4": {
                "\u9884\u70ed\u5f00\u59cb": "2026-01-01",
                "\u7387\u5b9a\u5f00\u59cb": "2026-01-02",
                "\u7387\u5b9a\u7ed3\u675f": "2026-01-04",
            },
        }

        summary = input_time_basis_ui_summary(
            config,
            self._context(),
            time_basis="continuous",
            step_hours=24,
        )

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["start"], "2026-01-01")
        self.assertEqual(summary["end"], "2026-01-04")
        self.assertEqual(summary["expected_steps"], 4)
        self.assertEqual(summary["items"][2]["value"], "4")

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
