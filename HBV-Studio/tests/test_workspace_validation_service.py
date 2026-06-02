from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.workspace_validation import build_engineering_focus_checks  # noqa: E402


class WorkspaceValidationServiceTests(unittest.TestCase):
    def _focus_context(self) -> SimpleNamespace:
        return SimpleNamespace(
            profile_daily="daily",
            profile_labels={"daily": "日尺度", "hourly": "小时尺度"},
            default_min_daily_hours=20,
            object_interbasin="interbasin_with_boundary",
            object_labels={"full_upstream": "完整上游流域"},
            normalize_time_step_hours=lambda value: float(value) if value is not None else None,
        )

    def test_engineering_focus_reports_daily_profile_mismatch(self) -> None:
        checks = build_engineering_focus_checks(
            {},
            self._focus_context(),
            profile="daily",
            object_type="full_upstream",
            step_hours=24.0,
            obs_info={"effective_calibration_mode": "hourly"},
            forcing={"ok": True, "expected_steps": 12, "time_basis_label": "连续时段"},
        )

        self.assertEqual(len(checks), 1)
        daily = checks[0]
        self.assertEqual(daily["id"], "daily_profile")
        self.assertEqual(daily["status"], "fail")
        self.assertIn("观测径流识别为小时尺度", daily["summary"])
        self.assertEqual(daily["items"][1]["value"], "小时尺度")

    def test_engineering_focus_classifies_boundary_inflow_issues(self) -> None:
        checks = build_engineering_focus_checks(
            {},
            self._focus_context(),
            profile="hourly",
            object_type="interbasin_with_boundary",
            step_hours=1.0,
            boundary_csv="inflow.csv",
            boundary_info={
                "coverage_ratio": 0.95,
                "duplicate_count": 0,
                "negative_count": 1,
                "out_of_range_steps": [],
                "zero_count": 0,
                "valid_rows": 10,
                "time_step_hours": 24,
            },
        )

        self.assertEqual(len(checks), 1)
        boundary = checks[0]
        self.assertEqual(boundary["id"], "boundary_inflow")
        self.assertEqual(boundary["status"], "fail")
        self.assertIn("关键问题", boundary["summary"])
        negative_item = next(item for item in boundary["items"] if item["label"] == "负流量记录")
        self.assertEqual(negative_item["status"], "fail")
        coverage_item = next(item for item in boundary["items"] if item["label"] == "覆盖率")
        self.assertEqual(coverage_item["value"], "95.0%")

    def test_engineering_focus_summarizes_station_precip_event_coverage(self) -> None:
        checks = build_engineering_focus_checks(
            {},
            self._focus_context(),
            profile="hourly",
            object_type="full_upstream",
            step_hours=1.0,
            station_precip_info={
                "enabled": True,
                "summary": "站点降水资料可用。",
                "status": "ok",
                "items": [{"label": "站点数", "value": "2", "status": "ok"}],
                "task_context": {"step": 4},
                "event_coverage": [{"status": "ok"}, {"status": "warn"}],
            },
        )

        self.assertEqual(len(checks), 1)
        station = checks[0]
        self.assertEqual(station["id"], "station_precip")
        self.assertEqual(station["status"], "ok")
        self.assertEqual(station["event_coverage_summary"]["ok_count"], 1)
        self.assertEqual(station["event_coverage_summary"]["event_count"], 2)


if __name__ == "__main__":
    unittest.main()
