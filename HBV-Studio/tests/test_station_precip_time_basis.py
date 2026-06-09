import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

import pandas as pd

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import studio_service as svc  # noqa: E402


def _write_station_files(root: Path, timestamps: pd.DatetimeIndex, missing: Optional[set[pd.Timestamp]] = None) -> tuple[Path, Path]:
    missing = {pd.Timestamp(item) for item in (missing or set())}
    rows = []
    for index, timestamp in enumerate(timestamps, start=1):
        if pd.Timestamp(timestamp) in missing:
            continue
        rows.append(
            {
                "time": pd.Timestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                "S1": 5.0 + index * 0.1,
                "S2": 4.0 + index * 0.1,
            }
        )
    precip_path = root / "station_precip.csv"
    meta_path = root / "station_meta.csv"
    pd.DataFrame(rows).to_csv(precip_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"station_id": "S1", "lon": 92.1, "lat": 34.1},
            {"station_id": "S2", "lon": 92.6, "lat": 34.4},
        ]
    ).to_csv(meta_path, index=False, encoding="utf-8-sig")
    return precip_path, meta_path


def _base_config(root: Path, precip_path: Path, meta_path: Path, *, mode: str) -> dict:
    return {
        "_config_path": str(root / "workspace.json"),
        "时间步长_小时": 24,
        "气象策略": {
            "降水方案": mode,
            "站点降水_csv": str(precip_path),
            "站点信息_csv": str(meta_path),
        },
        "时间": {
            "预热开始": "2025-01-01",
            "率定开始": "2025-01-01",
            "率定结束": "2025-12-31",
            "验证开始": "2025-01-01",
            "验证结束": "2025-12-31",
        },
    }


def _event_config(root: Path, precip_path: Path, meta_path: Path, *, mode: str) -> dict:
    config = _base_config(root, precip_path, meta_path, mode=mode)
    config["任务时段模式"] = "event_windows"
    config["洪水事件率定"] = {
        "启用": True,
        "事件窗口资料": True,
        "事件表": [
            {
                "event_id": "E202505",
                "purpose": "calibration",
                "run_start": "2025-05-01",
                "score_start": "2025-05-02",
                "score_end": "2025-05-04",
                "run_end": "2025-05-05",
            },
            {
                "event_id": "E202509",
                "purpose": "validation",
                "run_start": "2025-09-01",
                "score_start": "2025-09-02",
                "score_end": "2025-09-04",
                "run_end": "2025-09-05",
            },
        ],
    }
    return config


class StationPrecipTimeBasisTests(unittest.TestCase):
    def test_continuous_full_year_does_not_accept_flood_season_station_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flood_season = pd.date_range("2025-05-01", "2025-10-31", freq="D")
            precip_path, meta_path = _write_station_files(root, flood_season)

            grid_bias = svc.analyze_station_precip_inputs(
                _base_config(root, precip_path, meta_path, mode="grid_plus_station_bias"),
                step_hours=24,
            )
            self.assertEqual(grid_bias["status"], "warn")
            self.assertEqual(grid_bias["time_basis"], svc.TIME_BASIS_CONTINUOUS)
            self.assertLess(grid_bias["coverage_ratio"], 0.99)
            self.assertIn("连续时段", grid_bias["task_context"]["headline"])

            station_only = svc.analyze_station_precip_inputs(
                _base_config(root, precip_path, meta_path, mode="thiessen_station_only"),
                step_hours=24,
            )
            self.assertEqual(station_only["status"], "fail")
            self.assertGreater(station_only["zero_available_steps"], 0)

    def test_event_windows_only_require_station_coverage_inside_event_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_index = pd.DatetimeIndex(
                list(pd.date_range("2025-05-01", "2025-05-05", freq="D"))
                + list(pd.date_range("2025-09-01", "2025-09-05", freq="D"))
            )
            precip_path, meta_path = _write_station_files(root, event_index)

            result = svc.analyze_station_precip_inputs(
                _event_config(root, precip_path, meta_path, mode="thiessen_station_only"),
                step_hours=24,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["time_basis"], svc.TIME_BASIS_EVENT_WINDOWS)
            self.assertEqual(result["expected_time_steps"], 10)
            self.assertEqual(result["event_coverage"][0]["status"], "ok")
            self.assertIn("事件之间允许资料间断", result["task_context"]["headline"])

    def test_daily_check_aggregates_hourly_station_precip_by_hydrological_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hourly_index = pd.date_range("2025-05-01 08:00", periods=48, freq="1h")
            precip_path, meta_path = _write_station_files(root, hourly_index)
            config = _base_config(root, precip_path, meta_path, mode="grid_plus_station_bias")
            config["\u65f6\u95f4"] = {
                "\u9884\u70ed\u5f00\u59cb": "2025-05-01",
                "\u7387\u5b9a\u5f00\u59cb": "2025-05-01",
                "\u7387\u5b9a\u7ed3\u675f": "2025-05-02",
                "\u9a8c\u8bc1\u5f00\u59cb": "2025-05-01",
                "\u9a8c\u8bc1\u7ed3\u675f": "2025-05-02",
            }

            result = svc.analyze_station_precip_inputs(config, step_hours=24)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["expected_time_steps"], 2)
            self.assertEqual(result["covered_time_steps"], 2)
            self.assertEqual(result["zero_available_steps"], 0)
            self.assertTrue(result["station_time_aggregation"]["enabled"])
            self.assertEqual(result["station_time_aggregation"]["day_start_hour"], 8)

    def test_event_window_station_gap_fails_for_station_only_precipitation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_index = pd.DatetimeIndex(
                list(pd.date_range("2025-05-01", "2025-05-05", freq="D"))
                + list(pd.date_range("2025-09-01", "2025-09-05", freq="D"))
            )
            precip_path, meta_path = _write_station_files(root, event_index, missing={pd.Timestamp("2025-09-03")})

            result = svc.analyze_station_precip_inputs(
                _event_config(root, precip_path, meta_path, mode="thiessen_station_only"),
                step_hours=24,
            )
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["zero_available_steps"], 1)
            failed = [item for item in result["event_coverage"] if item["event_id"] == "E202509"][0]
            self.assertEqual(failed["zero_available_steps"], 1)
            self.assertEqual(failed["status"], "fail")

    def test_forecast_context_checks_station_precipitation_by_forecast_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            forecast_index = pd.date_range("2025-05-01", "2025-05-03", freq="D")
            precip_path, meta_path = _write_station_files(root, forecast_index)
            config = _base_config(root, precip_path, meta_path, mode="grid_plus_station_bias")
            config["时间"] = {
                "预热开始": "2025-05-01",
                "率定开始": "2025-05-01",
                "率定结束": "2025-05-03",
                "验证开始": "2025-05-01",
                "验证结束": "2025-05-03",
            }

            result = svc.analyze_station_precip_inputs(config, step_hours=24, context="forecast")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["time_basis"], svc.TIME_BASIS_FORECAST_WINDOW)
            self.assertEqual(result["expected_time_steps"], 3)
            self.assertIn("连续状态预报窗口", result["task_context"]["headline"])


if __name__ == "__main__":
    unittest.main()
