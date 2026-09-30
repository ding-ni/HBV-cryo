import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.runs import (  # noqa: E402
    RunDetailContext,
    RunExportContext,
    build_run_series_range,
    export_run_excel,
    load_run_detail,
)
from services.time_utils import (  # noqa: E402
    format_timestamp_for_display,
    is_date_only_string,
    normalize_time_step_hours,
)


class RunSeriesCoverageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.time_config = {
            "time_step_hours": 24.0,
            "warmup_start": "2022-01-01",
            "warmup_end": "2025-05-31",
            "calib_start": "2025-06-01",
            "calib_end": "2025-09-10",
            "valid_start": "2025-09-11",
            "valid_end": "2025-10-31",
        }

    def dates(self, start: str, end: str, *, step_hours: float = 24.0) -> list[str]:
        return [item.isoformat() for item in pd.date_range(start, end, freq=pd.Timedelta(hours=step_hours))]

    def write_run(self, run_dir: Path, dates: list[str]) -> None:
        (run_dir / "metadata.json").write_text(
            json.dumps({"time_config": self.time_config}), encoding="utf-8"
        )
        (run_dir / "simulation.csv").write_text(
            "date,q_sim,q_obs\n" + "".join(f"{item},1.0,\n" for item in dates), encoding="utf-8"
        )

    def detail_context(self) -> RunDetailContext:
        return RunDetailContext(
            resolve_path=lambda raw, **kwargs: Path(raw),
            read_json_file=lambda path: json.loads(path.read_text(encoding="utf-8")),
            normalize_run_metadata=lambda meta, **kwargs: (meta, None),
            run_update_timestamps=lambda path: (1.0, 1),
            safe_float=lambda value: float(value) if value else None,
            build_hydrology_summary=lambda meta, path: {},
            ensure_hydrology_diagnostic_report=lambda path, meta, summary: summary,
            build_run_summary=lambda path, meta, config, **kwargs: {
                "path": str(path), "time_config": meta["time_config"]
            },
            is_studio_editable_metadata=lambda meta, config: True,
        )

    def export_context(self) -> RunExportContext:
        return RunExportContext(
            resolve_path=lambda raw, **kwargs: Path(raw),
            read_json_file=lambda path: json.loads(path.read_text(encoding="utf-8")),
            normalize_time_step_hours=normalize_time_step_hours,
            is_date_only_string=is_date_only_string,
            format_timestamp_for_display=format_timestamp_for_display,
            slugify_workspace_name=lambda value: "test_run",
            to_display_path=lambda path: str(path),
        )

    def test_complete_1400_day_result_recognizes_equivalent_date_formats(self) -> None:
        dates = self.dates("2022-01-01", "2025-10-31")
        coverage = build_run_series_range(dates, self.time_config)
        self.assertEqual(coverage["valid_points"], 1400)
        self.assertEqual(coverage["actual_start"], "2022-01-01")
        self.assertEqual(coverage["actual_end"], "2025-10-31")
        self.assertTrue(coverage["warmup_covered"])
        self.assertTrue(coverage["full_period_covered"])
        self.assertTrue(coverage["continuous"])

    def test_153_day_saved_result_does_not_inherit_configured_warmup_coverage(self) -> None:
        coverage = build_run_series_range(self.dates("2025-06-01", "2025-10-31"), self.time_config)
        self.assertEqual(coverage["valid_points"], 153)
        self.assertEqual(coverage["actual_start"], "2025-06-01")
        self.assertFalse(coverage["warmup_covered"])
        self.assertFalse(coverage["full_period_covered"])
        self.assertTrue(coverage["continuous"])

    def test_saved_warmup_does_not_imply_validation_endpoint_is_saved(self) -> None:
        coverage = build_run_series_range(self.dates("2022-01-01", "2025-09-30"), self.time_config)
        self.assertTrue(coverage["warmup_covered"])
        self.assertFalse(coverage["full_period_covered"])
        self.assertEqual(coverage["actual_end"], "2025-09-30")

    def test_internal_gap_is_detected_before_chart_sampling(self) -> None:
        dates = self.dates("2022-01-01", "2025-10-31")
        dates.remove("2023-01-02T00:00:00")
        coverage = build_run_series_range(dates, self.time_config)
        self.assertFalse(coverage["warmup_covered"])
        self.assertFalse(coverage["full_period_covered"])
        self.assertFalse(coverage["continuous"])

    def test_invalid_or_duplicate_dates_do_not_claim_complete_saved_output(self) -> None:
        dates = self.dates("2022-01-01", "2025-10-31")
        for extra, key in [("bad-date", "invalid_date_count"), (dates[0], "duplicate_date_count")]:
            with self.subTest(extra=extra):
                coverage = build_run_series_range(dates + [extra], self.time_config)
                self.assertEqual(coverage[key], 1)
                self.assertFalse(coverage["full_period_covered"])

    def test_hourly_dates_cover_actual_configured_end_and_warmup(self) -> None:
        config = {
            "time_step_hours": 1.0,
            "warmup_start": "2025-01-01 00:00",
            "warmup_end": "2025-01-01 23:00",
            "calib_start": "2025-01-02 00:00",
            "valid_end": "2025-01-02 23:00",
        }
        dates = self.dates("2025-01-01", "2025-01-02 23:00", step_hours=1.0)
        complete = build_run_series_range(dates, config)
        truncated = build_run_series_range(dates[24:], config)
        self.assertTrue(complete["warmup_covered"])
        self.assertTrue(complete["full_period_covered"])
        self.assertEqual(complete["actual_end"], "2025-01-02 23:00")
        self.assertEqual(truncated["actual_start"], "2025-01-02 00:00")
        self.assertFalse(truncated["warmup_covered"])
        self.assertFalse(truncated["full_period_covered"])

    def test_result_detail_uses_saved_csv_dates_without_mutating_saved_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_run(run_dir, self.dates("2025-06-01", "2025-10-31"))
            before = {item.name: item.read_bytes() for item in run_dir.iterdir()}
            detail = load_run_detail(str(run_dir), self.detail_context())
            self.assertEqual(detail["series_range"]["actual_start"], "2025-06-01")
            self.assertFalse(detail["series_range"]["warmup_covered"])
            self.assertFalse(detail["series_range"]["full_period_covered"])
            self.assertEqual(detail["run"]["series_range"], detail["series_range"])
            self.assertEqual({item.name: item.read_bytes() for item in run_dir.iterdir()}, before)

    def test_hourly_date_only_end_requires_the_last_hour_of_each_day(self) -> None:
        dates = self.dates("2025-01-01", "2025-01-02 23:00", step_hours=1.0)
        missing_last_warmup_hour = [item for item in dates if item != "2025-01-01T23:00:00"]
        for end_key in ("valid_end", "calib_end", "forecast_end"):
            with self.subTest(end_key=end_key):
                config = {
                    "time_step_hours": 1.0,
                    "warmup_start": "2025-01-01",
                    "warmup_end": "2025-01-01",
                    "calib_start": "2025-01-02",
                    end_key: "2025-01-02",
                }
                truncated = build_run_series_range(dates[:25], config)
                complete = build_run_series_range(dates, config)
                missing_warmup_hour = build_run_series_range(missing_last_warmup_hour, config)
                self.assertEqual(truncated["valid_points"], 25)
                self.assertTrue(truncated["warmup_covered"])
                self.assertFalse(truncated["full_period_covered"])
                self.assertEqual(complete["valid_points"], 48)
                self.assertTrue(complete["warmup_covered"])
                self.assertTrue(complete["full_period_covered"])
                self.assertFalse(missing_warmup_hour["warmup_covered"])
                self.assertFalse(missing_warmup_hour["full_period_covered"])

    def test_export_rejects_unavailable_dates_without_requesting_new_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_run(run_dir, self.dates("2025-06-01", "2025-10-31"))
            for start, end in [("2022-01-01", "2025-10-31"), ("2025-06-01", "2025-11-01")]:
                with self.subTest(start=start, end=end), self.assertRaises(ValueError) as caught:
                    export_run_excel(
                        {"path": str(run_dir), "start_date": start, "end_date": end}, self.export_context()
                    )
                message = str(caught.exception)
                self.assertIn("2025-06-01 至 2025-10-31", message)
                self.assertNotIn("新版", message)
                self.assertNotIn("重新率定", message)
            self.assertFalse((run_dir / "导出").exists())

    def test_export_default_uses_all_available_saved_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_run(run_dir, self.dates("2025-06-01", "2025-10-31"))
            result = export_run_excel({"path": str(run_dir)}, self.export_context())
            self.assertEqual(result["start"], "2025-06-01")
            self.assertEqual(result["end"], "2025-10-31")
            self.assertEqual(result["row_count"], 153)
            self.assertTrue(Path(result["path"]).exists())


if __name__ == "__main__":
    unittest.main()
